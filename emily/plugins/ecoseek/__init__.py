"""ecoseek — Hermes plugin for EcoSeek DiDAL Protocol v2.

Provides tools for the dual-agent architecture (Alpha↔Beta):

  ``didal_protocol``         — full dialectical research loop with complexity-aware routing
  ``classify_prompt``        — classify prompt complexity (direct/didal/didal_literature)
  ``escalate_remote``        — one-shot delegation to Hermes Beta on reumanlab
  ``dialectical_exchange``   — legacy DiDAL structured debate
  ``hermes_status``          — check Hermes remote availability and loaded tools

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
import time
import urllib.error
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
_MODEL = os.environ.get("HERMES_REMOTE_MODEL", "hermes")
_TIMEOUT = int(os.environ.get("HERMES_REMOTE_TIMEOUT", "300"))
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
    """Send a request to hermes.ecoseek.org and return parsed JSON."""
    url = f"{_REMOTE_URL}{path}"
    data = json.dumps(payload).encode("utf-8") if payload else None
    headers = {"Accept": "application/json"}
    if _API_KEY:
        headers["Authorization"] = f"Bearer {_API_KEY}"
    if data:
        headers["Content-Type"] = "application/json"
        method = "POST"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout or _TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


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
    return json.dumps({
        "success": True,
        "mode": result.mode,
        "complexity_score": result.complexity_score,
        "reasons": result.reasons,
        "needs_clarification": result.needs_clarification,
        "expected_depth": result.expected_depth,
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool: didal_protocol — full dialectical research loop
# ---------------------------------------------------------------------------

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
    max_rounds : int, optional
        Max critique-revise rounds (default: DIDAL_MAX_CRITIQUE_ROUNDS env or 2).
    """
    from .protocol import run_didal_protocol
    return run_didal_protocol(
        prompt=prompt,
        force_mode=mode or None,
        max_rounds=max_rounds,
        task_id=task_id,
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
        "Classify a user prompt's scientific complexity to determine the best "
        "response mode. Returns one of: 'direct' (simple/factual), 'didal' "
        "(conceptual, needs dialectical loop), or 'didal_literature' (needs "
        "evidence-backed synthesis with references). Use this before deciding "
        "how to answer a question, or let didal_protocol handle it automatically."
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

    n = 5 if _is_configured() else 2
    logger.info(
        "ecoseek plugin registered: %d tools, remote=%s configured=%s didal=v2",
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
except ImportError:
    pass
