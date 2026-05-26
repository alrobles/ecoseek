"""ecoseek — Hermes plugin for EcoSeek DiDAL Protocol v2.

Provides tools for the dual-agent architecture (Alpha↔Beta):

  ``didal_protocol``         — full dialectical research loop with complexity-aware routing
  ``classify_prompt``        — classify prompt complexity (direct/didal/didal_literature)
  ``escalate_remote``        — one-shot delegation to Hermes Beta on reumanlab
  ``ecoagent_query``         — execute ecological analysis on EcoAgent (reumanlab) via Hermes
  ``dialectical_exchange``   — legacy DiDAL structured debate
  ``hermes_status``          — check Hermes remote availability and loaded tools
  ``literature_search``      — search local literature cache (litdb)
  ``web_search``             — search the internet (GitHub, scientific APIs, general web)
  ``classify_literature``    — LACS domain-specific literature relevance scoring
  ``train_lacs_model``       — train new LACS domain model on HPC cluster

Emily (Alpha, local) uses these tools to delegate heavy computation to
Hermes (Beta, remote) on reumanlab.  Communication goes directly to
hermes.ecoseek.org — no broker required.

Env vars (set in ~/.hermes/.env or passed via Docker):
  HERMES_REMOTE_URL           - Remote Hermes endpoint (default: https://hermes.ecoseek.org)
  HERMES_ECOSEEK_API_KEY      - API key for hermes.ecoseek.org
  HERMES_REMOTE_MODEL         - Model name on remote (default: hermes)
  HERMES_REMOTE_TIMEOUT       - Request timeout in seconds (default: 300)
  DIDAL_ENABLED               - Enable DiDAL protocol (default: true)
  DIDAL_MAX_CRITIQUE_ROUNDS   - Max critique-revise rounds (default: 2)
  DIDAL_MAX_TURNS             - Max dialogue turns for legacy exchange (default: 12)
  DIDAL_STUCK_THRESHOLD       - Repeated errors before stopping (default: 3)
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration — direct to hermes.ecoseek.org
# ---------------------------------------------------------------------------

_REMOTE_URL = os.environ.get(
    "HERMES_REMOTE_URL", "https://hermes.ecoseek.org"
).rstrip("/")
_API_KEY = os.environ.get("HERMES_ECOSEEK_API_KEY", "")
_MODEL = os.environ.get("HERMES_REMOTE_MODEL", "hermes-fast")
_MODEL_FAST = os.environ.get("HERMES_FAST_MODEL", "hermes-fast")
_MODEL_REASONER = os.environ.get("HERMES_REASONER_MODEL", "hermes-reasoner")
_TIMEOUT = int(os.environ.get("HERMES_REMOTE_TIMEOUT", "60"))
_MAX_TURNS = int(os.environ.get("DIDAL_MAX_TURNS", "12"))
_STUCK_THRESHOLD = int(os.environ.get("DIDAL_STUCK_THRESHOLD", "3"))


def _is_configured() -> bool:
    """Return True when we can reach the remote Hermes (URL + key present)."""
    return bool(_REMOTE_URL and _API_KEY)


# ---------------------------------------------------------------------------
# HTTP helper — direct to hermes.ecoseek.org
# ---------------------------------------------------------------------------

def _hermes_request(
    path: str,
    payload: dict | None = None,
    timeout: int | None = None,
    method: str = "GET",
) -> dict:
    """Send a request to hermes.ecoseek.org and return parsed JSON.

    Uses the Cloudflare-safe HTTP client that falls back to curl when
    Python's urllib is blocked by Cloudflare Bot Fight Mode (error 1010).
    """
    from .http_client import http_get_json, http_post_json

    url = f"{_REMOTE_URL}{path}"
    headers = {}
    if _API_KEY:
        headers["Authorization"] = f"Bearer {_API_KEY}"

    if payload:
        return http_post_json(url, payload, headers, timeout=timeout or _TIMEOUT)
    else:
        result = http_get_json(url, headers, timeout=timeout or _TIMEOUT)
        return result if isinstance(result, dict) else {}


# ---------------------------------------------------------------------------
# Tool: hermes_status
# ---------------------------------------------------------------------------

def hermes_status(task_id: Optional[str] = None) -> str:
    """Check if Hermes remote is available and what tools/plugins are loaded."""
    try:
        health = _hermes_request("/health", timeout=15)
        return json.dumps({
            "success": True,
            "status": health.get("status", "unknown"),
            "platform": health.get("platform", "hermes-agent"),
            "remote_url": _REMOTE_URL,
            "configured": _is_configured(),
        })
    except Exception as exc:
        return json.dumps({
            "success": False,
            "error": str(exc)[:300],
            "remote_url": _REMOTE_URL,
            "configured": _is_configured(),
        })


# ---------------------------------------------------------------------------
# Tool: classify_prompt — complexity classifier
# ---------------------------------------------------------------------------

def classify_prompt_tool(prompt: str, task_id: Optional[str] = None) -> str:
    """Classify a prompt's complexity and recommend a response mode.

    Returns the classification result with mode, score, and reasons.
    """
    from .classifier import classify_complexity
    result = classify_complexity(prompt)
    response = {
        "success": True,
        "mode": result.mode,
        "complexity_score": result.complexity_score,
        "reasons": result.reasons,
        "needs_clarification": result.needs_clarification,
        "expected_depth": result.expected_depth,
    }
    if result.is_execution:
        response["is_execution"] = True
        response["routing_hint"] = (
            "This is an EXECUTION task. Use escalate_remote to send it to "
            "Hermes Beta. Do NOT use didal_protocol — it only generates text "
            "and cannot execute commands, create jobs, or run code."
        )
    if result.is_web_search:
        response["is_web_search"] = True
        response["routing_hint"] = (
            "This is a SEARCH task. Use web_search to find information online. "
            "NEVER say 'I cannot access the internet'. The web_search tool "
            "can search GitHub repos, scientific literature (OpenAlex, Semantic "
            "Scholar, GBIF, PubMed), and the general web via Hermes."
        )
    return json.dumps(response, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool: didal_protocol — full dialectical research loop
# ---------------------------------------------------------------------------

_REASONING_MODE_RE = __import__("re").compile(
    r"^\[reasoning_mode:(fast|deep|auto)\]\s*", __import__("re").IGNORECASE
)

# Map frontend reasoning toggle to DiDAL modes
_REASONING_MODE_MAP = {
    "fast": "direct",           # skip DiDAL, quick answer via hermes-fast
    "deep": "didal_literature", # force full protocol + evidence retrieval
    # "auto" → let classifier decide (no override)
}

# Map frontend reasoning toggle to Hermes model aliases
_REASONING_MODEL_MAP = {
    "fast": _MODEL_FAST,         # hermes-fast: bypass agent loop, sub-second TTFT
    "deep": _MODEL_REASONER,     # hermes-reasoner: bypass + thinking mode
    # "auto" / None → _MODEL_FAST (each stage picks its own model)
}


def didal_protocol_tool(
    prompt: str,
    mode: str = "",
    max_rounds: int = 0,
    task_id: Optional[str] = None,
) -> str:
    """Run the full DiDAL protocol: classify → frame → retrieve → draft → critique → revise → report.

    Parameters
    ----------
    prompt : str
        The user's question or research task.
    mode : str, optional
        Force a specific mode: "direct", "didal", or "didal_literature".
        If empty, the classifier decides automatically.
        The frontend may inject [reasoning_mode:fast|deep|auto] prefix
        to override the classifier based on the user's toggle choice.
    max_rounds : int, optional
        Max critique-revise rounds (default: DIDAL_MAX_CRITIQUE_ROUNDS env or 2).
    """
    # Parse reasoning mode injected by the frontend toggle
    clean_prompt = prompt
    frontend_mode = None
    m = _REASONING_MODE_RE.match(prompt)
    if m:
        frontend_mode = m.group(1).lower()
        clean_prompt = prompt[m.end():]
        logger.info("reasoning_mode override from frontend: %s", frontend_mode)

    # Priority: explicit mode param > frontend toggle > classifier auto
    effective_mode = mode or _REASONING_MODE_MAP.get(frontend_mode or "", "") or None

    # Select Hermes model based on reasoning mode
    # In auto mode, pass None so each protocol stage picks its optimal model
    effective_model = _REASONING_MODEL_MAP.get(frontend_mode or "") if frontend_mode else None

    from .protocol import run_didal_protocol
    return run_didal_protocol(
        prompt=clean_prompt,
        force_mode=effective_mode or None,
        max_rounds=max_rounds,
        task_id=task_id,
        model_override=effective_model,
    )


# ---------------------------------------------------------------------------
# Tool: escalate_remote — one-shot delegation
# ---------------------------------------------------------------------------

def escalate_remote(
    task: str,
    context: str = "",
    urgency: str = "normal",
    task_id: Optional[str] = None,
) -> str:
    """Send a task to Hermes Beta on reumanlab via hermes.ecoseek.org.

    Parameters
    ----------
    task : str
        What the remote agent should do.
    context : str, optional
        Background info or system instructions for Beta.
    urgency : str, optional
        "normal" | "high" (shorter timeout) | "background" (longer timeout).
    """
    if not _is_configured():
        return json.dumps({
            "success": False,
            "error": "hermes_not_configured",
            "message": (
                "Remote escalation requires HERMES_ECOSEEK_API_KEY. "
                "Set it in ~/.hermes/.env or pass via Docker env."
            ),
        })

    messages = []
    if context:
        messages.append({"role": "system", "content": context})
    messages.append({"role": "user", "content": task})

    timeout = _TIMEOUT
    if urgency == "high":
        timeout = min(_TIMEOUT, 120)
    elif urgency == "background":
        timeout = max(_TIMEOUT, 600)

    try:
        data = _hermes_request(
            "/v1/chat/completions",
            payload={"model": _MODEL, "messages": messages},
            timeout=timeout,
        )

        choices = data.get("choices", [])
        if not choices:
            return json.dumps({
                "success": False,
                "error": "empty_response",
                "message": "Hermes Beta returned no choices.",
            })

        content = choices[0].get("message", {}).get("content", "")
        model_used = data.get("model", _MODEL)
        usage = data.get("usage", {})

        logger.info(
            "escalate_remote → %s: model=%s tokens=%s",
            _REMOTE_URL, model_used, usage.get("total_tokens", "?"),
        )

        return json.dumps({
            "success": True,
            "remote_response": content,
            "model": model_used,
            "usage": usage,
            "source": "hermes.ecoseek.org",
        })

    except urllib.error.HTTPError as exc:
        err = ""
        try:
            err = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        logger.warning("escalate_remote HTTP %s: %s", exc.code, err[:200])
        return json.dumps({
            "success": False,
            "error": f"http_{exc.code}",
            "message": f"Hermes Beta returned HTTP {exc.code}.",
            "detail": err[:500],
        })
    except urllib.error.URLError as exc:
        logger.warning("escalate_remote URL error: %s", exc.reason)
        return json.dumps({
            "success": False,
            "error": "connection_error",
            "message": f"Cannot reach Hermes remote: {exc.reason}",
        })
    except Exception as exc:
        logger.exception("escalate_remote unexpected error")
        return json.dumps({
            "success": False,
            "error": "unexpected_error",
            "message": str(exc)[:300],
        })


# ---------------------------------------------------------------------------
# DiDAL protocol helpers (legacy exchange)
# ---------------------------------------------------------------------------

MESSAGE_TYPES = ("plan", "code", "execution_result", "critique", "final")


def _make_msg(sender: str, msg_type: str, content: str, task_id: str, turn: int) -> dict:
    return {
        "from": sender,
        "type": msg_type,
        "content": content,
        "metadata": {
            "turn": turn,
            "task_id": task_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    }


def _detect_stuck(history: list[dict]) -> bool:
    errors = [
        m for m in history
        if m.get("type") in ("execution_result", "critique")
        and "error" in m.get("content", "").lower()
    ]
    if len(errors) < _STUCK_THRESHOLD:
        return False
    recent = errors[-_STUCK_THRESHOLD:]
    first = recent[0].get("content", "")[:200]
    return all(r.get("content", "")[:200] == first for r in recent)


BETA_SYSTEM = """\
You are Beta, the execution specialist in the EcoSeek DiDAL system.

Your role:
1. Execute plans and code from Alpha using your tools and sandbox
2. Critically review Alpha's proposals — point out errors, edge cases, missing deps
3. Report results honestly — never claim success if something failed
4. Suggest improvements when you spot better approaches
5. When the task is complete, respond with FINAL: followed by a summary

You have access to: eco_analyze (GBIF, SDM, diversity, taxonomy), ku_hpc (Slurm HPC),
shell, file editing, web search, and GitHub CLI.

Respond with a JSON object: {"type": "execution_result|critique|final", "content": "..."}
"""


# ---------------------------------------------------------------------------
# Tool: dialectical_exchange — structured Alpha↔Beta debate (legacy)
# ---------------------------------------------------------------------------

def dialectical_exchange(
    task: str,
    plan: str = "",
    max_turns: int = 0,
    task_id: Optional[str] = None,
) -> str:
    """Start a DiDAL exchange: Alpha proposes, Beta executes + critiques, loop until consensus.

    Parameters
    ----------
    task : str
        The user's task description.
    plan : str, optional
        Alpha's proposed plan. Beta will execute and critique it.
    max_turns : int, optional
        Max turns before stopping (default: DIDAL_MAX_TURNS env or 12).
    """
    if not _is_configured():
        return json.dumps({
            "success": False,
            "error": "hermes_not_configured",
            "message": (
                "DiDAL requires HERMES_ECOSEEK_API_KEY to reach Hermes Beta. "
                "Set it in ~/.hermes/.env or pass via Docker env."
            ),
        })

    effective_max = max_turns if max_turns > 0 else _MAX_TURNS
    dialogue_id = task_id or str(uuid.uuid4())[:8]
    history: list[dict] = []
    turn = 0

    alpha_content = f"Task: {task}"
    if plan:
        alpha_content += f"\n\nPlan:\n{plan}"
    history.append(_make_msg("alpha", "plan", alpha_content, dialogue_id, turn))
    turn += 1

    logger.info("didal[%s] started: %s", dialogue_id, task[:100])

    final_result = None

    while turn < effective_max:
        # Build API messages for Beta
        api_messages = [{"role": "system", "content": BETA_SYSTEM}]
        for m in history:
            role = "assistant" if m.get("from") == "beta" else "user"
            api_messages.append({"role": role, "content": m["content"]})

        try:
            data = _hermes_request(
                "/v1/chat/completions",
                payload={"model": _MODEL, "messages": api_messages},
            )
            beta_content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            beta_model = data.get("model", _MODEL)
            beta_usage = data.get("usage", {})
        except Exception as exc:
            logger.warning("didal[%s] beta error turn %d: %s", dialogue_id, turn, exc)
            history.append(_make_msg(
                "beta", "execution_result",
                f"Error communicating with Beta: {exc}",
                dialogue_id, turn,
            ))
            turn += 1
            if _detect_stuck(history):
                break
            continue

        # Parse Beta's response type
        beta_type = "execution_result"
        if beta_content.strip().upper().startswith("FINAL:"):
            beta_type = "final"
            final_result = beta_content[6:].strip()
        else:
            try:
                parsed = json.loads(beta_content)
                if isinstance(parsed, dict) and "type" in parsed:
                    bt = parsed["type"]
                    beta_type = bt if bt in MESSAGE_TYPES else "execution_result"
                    beta_content = parsed.get("content", beta_content)
                    if beta_type == "final":
                        final_result = beta_content
            except (json.JSONDecodeError, KeyError):
                pass

        msg = _make_msg("beta", beta_type, beta_content, dialogue_id, turn)
        msg["metadata"]["model"] = beta_model
        msg["metadata"]["usage"] = beta_usage
        history.append(msg)
        turn += 1

        logger.info("didal[%s] turn %d: beta %s (%d chars)", dialogue_id, turn, beta_type, len(beta_content))

        if beta_type == "final":
            break
        if _detect_stuck(history):
            logger.warning("didal[%s] stuck loop at turn %d", dialogue_id, turn)
            break
        if beta_type == "critique":
            break

    total_tokens = sum(
        m.get("metadata", {}).get("usage", {}).get("total_tokens", 0)
        for m in history
    )

    return json.dumps({
        "success": final_result is not None,
        "dialogue_id": dialogue_id,
        "turns": turn,
        "final_result": final_result,
        "last_beta_response": history[-1]["content"] if history else "",
        "history": history,
        "total_tokens": total_tokens,
        "stuck_loop": _detect_stuck(history),
        "source": "hermes.ecoseek.org",
    })


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

HERMES_STATUS_SCHEMA = {
    "name": "hermes_status",
    "description": (
        "Check if the remote Hermes agent (Beta on reumanlab) is available. "
        "Returns the remote endpoint status, loaded plugins, and connection info. "
        "Use this to verify the remote agent is up before escalating tasks."
    ),
    "parameters": {"type": "object", "properties": {}},
}

CLASSIFY_PROMPT_SCHEMA = {
    "name": "classify_prompt",
    "description": (
        "Classify a user prompt's scientific complexity BEFORE calling "
        "didal_protocol. ALWAYS call this first, then tell the user what mode "
        "was detected and what you will do, THEN call didal_protocol with the "
        "mode parameter. Returns: 'direct' (simple), 'didal' (conceptual), or "
        "'didal_literature' (evidence-backed synthesis). If is_execution=true, "
        "the task is an ACTION (create job, run code, etc.) — you MUST use "
        "escalate_remote instead of didal_protocol. This is fast (~1s) and "
        "gives the user immediate feedback while you prepare the full response."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "The user's question or prompt to classify.",
            },
        },
        "required": ["prompt"],
    },
}

DIDAL_PROTOCOL_SCHEMA = {
    "name": "didal_protocol",
    "description": (
        "Run the full DiDAL (Dialectical Dual-Agent Loop) protocol on a question. "
        "Automatically classifies complexity and routes to the right mode:\n"
        "- direct: simple factual answers (fast, single call)\n"
        "- didal: conceptual questions → structured frame → expert draft → "
        "naive critique → revision → mini-report\n"
        "- didal_literature: complex scientific questions → adds evidence "
        "retrieval + source grounding before synthesis\n\n"
        "USE THIS for any ecological, scientific, or research question. "
        "It produces structured mini-reports for complex questions and fast "
        "answers for simple ones. The protocol handles routing automatically."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "The user's question or research task.",
            },
            "mode": {
                "type": "string",
                "enum": ["", "direct", "didal", "didal_literature"],
                "description": "Force a specific mode. Leave empty for automatic classification.",
            },
            "max_rounds": {
                "type": "integer",
                "description": "Max critique-revise rounds (default: 2).",
            },
        },
        "required": ["prompt"],
    },
}

ESCALATE_REMOTE_SCHEMA = {
    "name": "escalate_remote",
    "description": (
        "Delegate a task to Hermes Beta on reumanlab (hermes.ecoseek.org). "
        "Beta has DeepSeek v4 Pro, KU HPC cluster (A100/MI210 GPUs via Slurm), "
        "eco_analyze (GBIF, SDM, diversity, taxonomy), ku_hpc, GitHub CLI, and "
        "shell access. Use this for ANY task that involves: heavy computation, "
        "HPC jobs, large datasets, ecological pipelines, code execution on "
        "reumanlab, or capabilities beyond your local model. For scientific "
        "QUESTIONS, prefer didal_protocol instead — it adds structured debate "
        "and mini-report formatting."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "What the remote agent should accomplish. Be specific.",
            },
            "context": {
                "type": "string",
                "description": "Background info or instructions for Beta.",
            },
            "urgency": {
                "type": "string",
                "enum": ["normal", "high", "background"],
                "description": "'high' for quick lookups, 'background' for HPC jobs, 'normal' for standard.",
            },
        },
        "required": ["task"],
    },
}

UPLOAD_DOCUMENT_SCHEMA = {
    "name": "upload_document",
    "description": (
        "Upload and index a document (PDF or text) for the user's personal "
        "knowledge base. Once indexed, the document's content will be "
        "automatically searched during DiDAL literature retrieval (highest priority). "
        "Use this when the user provides a PDF or pastes text from a paper."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the PDF or text file to ingest.",
            },
            "text": {
                "type": "string",
                "description": (
                    "Raw text to index directly (use when user pastes text "
                    "instead of providing a file). Either file_path or text is required."
                ),
            },
            "title": {
                "type": "string",
                "description": "Optional paper title (auto-detected if not provided).",
            },
            "authors": {
                "type": "string",
                "description": "Optional authors string.",
            },
        },
        "required": [],
    },
}


def upload_document_tool(
    file_path: str = "",
    text: str = "",
    title: str = "",
    authors: str = "",
    task_id: Optional[str] = None,
) -> str:
    """Ingest a PDF or text into the user's personal knowledge base."""
    if file_path:
        from .pdf_ingest import ingest_pdf
        result = ingest_pdf(file_path)
    elif text:
        from .pdf_ingest import ingest_text
        result = ingest_text(text, filename=title or "pasted_text.txt")
    else:
        result = {"success": False, "error": "Provide either file_path or text."}

    # Override title/authors if user provided them
    if result.get("success") and (title or authors):
        try:
            from .litdb import _connect
            with _connect() as conn:
                doc_id = result.get("id")
                if doc_id:
                    updates = []
                    params = []
                    if title:
                        updates.append("title = ?")
                        params.append(title)
                    if authors:
                        updates.append("authors = ?")
                        params.append(authors)
                    if updates:
                        params.append(doc_id)
                        conn.execute(
                            f"UPDATE user_papers SET {', '.join(updates)} WHERE id = ?",
                            params,
                        )
        except Exception:
            pass

    return json.dumps(result, ensure_ascii=False)


LITERATURE_SEARCH_SCHEMA = {
    "name": "literature_search",
    "description": (
        "Search the local literature database for scientific papers. "
        "Returns cached papers from OpenAlex, GBIF Literature, Semantic Scholar, "
        "Entrez/PubMed, and user-uploaded documents. Also searches cluster FTS5 "
        "indices (36M PubMed + 61K GBIF Literature) via Hermes. Use this for "
        "quick reference lookups without running the full DiDAL protocol."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query (scientific terms, species names, methods).",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results (default: 10).",
            },
        },
        "required": ["query"],
    },
}


def literature_search_tool(
    query: str,
    limit: int = 10,
    task_id: Optional[str] = None,
) -> str:
    """Search local literature cache, user papers, and optionally APIs."""
    from .litdb import search as litdb_search, get_stats, search_user_papers, get_user_paper_stats

    # Search user-uploaded documents first (highest priority)
    user_results = []
    try:
        user_results = search_user_papers(query, limit=min(limit, 5))
    except Exception:
        pass

    # Search the litdb cache
    results = litdb_search(query, limit=limit)

    # If no cache results, try a quick API fetch
    if not results:
        try:
            from .retrieval import retrieve_literature
            lit = retrieve_literature(query=query, tier="A", max_per_source=3)
            results = litdb_search(query, limit=limit)
            if not results:
                results = lit.get("sources", [])[:limit]
        except Exception as exc:
            logger.warning("literature_search API fallback failed: %s", exc)

    # Merge: user papers first, then cache results
    all_results = user_results + results

    stats = {}
    try:
        stats = get_stats()
        user_stats = get_user_paper_stats()
        stats["user_documents"] = user_stats.get("total_documents", 0)
        stats["user_tokens"] = user_stats.get("total_tokens", 0)
    except Exception:
        pass

    return json.dumps({
        "success": True,
        "results": all_results[:limit],
        "count": len(all_results[:limit]),
        "user_papers_found": len(user_results),
        "cache_stats": stats,
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool: web_search — search GitHub, scientific APIs, and general web
# ---------------------------------------------------------------------------

WEB_SEARCH_SCHEMA = {
    "name": "web_search",
    "description": (
        "Search the internet for information. Supports multiple search types: "
        "'github' (search GitHub repositories, code, issues), "
        "'scientific' (search OpenAlex, Semantic Scholar, GBIF, PubMed), "
        "'general' (delegate to Hermes Beta for general web search via SearXNG). "
        "Use this tool whenever the user asks to search, look up, or find information "
        "online. NEVER say 'I cannot access the internet' — use this tool instead."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query.",
            },
            "search_type": {
                "type": "string",
                "enum": ["github", "scientific", "general", "auto"],
                "description": (
                    "Type of search. 'auto' (default) detects automatically: "
                    "github for repo/code queries, scientific for papers/species, "
                    "general for everything else."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results (default: 5).",
            },
        },
        "required": ["query"],
    },
}


def _detect_search_type(query: str) -> str:
    """Auto-detect the best search type from the query."""
    lower = query.lower()
    github_signals = ["github", "repo", "repository", "repositorio", "code", "codigo",
                      "pull request", "pr ", "issue", "commit", "branch", "fork",
                      "alrobles/", "git "]
    scientific_signals = ["paper", "papers", "articulo", "species", "especie",
                          "niche", "ecology", "ecologia", "sdm", "gbif", "phylo",
                          "pubmed", "doi", "abstract"]
    if any(s in lower for s in github_signals):
        return "github"
    if any(s in lower for s in scientific_signals):
        return "scientific"
    return "general"


def _search_github(query: str, limit: int = 5) -> list[dict]:
    """Search GitHub repositories and code via the public API."""
    results = []

    # Search repositories
    repo_url = (
        "https://api.github.com/search/repositories?"
        + urllib.parse.urlencode({"q": query, "per_page": min(limit, 10), "sort": "best match"})
    )
    try:
        req = urllib.request.Request(repo_url, headers={
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "EcoSeek-Emily/1.0",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for item in data.get("items", [])[:limit]:
            results.append({
                "type": "repository",
                "name": item.get("full_name", ""),
                "description": item.get("description", "") or "",
                "url": item.get("html_url", ""),
                "stars": item.get("stargazers_count", 0),
                "language": item.get("language", ""),
                "updated": item.get("updated_at", ""),
                "topics": item.get("topics", []),
            })
    except Exception as exc:
        logger.warning("GitHub repo search failed: %s", exc)

    # If looking for a specific repo (e.g., "alrobles/xsdm"), try direct fetch
    repo_pattern = re.compile(r"(?:^|[\s/])([a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+)")
    match = repo_pattern.search(query)
    if match and not results:
        repo_name = match.group(1)
        direct_url = f"https://api.github.com/repos/{repo_name}"
        try:
            req = urllib.request.Request(direct_url, headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "EcoSeek-Emily/1.0",
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                item = json.loads(resp.read().decode("utf-8"))
            readme_text = ""
            try:
                readme_url = f"https://api.github.com/repos/{repo_name}/readme"
                req2 = urllib.request.Request(readme_url, headers={
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "EcoSeek-Emily/1.0",
                })
                with urllib.request.urlopen(req2, timeout=10) as resp2:
                    readme_data = json.loads(resp2.read().decode("utf-8"))
                import base64
                readme_text = base64.b64decode(readme_data.get("content", "")).decode("utf-8", errors="replace")[:2000]
            except Exception:
                pass
            results.insert(0, {
                "type": "repository_detail",
                "name": item.get("full_name", ""),
                "description": item.get("description", "") or "",
                "url": item.get("html_url", ""),
                "stars": item.get("stargazers_count", 0),
                "forks": item.get("forks_count", 0),
                "language": item.get("language", ""),
                "updated": item.get("updated_at", ""),
                "topics": item.get("topics", []),
                "license": (item.get("license") or {}).get("spdx_id", ""),
                "readme_excerpt": readme_text[:1500] if readme_text else "",
            })
        except Exception as exc:
            logger.warning("GitHub direct repo fetch failed for %s: %s", repo_name, exc)

    return results


def _search_scientific(query: str, limit: int = 5) -> list[dict]:
    """Search scientific literature APIs (OpenAlex, Semantic Scholar, GBIF, Entrez)."""
    from .retrieval import retrieve_literature, evidence_to_dict
    try:
        lit = retrieve_literature(query=query, tier="A", max_per_source=max(2, limit // 3))
        sources = lit.get("sources", [])[:limit]
        return sources
    except Exception as exc:
        logger.warning("Scientific search failed: %s", exc)
        return []


def _search_general_via_hermes(query: str, limit: int = 5) -> list[dict]:
    """Delegate general web search to Hermes Beta (has SearXNG/web access)."""
    if not _is_configured():
        return [{"type": "error", "message": "Hermes not configured for web search"}]

    try:
        data = _hermes_request(
            "/v1/chat/completions",
            payload={
                "model": _MODEL_FAST,
                "messages": [
                    {"role": "system", "content": (
                        "You are a web search assistant. Search the web for the query and "
                        "return results as a JSON array of objects with fields: "
                        "title, url, snippet, source. Return ONLY the JSON array, no markdown."
                    )},
                    {"role": "user", "content": f"Search the web for: {query}\nReturn up to {limit} results."},
                ],
            },
            timeout=30,
        )
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        try:
            parsed = json.loads(content)
            if isinstance(parsed, list):
                return parsed[:limit]
        except json.JSONDecodeError:
            pass
        return [{"type": "web_summary", "content": content[:2000]}]
    except Exception as exc:
        logger.warning("Hermes web search failed: %s", exc)
        return [{"type": "error", "message": f"Web search failed: {exc}"}]


def web_search_tool(
    query: str,
    search_type: str = "auto",
    limit: int = 5,
    task_id: Optional[str] = None,
) -> str:
    """Search GitHub, scientific APIs, or general web."""
    if search_type == "auto":
        search_type = _detect_search_type(query)

    results: list[dict] = []

    if search_type == "github":
        results = _search_github(query, limit)
        if not results and _is_configured():
            results = _search_general_via_hermes(
                f"Search GitHub for: {query}. Use gh CLI if available.", limit,
            )
            if results:
                search_type = "github_via_hermes"
    elif search_type == "scientific":
        results = _search_scientific(query, limit)
    elif search_type == "general":
        results = _search_general_via_hermes(query, limit)
    else:
        results = _search_general_via_hermes(query, limit)

    return json.dumps({
        "success": True,
        "search_type": search_type,
        "query": query,
        "results": results,
        "count": len(results),
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool: ecoagent_query — call EcoAgent tools on reumanlab via Hermes
# ---------------------------------------------------------------------------

_ECOAGENT_ACTIONS = (
    "query_species", "query_papers", "compute_diversity", "compute_clusters",
    "search_literature", "query_pubtator", "fit_sdm", "fit_maxent",
    "evaluate_niche", "resolve_taxonomy", "resolve_worms", "query_cofid",
    "validate_cofid", "extract_triplets", "build_knowledge_graph",
    "query_graph_hosts", "query_graph_parasites", "query_gbif_literature",
    "query_gbif_parquet", "compute_bioclim", "compute_effort_bias",
    "classify_abstract", "predict_susceptibility", "compute_ecological_distance",
    "fit_geotax",
)


def ecoagent_query_tool(
    action: str,
    params: dict | None = None,
    task_id: Optional[str] = None,
) -> str:
    """Execute an ecological analysis action on EcoAgent (reumanlab) via Hermes.

    EcoAgent exposes 25 tools for ecological computation: GBIF queries,
    SDM fitting, diversity metrics, taxonomy resolution, knowledge graphs,
    cofid host-parasite interactions, and more.
    """
    if action not in _ECOAGENT_ACTIONS:
        return json.dumps({
            "success": False,
            "error": "invalid_action",
            "message": f"Unknown action: {action!r}. Available: {', '.join(_ECOAGENT_ACTIONS)}",
        })

    if not _is_configured():
        return json.dumps({
            "success": False,
            "error": "hermes_not_configured",
            "message": "EcoAgent requires HERMES_ECOSEEK_API_KEY to reach reumanlab.",
        })

    from .retrieval import _hermes_eco_analyze
    result = _hermes_eco_analyze(action, {"args": params or {}})

    if result is None:
        return json.dumps({
            "success": False,
            "error": "ecoagent_unreachable",
            "message": "EcoAgent tool_server on reumanlab did not respond via Hermes.",
        })

    return json.dumps({
        "success": True,
        "action": action,
        "result": result,
    }, ensure_ascii=False, default=str)


ECOAGENT_QUERY_SCHEMA = {
    "name": "ecoagent_query",
    "description": (
        "Execute ecological analysis on EcoAgent (reumanlab) via Hermes. "
        "25 tools available: query_species (GBIF occurrences), "
        "query_gbif_literature (GBIF literature search), "
        "resolve_taxonomy (taxonomic name resolution via GBIF/WoRMS), "
        "query_cofid (host-parasite interactions from CoFID), "
        "fit_sdm/fit_maxent (species distribution models), "
        "compute_diversity/compute_clusters (diversity indices), "
        "compute_bioclim (bioclimatic variables), "
        "extract_triplets/build_knowledge_graph (ecological knowledge extraction), "
        "and more. Use this for structured ecological computation."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": list(_ECOAGENT_ACTIONS),
                "description": "The EcoAgent tool to execute.",
            },
            "params": {
                "type": "object",
                "description": (
                    "Parameters for the action. Examples:\n"
                    "  query_species: {\"query\": \"Panthera tigris\", \"limit\": 10}\n"
                    "  resolve_taxonomy: {\"name\": \"Quercus robur\"}\n"
                    "  query_gbif_literature: {\"query\": \"species distribution modeling\", \"limit\": 5}\n"
                    "  query_cofid: {\"query\": \"Mammalia\", \"limit\": 10}\n"
                    "  fit_sdm: {\"species\": \"Panthera onca\", \"method\": \"maxent\"}\n"
                    "  compute_diversity: {\"community_matrix\": [[1,2],[3,4]], \"index\": \"shannon\"}"
                ),
            },
        },
        "required": ["action"],
    },
}


# ---------------------------------------------------------------------------
# Tool: classify_literature — LACS domain-specific relevance scoring
# ---------------------------------------------------------------------------

CLASSIFY_LITERATURE_SCHEMA = {
    "name": "classify_literature",
    "description": (
        "Score scientific abstracts by domain relevance using LACS "
        "(Literature Abstract Classification System). Uses PU-learning "
        "(Positive-Unlabeled) models trained on domain-specific corpora. "
        "Available domains: host-parasite (GMPD+ZOVER), niche-modeling, biodiversity. "
        "Returns a relevance score (0-1) for each abstract. "
        "Use this to filter/rank papers before including them in a synthesis, "
        "or to help the user identify relevant literature for their research."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "abstracts": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of abstract texts to classify.",
            },
            "domain": {
                "type": "string",
                "enum": ["host-parasite", "niche-modeling", "biodiversity"],
                "description": "Domain model to use (default: host-parasite).",
            },
        },
        "required": ["abstracts"],
    },
}


def classify_literature_tool(
    abstracts: list,
    domain: str = "host-parasite",
    task_id: Optional[str] = None,
) -> str:
    """Score abstracts by domain relevance using LACS."""
    from .lacs_classifier import classify_abstracts, AVAILABLE_DOMAINS

    if not abstracts:
        return json.dumps({"success": False, "error": "No abstracts provided"})

    results = classify_abstracts(
        abstracts=[str(a) for a in abstracts],
        domain=domain,
    )

    n_relevant = sum(1 for r in results if r["relevant"])

    return json.dumps({
        "success": True,
        "results": results,
        "summary": {
            "total": len(results),
            "relevant": n_relevant,
            "irrelevant": len(results) - n_relevant,
            "domain": domain,
            "domain_description": AVAILABLE_DOMAINS.get(domain, ""),
        },
    }, ensure_ascii=False)


TRAIN_LACS_MODEL_SCHEMA = {
    "name": "train_lacs_model",
    "description": (
        "Train a new LACS domain model on the HPC cluster using user-provided "
        "positive papers. The model learns to distinguish domain-relevant papers "
        "from random literature using PU-learning (PLUS algorithm). "
        "Requires at least 10 positive abstracts. Random negatives are sampled "
        "from the PubMed FTS5 index (~36M papers). "
        "The trained model is saved on the cluster and can be used with "
        "classify_literature for future scoring."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": "Name for the new domain model (e.g., 'coral-bleaching').",
            },
            "positive_papers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "doi": {"type": "string"},
                        "title": {"type": "string"},
                        "abstract": {"type": "string"},
                    },
                    "required": ["abstract"],
                },
                "description": "Known-positive papers for the domain.",
            },
            "random_sample_size": {
                "type": "integer",
                "description": "Number of random abstracts for unlabeled class (default: 5000).",
            },
        },
        "required": ["domain", "positive_papers"],
    },
}


def train_lacs_model_tool(
    domain: str,
    positive_papers: list,
    random_sample_size: int = 5000,
    task_id: Optional[str] = None,
) -> str:
    """Train a new LACS model on the cluster."""
    from .lacs_classifier import train_lacs_model

    result = train_lacs_model(
        domain=domain,
        positive_abstracts=positive_papers,
        random_sample_size=random_sample_size,
    )
    return json.dumps(result, ensure_ascii=False)


DIALECTICAL_EXCHANGE_SCHEMA = {
    "name": "dialectical_exchange",
    "description": (
        "Legacy DiDAL exchange: Alpha proposes, Beta executes + critiques, "
        "loop until consensus. For scientific QUESTIONS, prefer didal_protocol "
        "instead — it adds automatic complexity classification, structured "
        "critique rounds, evidence retrieval, and mini-report formatting. "
        "Use this only for multi-step EXECUTION tasks (pipelines, HPC workflows, "
        "code review) where the back-and-forth is about running code, not synthesis."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "The user's original task description.",
            },
            "plan": {
                "type": "string",
                "description": "Your proposed plan. Beta will execute and critique it.",
            },
            "max_turns": {
                "type": "integer",
                "description": "Max turns before stopping (default: 12).",
            },
        },
        "required": ["task"],
    },
}


# ---------------------------------------------------------------------------
# Tool: upload_artifact — push large files to GitHub for download
# ---------------------------------------------------------------------------

UPLOAD_ARTIFACT_SCHEMA = {
    "name": "upload_artifact",
    "description": (
        "Upload a large file from the cluster to the ecoseek-artifacts GitHub repo. "
        "Use this when Hermes generates outputs (rasters, CSVs, plots) too large "
        "to return inline. Returns a download URL via raw.githubusercontent.com. "
        "For files <5MB, prefer returning them inline in the response."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "cluster_path": {
                "type": "string",
                "description": "Path to the file on the cluster (e.g., /home/a474r867/work/sdm/output.tif).",
            },
            "artifact_name": {
                "type": "string",
                "description": "Name for the artifact in the repo (e.g., ara_macao_sdm.tif).",
            },
            "session_id": {
                "type": "string",
                "description": "Optional session ID for organizing artifacts.",
            },
        },
        "required": ["cluster_path", "artifact_name"],
    },
}


def upload_artifact_tool(
    cluster_path: str,
    artifact_name: str,
    session_id: str = "",
    task_id: Optional[str] = None,
) -> str:
    """Upload a large file from the cluster to GitHub artifacts repo."""
    from .artifacts import upload_artifact_via_hermes
    result = upload_artifact_via_hermes(
        local_path=cluster_path,
        artifact_name=artifact_name,
        session_id=session_id or task_id or "",
    )
    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# R Workspace tool schemas
# ---------------------------------------------------------------------------

EXECUTE_R_CODE_SCHEMA = {
    "name": "execute_r_code",
    "description": (
        "Execute R code in the rocker/geospatial workspace container. "
        "Pre-installed packages: sf, terra, raster, dismo, vegan, ape, "
        "picante, phytools, rgbif, taxize, ENMeval, spocc, CoordinateCleaner, "
        "biomod2, rnaturalearth, geodata, sdm, tidyverse, ggplot2, and more. "
        "Use this for: species distribution modeling, GBIF data queries, "
        "biodiversity analysis, spatial analysis, phylogenetic analysis, "
        "statistical modeling, and generating plots. "
        "Code runs in /workspace/jobs/<job_id>/ — output files (plots, CSVs) "
        "are saved there and returned in the response."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "R code to execute. Use library() for packages.",
            },
            "timeout": {
                "type": "integer",
                "description": "Max execution time in seconds (default: 300).",
            },
            "job_id": {
                "type": "string",
                "description": "Optional job identifier for tracking.",
            },
        },
        "required": ["code"],
    },
}

LIST_R_PACKAGES_SCHEMA = {
    "name": "list_r_packages",
    "description": "List all R packages installed in the geospatial workspace.",
    "parameters": {"type": "object", "properties": {}},
}

R_WORKSPACE_STATUS_SCHEMA = {
    "name": "r_workspace_status",
    "description": "Check if the R geospatial workspace container is running and available.",
    "parameters": {"type": "object", "properties": {}},
}

RUN_NICHE_MODEL_SCHEMA = {
    "name": "run_niche_model",
    "description": (
        "Run the ellipsoidal niche modeling pipeline for a species. "
        "10-step algorithm: (1) Get GBIF occurrences, (2) filter unique, "
        "(3) remove outliers (IQR), (4) extract CHELSA bioclim, "
        "(5) deduplicate coords, (6) fit nicher ellipsoid (presence_only), "
        "(7) build M mask from ecoregions (>5% threshold), "
        "(8) crop bioclim with M mask, (9) project ellipse, "
        "(10) write suitability GeoTIFF. "
        "Uses nicher package with CHELSA bioclim and WWF ecoregions. "
        "Data sources: GBIF parquet (cluster) or GBIF API."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "species": {
                "type": "string",
                "description": "Scientific name (e.g., 'Panthera onca').",
            },
            "num_starts": {
                "type": "integer",
                "description": "Multi-start optimization restarts (default: 20).",
            },
            "iqr_factor": {
                "type": "number",
                "description": "IQR multiplier for outlier removal (default: 1.5).",
            },
            "ecoregion_pct": {
                "type": "number",
                "description": "Min fraction of points to keep ecoregion (default: 0.05).",
            },
            "bioclim_vars": {
                "type": "string",
                "description": "Comma-separated bioclim vars (default: bio01-bio19).",
            },
            "use_gbif_api": {
                "type": "boolean",
                "description": "Query GBIF API instead of local parquet (default: false).",
            },
        },
        "required": ["species"],
    },
}


# ---------------------------------------------------------------------------
# register(ctx) — Plugin system entry point
# ---------------------------------------------------------------------------

def register(ctx) -> None:
    """Register all EcoSeek DiDAL tools."""
    ctx.register_tool(
        name="hermes_status",
        toolset="ecoseek",
        schema=HERMES_STATUS_SCHEMA,
        handler=lambda args, **kw: hermes_status(task_id=kw.get("task_id")),
        check_fn=lambda: True,
    )

    ctx.register_tool(
        name="classify_prompt",
        toolset="ecoseek",
        schema=CLASSIFY_PROMPT_SCHEMA,
        handler=lambda args, **kw: classify_prompt_tool(
            prompt=args.get("prompt", ""),
            task_id=kw.get("task_id"),
        ),
        check_fn=lambda: True,
    )

    ctx.register_tool(
        name="didal_protocol",
        toolset="ecoseek",
        schema=DIDAL_PROTOCOL_SCHEMA,
        handler=lambda args, **kw: didal_protocol_tool(
            prompt=args.get("prompt", ""),
            mode=args.get("mode", ""),
            max_rounds=args.get("max_rounds", 0),
            task_id=kw.get("task_id"),
        ),
        check_fn=_is_configured,
    )

    ctx.register_tool(
        name="escalate_remote",
        toolset="ecoseek",
        schema=ESCALATE_REMOTE_SCHEMA,
        handler=lambda args, **kw: escalate_remote(
            task=args.get("task", ""),
            context=args.get("context", ""),
            urgency=args.get("urgency", "normal"),
            task_id=kw.get("task_id"),
        ),
        check_fn=_is_configured,
    )

    ctx.register_tool(
        name="dialectical_exchange",
        toolset="ecoseek",
        schema=DIALECTICAL_EXCHANGE_SCHEMA,
        handler=lambda args, **kw: dialectical_exchange(
            task=args.get("task", ""),
            plan=args.get("plan", ""),
            max_turns=args.get("max_turns", 0),
            task_id=kw.get("task_id"),
        ),
        check_fn=_is_configured,
    )

    ctx.register_tool(
        name="literature_search",
        toolset="ecoseek",
        schema=LITERATURE_SEARCH_SCHEMA,
        handler=lambda args, **kw: literature_search_tool(
            query=args.get("query", ""),
            limit=args.get("limit", 10),
            task_id=kw.get("task_id"),
        ),
        check_fn=lambda: True,
    )

    ctx.register_tool(
        name="web_search",
        toolset="ecoseek",
        schema=WEB_SEARCH_SCHEMA,
        handler=lambda args, **kw: web_search_tool(
            query=args.get("query", ""),
            search_type=args.get("search_type", "auto"),
            limit=args.get("limit", 5),
            task_id=kw.get("task_id"),
        ),
        check_fn=lambda: True,
    )

    ctx.register_tool(
        name="upload_document",
        toolset="ecoseek",
        schema=UPLOAD_DOCUMENT_SCHEMA,
        handler=lambda args, **kw: upload_document_tool(
            file_path=args.get("file_path", ""),
            text=args.get("text", ""),
            title=args.get("title", ""),
            authors=args.get("authors", ""),
            task_id=kw.get("task_id"),
        ),
        check_fn=lambda: True,
    )

    ctx.register_tool(
        name="ecoagent_query",
        toolset="ecoseek",
        schema=ECOAGENT_QUERY_SCHEMA,
        handler=lambda args, **kw: ecoagent_query_tool(
            action=args.get("action", ""),
            params=args.get("params"),
            task_id=kw.get("task_id"),
        ),
        check_fn=_is_configured,
    )

    # R Workspace tools (available when r-workspace container is running)
    from .r_executor import (
        execute_r_code, list_r_packages, r_workspace_status, run_niche_model,
    )

    ctx.register_tool(
        name="execute_r_code",
        toolset="ecoseek",
        schema=EXECUTE_R_CODE_SCHEMA,
        handler=lambda args, **kw: execute_r_code(
            code=args.get("code", ""),
            timeout=args.get("timeout"),
            job_id=args.get("job_id"),
            task_id=kw.get("task_id"),
        ),
        check_fn=lambda: True,
    )

    ctx.register_tool(
        name="list_r_packages",
        toolset="ecoseek",
        schema=LIST_R_PACKAGES_SCHEMA,
        handler=lambda args, **kw: list_r_packages(task_id=kw.get("task_id")),
        check_fn=lambda: True,
    )

    ctx.register_tool(
        name="r_workspace_status",
        toolset="ecoseek",
        schema=R_WORKSPACE_STATUS_SCHEMA,
        handler=lambda args, **kw: r_workspace_status(task_id=kw.get("task_id")),
        check_fn=lambda: True,
    )

    ctx.register_tool(
        name="run_niche_model",
        toolset="ecoseek",
        schema=RUN_NICHE_MODEL_SCHEMA,
        handler=lambda args, **kw: run_niche_model(
            species=args.get("species", ""),
            num_starts=args.get("num_starts", 20),
            iqr_factor=args.get("iqr_factor", 1.5),
            ecoregion_pct=args.get("ecoregion_pct", 0.05),
            bioclim_vars=args.get("bioclim_vars", "bio01,bio02,bio03,bio04,bio05,bio06,bio07,bio08,bio09,bio10,bio11,bio12,bio13,bio14,bio15,bio16,bio17,bio18,bio19"),
            use_gbif_api=args.get("use_gbif_api", False),
            task_id=kw.get("task_id"),
        ),
        check_fn=lambda: True,
    )

    ctx.register_tool(
        name="upload_artifact",
        toolset="ecoseek",
        schema=UPLOAD_ARTIFACT_SCHEMA,
        handler=lambda args, **kw: upload_artifact_tool(
            cluster_path=args.get("cluster_path", ""),
            artifact_name=args.get("artifact_name", ""),
            session_id=args.get("session_id", ""),
            task_id=kw.get("task_id"),
        ),
        check_fn=_is_configured,
    )

    # LACS tools — domain-specific literature classification
    ctx.register_tool(
        name="classify_literature",
        toolset="ecoseek",
        schema=CLASSIFY_LITERATURE_SCHEMA,
        handler=lambda args, **kw: classify_literature_tool(
            abstracts=args.get("abstracts", []),
            domain=args.get("domain", "host-parasite"),
            task_id=kw.get("task_id"),
        ),
        check_fn=lambda: True,
    )

    ctx.register_tool(
        name="train_lacs_model",
        toolset="ecoseek",
        schema=TRAIN_LACS_MODEL_SCHEMA,
        handler=lambda args, **kw: train_lacs_model_tool(
            domain=args.get("domain", ""),
            positive_papers=args.get("positive_papers", []),
            random_sample_size=args.get("random_sample_size", 5000),
            task_id=kw.get("task_id"),
        ),
        check_fn=_is_configured,
    )

    n = 15 if _is_configured() else 10
    logger.info(
        "ecoseek plugin registered: %d tools, remote=%s configured=%s didal=v2 ecoagent=true r_workspace=true niche=true pdf=true artifacts=true lacs=true",
        n, _REMOTE_URL, _is_configured(),
    )


# ---------------------------------------------------------------------------
# Legacy registration (when loaded as bundled tool, not user plugin)
# ---------------------------------------------------------------------------

try:
    from tools.registry import registry

    registry.register(
        name="hermes_status",
        toolset="ecoseek",
        schema=HERMES_STATUS_SCHEMA,
        handler=lambda args, **kw: hermes_status(task_id=kw.get("task_id")),
        check_fn=lambda: True,
        requires_env=[],
    )
    registry.register(
        name="classify_prompt",
        toolset="ecoseek",
        schema=CLASSIFY_PROMPT_SCHEMA,
        handler=lambda args, **kw: classify_prompt_tool(
            prompt=args.get("prompt", ""),
            task_id=kw.get("task_id"),
        ),
        check_fn=lambda: True,
        requires_env=[],
    )
    registry.register(
        name="didal_protocol",
        toolset="ecoseek",
        schema=DIDAL_PROTOCOL_SCHEMA,
        handler=lambda args, **kw: didal_protocol_tool(
            prompt=args.get("prompt", ""),
            mode=args.get("mode", ""),
            max_rounds=args.get("max_rounds", 0),
            task_id=kw.get("task_id"),
        ),
        check_fn=_is_configured,
        requires_env=[],
    )
    registry.register(
        name="escalate_remote",
        toolset="ecoseek",
        schema=ESCALATE_REMOTE_SCHEMA,
        handler=lambda args, **kw: escalate_remote(
            task=args.get("task", ""),
            context=args.get("context", ""),
            urgency=args.get("urgency", "normal"),
            task_id=kw.get("task_id"),
        ),
        check_fn=_is_configured,
        requires_env=[],
    )
    registry.register(
        name="dialectical_exchange",
        toolset="ecoseek",
        schema=DIALECTICAL_EXCHANGE_SCHEMA,
        handler=lambda args, **kw: dialectical_exchange(
            task=args.get("task", ""),
            plan=args.get("plan", ""),
            max_turns=args.get("max_turns", 0),
            task_id=kw.get("task_id"),
        ),
        check_fn=_is_configured,
        requires_env=[],
    )
    registry.register(
        name="literature_search",
        toolset="ecoseek",
        schema=LITERATURE_SEARCH_SCHEMA,
        handler=lambda args, **kw: literature_search_tool(
            query=args.get("query", ""),
            limit=args.get("limit", 10),
            task_id=kw.get("task_id"),
        ),
        check_fn=lambda: True,
        requires_env=[],
    )
    registry.register(
        name="web_search",
        toolset="ecoseek",
        schema=WEB_SEARCH_SCHEMA,
        handler=lambda args, **kw: web_search_tool(
            query=args.get("query", ""),
            search_type=args.get("search_type", "auto"),
            limit=args.get("limit", 5),
            task_id=kw.get("task_id"),
        ),
        check_fn=lambda: True,
        requires_env=[],
    )
    registry.register(
        name="upload_document",
        toolset="ecoseek",
        schema=UPLOAD_DOCUMENT_SCHEMA,
        handler=lambda args, **kw: upload_document_tool(
            file_path=args.get("file_path", ""),
            text=args.get("text", ""),
            title=args.get("title", ""),
            authors=args.get("authors", ""),
            task_id=kw.get("task_id"),
        ),
        check_fn=lambda: True,
        requires_env=[],
    )
    registry.register(
        name="ecoagent_query",
        toolset="ecoseek",
        schema=ECOAGENT_QUERY_SCHEMA,
        handler=lambda args, **kw: ecoagent_query_tool(
            action=args.get("action", ""),
            params=args.get("params"),
            task_id=kw.get("task_id"),
        ),
        check_fn=_is_configured,
        requires_env=[],
    )
    from .r_executor import execute_r_code, list_r_packages, r_workspace_status

    registry.register(
        name="execute_r_code",
        toolset="ecoseek",
        schema=EXECUTE_R_CODE_SCHEMA,
        handler=lambda args, **kw: execute_r_code(
            code=args.get("code", ""),
            timeout=args.get("timeout"),
            job_id=args.get("job_id"),
            task_id=kw.get("task_id"),
        ),
        check_fn=lambda: True,
        requires_env=[],
    )
    registry.register(
        name="list_r_packages",
        toolset="ecoseek",
        schema=LIST_R_PACKAGES_SCHEMA,
        handler=lambda args, **kw: list_r_packages(task_id=kw.get("task_id")),
        check_fn=lambda: True,
        requires_env=[],
    )
    registry.register(
        name="r_workspace_status",
        toolset="ecoseek",
        schema=R_WORKSPACE_STATUS_SCHEMA,
        handler=lambda args, **kw: r_workspace_status(task_id=kw.get("task_id")),
        check_fn=lambda: True,
        requires_env=[],
    )
    registry.register(
        name="upload_artifact",
        toolset="ecoseek",
        schema=UPLOAD_ARTIFACT_SCHEMA,
        handler=lambda args, **kw: upload_artifact_tool(
            cluster_path=args.get("cluster_path", ""),
            artifact_name=args.get("artifact_name", ""),
            session_id=args.get("session_id", ""),
            task_id=kw.get("task_id"),
        ),
        check_fn=_is_configured,
        requires_env=[],
    )
    registry.register(
        name="classify_literature",
        toolset="ecoseek",
        schema=CLASSIFY_LITERATURE_SCHEMA,
        handler=lambda args, **kw: classify_literature_tool(
            abstracts=args.get("abstracts", []),
            domain=args.get("domain", "host-parasite"),
            task_id=kw.get("task_id"),
        ),
        check_fn=lambda: True,
        requires_env=[],
    )
    registry.register(
        name="train_lacs_model",
        toolset="ecoseek",
        schema=TRAIN_LACS_MODEL_SCHEMA,
        handler=lambda args, **kw: train_lacs_model_tool(
            domain=args.get("domain", ""),
            positive_papers=args.get("positive_papers", []),
            random_sample_size=args.get("random_sample_size", 5000),
            task_id=kw.get("task_id"),
        ),
        check_fn=_is_configured,
        requires_env=[],
    )
except ImportError:
    pass
