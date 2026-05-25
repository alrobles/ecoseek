"""DiDAL Protocol Orchestrator — structured dialectical research loop.

Implements the full DiDAL pipeline:
  classify → frame_task → retrieve → expert_draft → critique → revise → report

The orchestrator sends each stage to Hermes Beta (hermes.ecoseek.org) with
stage-specific system prompts, then assembles the final mini-report.
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

from .classifier import ClassificationResult, classify_complexity
from .prompts import (
    BETA_EXPERT_SYSTEM,
    BETA_NAIVE_SYSTEM,
    DIRECT_MODE_PROMPT,
    EXPERT_DRAFT_PROMPT,
    FRAME_TASK_PROMPT,
    MINI_REPORT_TEMPLATE,
    NAIVE_CRITIQUE_PROMPT,
    RETRIEVE_EVIDENCE_PROMPT,
    REVISION_PROMPT,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_REMOTE_URL = os.environ.get(
    "HERMES_REMOTE_URL", "https://hermes.ecoseek.org"
).rstrip("/")
_API_KEY = os.environ.get("HERMES_ECOSEEK_API_KEY", "")
_MODEL = os.environ.get("HERMES_REMOTE_MODEL", "hermes")
_TIMEOUT = int(os.environ.get("HERMES_REMOTE_TIMEOUT", "300"))
_DIDAL_ENABLED = os.environ.get("DIDAL_ENABLED", "true").lower() in ("true", "1", "yes")
_MAX_CRITIQUE_ROUNDS = int(os.environ.get("DIDAL_MAX_CRITIQUE_ROUNDS", "2"))


def _is_configured() -> bool:
    return bool(_REMOTE_URL and _API_KEY)


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _beta_call(
    system_prompt: str,
    user_content: str,
    context_messages: list[dict] | None = None,
    timeout: int | None = None,
) -> dict:
    """Send a chat completion to Hermes Beta with a specific system prompt."""
    messages = [{"role": "system", "content": system_prompt}]
    if context_messages:
        messages.extend(context_messages)
    messages.append({"role": "user", "content": user_content})

    url = f"{_REMOTE_URL}/v1/chat/completions"
    payload = json.dumps({"model": _MODEL, "messages": messages}).encode("utf-8")
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if _API_KEY:
        headers["Authorization"] = f"Bearer {_API_KEY}"

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout or _TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    usage = data.get("usage", {})
    return {"content": content, "usage": usage, "model": data.get("model", _MODEL)}


def _parse_json_response(content: str) -> dict | None:
    """Try to parse JSON from Beta's response, handling markdown wrapping."""
    content = content.strip()
    # Strip markdown code fences
    if content.startswith("```"):
        lines = content.split("\n")
        # Remove first and last line if they're fences
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines)
    try:
        return json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Stage implementations
# ---------------------------------------------------------------------------

def _stage_classify(prompt: str) -> dict:
    """Stage 0: Run the complexity classifier."""
    result = classify_complexity(prompt)
    return {
        "stage": "classify",
        "classification": {
            "mode": result.mode,
            "complexity_score": result.complexity_score,
            "reasons": result.reasons,
            "needs_clarification": result.needs_clarification,
            "expected_depth": result.expected_depth,
        },
    }


def _stage_frame_task(prompt: str, classification: dict) -> dict:
    """Stage 1: Frame the question into a structured task object."""
    context = (
        f"User's question: {prompt}\n\n"
        f"Classification: mode={classification['mode']}, "
        f"depth={classification['expected_depth']}, "
        f"score={classification['complexity_score']}"
    )
    try:
        result = _beta_call(FRAME_TASK_PROMPT, context)
        task_obj = _parse_json_response(result["content"])
        return {
            "stage": "frame_task",
            "task_object": task_obj or {"raw_response": result["content"]},
            "usage": result["usage"],
        }
    except Exception as exc:
        logger.warning("frame_task failed: %s", exc)
        return {
            "stage": "frame_task",
            "task_object": {
                "user_question": prompt,
                "task_type": "ecological_question",
                "scope": "ecology",
                "subquestions": [prompt],
                "required_output": "mini_report",
            },
            "error": str(exc)[:200],
        }


def _stage_retrieve(task_object: dict, classification: dict) -> dict:
    """Stage 2: Retrieve evidence using real literature APIs + Beta synthesis.

    Uses multi-source retrieval (OpenAlex, Semantic Scholar, GBIF Literature,
    Entrez/PubMed) to find real papers, then asks Beta to map sources to
    subquestions and assess relevance.
    """
    from .retrieval import retrieve_literature

    # Determine retrieval tier from classification
    tier = "B" if classification.get("mode") == "didal_literature" else "A"
    subquestions = task_object.get("subquestions", [])
    query = task_object.get("user_question", "")

    # Step 1: Retrieve real literature from APIs
    try:
        lit_results = retrieve_literature(
            query=query,
            subquestions=subquestions,
            tier=tier,
            max_per_source=4 if tier == "B" else 2,
        )
    except Exception as exc:
        logger.warning("literature retrieval failed: %s", exc)
        lit_results = {"sources": [], "retrieval_notes": f"API retrieval failed: {exc}"}

    # Step 2: Ask Beta to analyze and map retrieved sources to subquestions
    if lit_results.get("sources"):
        context = (
            f"Structured task:\n{json.dumps(task_object, indent=2, ensure_ascii=False)}\n\n"
            f"Retrieved sources from literature APIs:\n"
            f"{json.dumps(lit_results['sources'][:10], indent=2, ensure_ascii=False)}\n\n"
            f"Map each source to the relevant subquestion(s) it helps answer. "
            f"Assess which sources are most relevant and trustworthy. "
            f"Identify any gaps where no good source was found."
        )
        try:
            result = _beta_call(
                f"{BETA_EXPERT_SYSTEM}\n\n{RETRIEVE_EVIDENCE_PROMPT}",
                context,
                timeout=120,
            )
            beta_analysis = _parse_json_response(result["content"])
            usage = result["usage"]
        except Exception as exc:
            logger.warning("Beta evidence analysis failed: %s", exc)
            beta_analysis = None
            usage = {}

        # Merge API results with Beta's analysis
        evidence = {
            "sources": lit_results["sources"],
            "total_found": lit_results["total_found"],
            "provider_stats": lit_results.get("provider_stats", {}),
            "tier": tier,
            "retrieval_notes": lit_results.get("retrieval_notes", ""),
            "beta_analysis": beta_analysis,
        }
        return {
            "stage": "retrieve_evidence",
            "evidence": evidence,
            "usage": usage,
        }
    else:
        # Fallback: ask Beta to identify sources from its knowledge
        context = f"Structured task:\n{json.dumps(task_object, indent=2, ensure_ascii=False)}"
        try:
            result = _beta_call(
                f"{BETA_EXPERT_SYSTEM}\n\n{RETRIEVE_EVIDENCE_PROMPT}",
                context,
                timeout=120,
            )
            evidence = _parse_json_response(result["content"])
            return {
                "stage": "retrieve_evidence",
                "evidence": evidence or {"raw_response": result["content"]},
                "usage": result["usage"],
                "api_retrieval_failed": True,
            }
        except Exception as exc:
            logger.warning("retrieve_evidence fallback failed: %s", exc)
            return {
                "stage": "retrieve_evidence",
                "evidence": {"sources": [], "retrieval_notes": f"All retrieval failed: {exc}"},
                "error": str(exc)[:200],
            }


def _stage_expert_draft(task_object: dict, evidence: dict | None) -> dict:
    """Stage 3: Expert produces first scientific synthesis."""
    context_parts = [f"Structured task:\n{json.dumps(task_object, indent=2, ensure_ascii=False)}"]
    if evidence and evidence.get("sources"):
        context_parts.append(f"\nRetrieved evidence:\n{json.dumps(evidence, indent=2, ensure_ascii=False)}")

    try:
        result = _beta_call(
            f"{BETA_EXPERT_SYSTEM}\n\n{EXPERT_DRAFT_PROMPT}",
            "\n".join(context_parts),
        )
        draft = _parse_json_response(result["content"])
        return {
            "stage": "expert_draft",
            "draft": draft or {"raw_response": result["content"]},
            "usage": result["usage"],
        }
    except Exception as exc:
        logger.warning("expert_draft failed: %s", exc)
        return {
            "stage": "expert_draft",
            "draft": {"thesis": "Draft generation failed", "raw_error": str(exc)[:200]},
            "error": str(exc)[:200],
        }


def _stage_critique(draft: dict, task_object: dict) -> dict:
    """Stage 4: Naive interlocutor critiques the draft."""
    context = (
        f"Original task:\n{json.dumps(task_object, indent=2, ensure_ascii=False)}\n\n"
        f"Expert draft:\n{json.dumps(draft, indent=2, ensure_ascii=False)}"
    )
    try:
        result = _beta_call(
            f"{BETA_NAIVE_SYSTEM}\n\n{NAIVE_CRITIQUE_PROMPT}",
            context,
        )
        critique = _parse_json_response(result["content"])
        return {
            "stage": "naive_critique",
            "critique": critique or {"raw_response": result["content"]},
            "usage": result["usage"],
        }
    except Exception as exc:
        logger.warning("naive_critique failed: %s", exc)
        return {
            "stage": "naive_critique",
            "critique": {
                "overall_quality": "unknown",
                "issues": [],
                "requires_revision": False,
            },
            "error": str(exc)[:200],
        }


def _stage_revise(draft: dict, critique: dict, task_object: dict) -> dict:
    """Stage 5: Expert revises based on critique."""
    context = (
        f"Original task:\n{json.dumps(task_object, indent=2, ensure_ascii=False)}\n\n"
        f"Your previous draft:\n{json.dumps(draft, indent=2, ensure_ascii=False)}\n\n"
        f"Critique received:\n{json.dumps(critique, indent=2, ensure_ascii=False)}"
    )
    try:
        result = _beta_call(
            f"{BETA_EXPERT_SYSTEM}\n\n{REVISION_PROMPT}",
            context,
        )
        revised = _parse_json_response(result["content"])
        return {
            "stage": "revision",
            "revised_draft": revised or {"raw_response": result["content"]},
            "usage": result["usage"],
        }
    except Exception as exc:
        logger.warning("revision failed: %s", exc)
        return {
            "stage": "revision",
            "revised_draft": draft,  # fallback to original
            "error": str(exc)[:200],
        }


def _stage_direct(prompt: str) -> dict:
    """Direct mode: simple one-shot answer without dialectical loop."""
    try:
        result = _beta_call(DIRECT_MODE_PROMPT, prompt)
        return {
            "stage": "direct_answer",
            "content": result["content"],
            "usage": result["usage"],
            "model": result["model"],
        }
    except Exception as exc:
        logger.warning("direct_answer failed: %s", exc)
        return {
            "stage": "direct_answer",
            "content": f"Error getting response: {exc}",
            "error": str(exc)[:200],
        }


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

def _assemble_report(
    prompt: str,
    classification: dict,
    task_object: dict,
    draft: dict,
    evidence: dict | None,
    rounds: int,
) -> str:
    """Assemble the final mini-report from structured draft data."""
    sections = draft.get("sections", {})

    # If draft is raw text (parsing failed), return it directly
    if "raw_response" in draft:
        return draft["raw_response"]

    title = task_object.get("task_type", "Ecological Analysis").replace("_", " ").title()
    question = task_object.get("user_question", prompt)

    try:
        report = MINI_REPORT_TEMPLATE.format(
            title=title,
            question_and_scope=f"**Question:** {question}\n**Scope:** {task_object.get('scope', 'ecology')}",
            short_answer=draft.get("thesis", "See synthesis below."),
            definition=sections.get("definition", "*Not applicable for this question type.*"),
            historical_development=sections.get("historical_development", "*Not covered in this analysis.*"),
            key_distinctions=sections.get("key_distinctions", "*Not applicable.*"),
            evidence_and_references=sections.get("evidence_and_references", "*No specific references retrieved.*"),
            competing_views=sections.get("competing_views", "*No competing views identified.*"),
            synthesis=sections.get("synthesis", draft.get("thesis", "")),
            open_questions="\n".join(
                f"- {q}" for q in draft.get("missing_information", draft.get("uncertainties", []))
            ) or "*None identified.*",
            complexity_score=classification.get("complexity_score", "?"),
            mode=classification.get("mode", "?"),
            rounds=rounds,
        )
    except (KeyError, TypeError):
        # Fallback: render whatever we have
        report = f"# Analysis: {question}\n\n"
        if draft.get("thesis"):
            report += f"## Thesis\n{draft['thesis']}\n\n"
        for key, val in sections.items():
            report += f"## {key.replace('_', ' ').title()}\n{val}\n\n"
        if draft.get("key_points"):
            report += "## Key Points\n" + "\n".join(f"- {p}" for p in draft["key_points"]) + "\n\n"
        if draft.get("uncertainties"):
            report += "## Uncertainties\n" + "\n".join(f"- {u}" for u in draft["uncertainties"]) + "\n"

    return report


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def run_didal_protocol(
    prompt: str,
    force_mode: str | None = None,
    max_rounds: int = 0,
    task_id: str | None = None,
) -> str:
    """Run the full DiDAL protocol on a user prompt.

    Parameters
    ----------
    prompt : str
        The user's question.
    force_mode : str, optional
        Override the classifier: "direct", "didal", or "didal_literature".
    max_rounds : int, optional
        Override max critique rounds (default: DIDAL_MAX_CRITIQUE_ROUNDS env).
    task_id : str, optional
        Session/task identifier for tracing.

    Returns
    -------
    str
        JSON string with protocol results.
    """
    if not _is_configured():
        return json.dumps({
            "success": False,
            "error": "hermes_not_configured",
            "message": "DiDAL protocol requires HERMES_ECOSEEK_API_KEY.",
        })

    if not _DIDAL_ENABLED and force_mode != "direct":
        # Feature flag off — fallback to direct
        force_mode = "direct"

    protocol_id = task_id or str(uuid.uuid4())[:12]
    effective_max_rounds = max_rounds if max_rounds > 0 else _MAX_CRITIQUE_ROUNDS
    stages: list[dict] = []
    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    start_time = time.time()

    def _track_usage(stage_data: dict):
        usage = stage_data.get("usage", {})
        for k in total_usage:
            total_usage[k] += usage.get(k, 0)

    # --- Stage 0: Classify ---
    classify_result = _stage_classify(prompt)
    stages.append(classify_result)
    classification = classify_result["classification"]

    # Override mode if forced
    mode = force_mode or classification["mode"]
    classification["mode"] = mode  # update for report

    logger.info(
        "didal[%s] classified: mode=%s score=%.2f reasons=%s",
        protocol_id, mode, classification["complexity_score"],
        classification["reasons"][:2],
    )

    # --- Direct mode: skip dialectical loop ---
    if mode == "direct":
        direct_result = _stage_direct(prompt)
        stages.append(direct_result)
        _track_usage(direct_result)

        elapsed = round(time.time() - start_time, 1)
        return json.dumps({
            "success": True,
            "protocol_id": protocol_id,
            "mode": "direct",
            "classification": classification,
            "content": direct_result["content"],
            "stages": stages,
            "total_usage": total_usage,
            "elapsed_seconds": elapsed,
            "source": "hermes.ecoseek.org",
        }, ensure_ascii=False)

    # --- DiDAL mode: full dialectical loop ---

    # Stage 1: Frame task
    frame_result = _stage_frame_task(prompt, classification)
    stages.append(frame_result)
    _track_usage(frame_result)
    task_object = frame_result["task_object"]

    # Stage 2: Retrieve evidence (only for didal_literature)
    evidence = None
    if mode == "didal_literature":
        retrieve_result = _stage_retrieve(task_object, classification)
        stages.append(retrieve_result)
        _track_usage(retrieve_result)
        evidence = retrieve_result["evidence"]

    # Stage 3: Expert draft
    draft_result = _stage_expert_draft(task_object, evidence)
    stages.append(draft_result)
    _track_usage(draft_result)
    current_draft = draft_result["draft"]

    # Stage 4-5: Critique-Revise loop (bounded)
    rounds = 0
    for round_idx in range(effective_max_rounds):
        # Stage 4: Naive critique
        critique_result = _stage_critique(current_draft, task_object)
        stages.append(critique_result)
        _track_usage(critique_result)
        critique = critique_result["critique"]

        rounds = round_idx + 1

        # Check if revision needed
        requires_revision = critique.get("requires_revision", False)
        overall_quality = critique.get("overall_quality", "adequate")

        if not requires_revision or overall_quality in ("good", "excellent"):
            logger.info("didal[%s] critique round %d: quality=%s, no revision needed",
                       protocol_id, rounds, overall_quality)
            break

        # Stage 5: Revision
        revision_result = _stage_revise(current_draft, critique, task_object)
        stages.append(revision_result)
        _track_usage(revision_result)
        current_draft = revision_result["revised_draft"]

        logger.info("didal[%s] revision round %d complete", protocol_id, rounds)

    # Stage 6: Assemble final report
    report = _assemble_report(
        prompt, classification, task_object, current_draft, evidence, rounds,
    )

    elapsed = round(time.time() - start_time, 1)

    return json.dumps({
        "success": True,
        "protocol_id": protocol_id,
        "mode": mode,
        "classification": classification,
        "content": report,
        "task_object": task_object,
        "final_draft": current_draft,
        "evidence": evidence,
        "critique_rounds": rounds,
        "stages": stages,
        "total_usage": total_usage,
        "elapsed_seconds": elapsed,
        "source": "hermes.ecoseek.org",
    }, ensure_ascii=False)
