"""DiDAL Protocol Orchestrator — structured dialectical research loop.

Implements the full DiDAL pipeline:
  classify → frame_task → retrieve → expert_draft → critique → revise → report

The orchestrator sends each stage to Hermes Beta (hermes.ecoseek.org) with
stage-specific system prompts, then assembles the final mini-report.

Progress logging: each stage emits a logger.info message with a stage tag
so that gateway/CLI consumers can show real-time progress.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
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
from .judge import judge_answer
from .memory import (
    extract_memories_from_protocol,
    is_memory_enabled,
    memory_read_stage,
    memory_write_stage,
    recall,
    record_policy_signal,
    should_write,
)
from .tracing import (
    record_llm_call,
    trace_protocol,
    trace_retrieval_source,
    trace_stage,
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


def _emit_progress(stage: str, detail: str = "") -> None:
    """Emit a progress message for the current protocol stage.

    These messages are logged at INFO level and also printed to stdout
    so that gateway consumers (TUI, API server) can surface them to the
    user during long-running tool calls.
    """
    msg = f"[DiDAL] {stage}"
    if detail:
        msg += f" — {detail}"
    logger.info(msg)
    # Print to stdout for gateway tool-progress display
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _beta_call(
    system_prompt: str,
    user_content: str,
    context_messages: list[dict] | None = None,
    timeout: int | None = None,
) -> dict:
    """Send a chat completion to Hermes Beta with a specific system prompt.

    Uses the Cloudflare-safe HTTP client that falls back to curl when
    Python's urllib is blocked by Cloudflare Bot Fight Mode (error 1010).
    """
    from .http_client import http_post_json

    messages = [{"role": "system", "content": system_prompt}]
    if context_messages:
        messages.extend(context_messages)
    messages.append({"role": "user", "content": user_content})

    url = f"{_REMOTE_URL}/v1/chat/completions"
    headers = {}
    if _API_KEY:
        headers["Authorization"] = f"Bearer {_API_KEY}"

    data = http_post_json(
        url,
        payload={"model": _MODEL, "messages": messages},
        headers=headers,
        timeout=timeout or _TIMEOUT,
    )

    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    usage = data.get("usage", {})
    model = data.get("model", _MODEL)
    record_llm_call({}, model, usage, stage="beta_call")
    return {"content": content, "usage": usage, "model": model}


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
    with trace_protocol(protocol_id, prompt, force_mode or "auto") as tctx:

        _emit_progress("Classifying", "analyzing question complexity")
        with trace_stage("classification", tctx, agent_role="system") as sctx:
            classify_result = _stage_classify(prompt)
            stages.append(classify_result)
            classification = classify_result["classification"]
            sctx["confidence"] = classification["complexity_score"]

        # Override mode if forced
        mode = force_mode or classification["mode"]
        classification["mode"] = mode  # update for report
        tctx["mode"] = mode

        _emit_progress(
            "Classified",
            f"mode={mode}, score={classification['complexity_score']:.2f}",
        )
        logger.info(
            "didal[%s] classified: mode=%s score=%.2f reasons=%s",
            protocol_id, mode, classification["complexity_score"],
            classification["reasons"][:2],
        )

        # --- Direct mode: skip dialectical loop ---
        if mode == "direct":
            _emit_progress("Direct", "fast answer mode")
            with trace_stage("direct_answer", tctx, agent_role="backend_expert") as sctx:
                direct_result = _stage_direct(prompt)
                stages.append(direct_result)
                _track_usage(direct_result)
                sctx["tokens_used"] = direct_result.get("usage", {}).get("total_tokens", 0)

            elapsed = round(time.time() - start_time, 1)
            result = {
                "success": True,
                "protocol_id": protocol_id,
                "mode": "direct",
                "classification": classification,
                "content": direct_result["content"],
                "stages": stages,
                "total_usage": total_usage,
                "elapsed_seconds": elapsed,
                "source": "hermes.ecoseek.org",
            }
            if tctx.get("trace_id"):
                result["trace_id"] = tctx["trace_id"]
            return json.dumps(result, ensure_ascii=False)

        # --- DiDAL mode: full dialectical loop ---

        # Memory read: recall relevant context before framing
        memory_context = []
        if is_memory_enabled():
            _emit_progress("Memory", "recalling relevant context")
            with trace_stage("memory.read", tctx, agent_role="system") as sctx:
                with memory_read_stage(prompt, classification) as mctx:
                    memory_context = mctx.get("memories", [])
                    sctx["recall_count"] = mctx.get("recall_count", 0)
                    stages.append({
                        "stage": "memory.read",
                        "recall_count": mctx.get("recall_count", 0),
                    })

        # Stage 1: Frame task
        _emit_progress("Framing", "structuring the research question")
        with trace_stage("frontend.frame_task", tctx, agent_role="frontend_naive") as sctx:
            frame_result = _stage_frame_task(prompt, classification)
            stages.append(frame_result)
            _track_usage(frame_result)
            task_object = frame_result["task_object"]
            sctx["tokens_used"] = frame_result.get("usage", {}).get("total_tokens", 0)

        # Stage 2: Retrieve evidence (only for didal_literature)
        evidence = None
        if mode == "didal_literature":
            _emit_progress("Retrieving", "searching literature databases")
            with trace_stage("backend.retrieve", tctx, agent_role="backend_expert",
                             question_type=task_object.get("task_type", "unknown")) as sctx:
                retrieve_result = _stage_retrieve(task_object, classification)
                stages.append(retrieve_result)
                _track_usage(retrieve_result)
                evidence = retrieve_result["evidence"]
                n_sources = len(evidence.get("sources", [])) if isinstance(evidence, dict) else 0
                sctx["retrieved_sources"] = n_sources
                tctx["total_sources"] = n_sources
                _emit_progress("Retrieved", f"{n_sources} sources found")

        # Stage 3: Expert draft
        _emit_progress("Drafting", "writing expert synthesis")
        with trace_stage("backend.synthesize_draft", tctx, agent_role="backend_expert") as sctx:
            draft_result = _stage_expert_draft(task_object, evidence)
            stages.append(draft_result)
            _track_usage(draft_result)
            current_draft = draft_result["draft"]
            sctx["tokens_used"] = draft_result.get("usage", {}).get("total_tokens", 0)
            sctx["evidence_used"] = len(current_draft.get("evidence", [])) if isinstance(current_draft, dict) else 0

        # Stage 4-5: Critique-Revise loop (bounded)
        rounds = 0
        for round_idx in range(effective_max_rounds):
            # Stage 4: Naive critique
            _emit_progress("Critiquing", f"peer review round {round_idx + 1}")
            with trace_stage("frontend.critique", tctx, agent_role="frontend_naive",
                             round_index=round_idx + 1) as sctx:
                critique_result = _stage_critique(current_draft, task_object)
                stages.append(critique_result)
                _track_usage(critique_result)
                critique = critique_result["critique"]

                rounds = round_idx + 1
                sctx["quality"] = critique.get("overall_quality", "unknown")
                sctx["requires_revision"] = critique.get("requires_revision", False)

            # Check if revision needed
            requires_revision = critique.get("requires_revision", False)
            overall_quality = critique.get("overall_quality", "adequate")

            if not requires_revision or overall_quality in ("good", "excellent"):
                logger.info("didal[%s] critique round %d: quality=%s, no revision needed",
                           protocol_id, rounds, overall_quality)
                break

            # Stage 5: Revision
            _emit_progress("Revising", f"improving draft (round {round_idx + 1})")
            with trace_stage("backend.revise", tctx, agent_role="backend_expert",
                             round_index=round_idx + 1) as sctx:
                revision_result = _stage_revise(current_draft, critique, task_object)
                stages.append(revision_result)
                _track_usage(revision_result)
                current_draft = revision_result["revised_draft"]
                sctx["tokens_used"] = revision_result.get("usage", {}).get("total_tokens", 0)

            logger.info("didal[%s] revision round %d complete", protocol_id, rounds)

        tctx["critique_rounds"] = rounds

        # Stage 6: Assemble final report
        _emit_progress("Finalizing", "assembling mini-report")
        with trace_stage("finalize_report", tctx, agent_role="system") as sctx:
            report = _assemble_report(
                prompt, classification, task_object, current_draft, evidence, rounds,
            )

        # Stage 7: Judge — score the final answer
        _emit_progress("Judging", "scoring answer quality")
        judge_result = {"overall_score": 0.0, "verdict": "unknown"}
        with trace_stage("judge.score", tctx, agent_role="judge") as sctx:
            try:
                judge_result = judge_answer(
                    prompt=prompt,
                    answer=report,
                    mode=mode,
                    evidence=evidence,
                    classification=classification,
                )
                sctx["overall_score"] = judge_result.get("overall_score", 0)
                sctx["verdict"] = judge_result.get("verdict", "unknown")
                stages.append({
                    "stage": "judge.score",
                    "overall_score": judge_result.get("overall_score", 0),
                    "verdict": judge_result.get("verdict", "unknown"),
                    "scores": judge_result.get("scores", {}),
                    "reasons": judge_result.get("reasons", []),
                })
            except Exception as exc:
                logger.warning("Judge scoring failed: %s", exc)
                sctx["error"] = str(exc)[:200]

        # Stage 8: Memory write — persist useful knowledge
        if is_memory_enabled():
            _emit_progress("Saving", "persisting to memory")
            with trace_stage("memory.write", tctx, agent_role="system") as sctx:
                elapsed_so_far = round(time.time() - start_time, 1)
                write_result = {
                    "success": True,
                    "protocol_id": protocol_id,
                    "mode": mode,
                    "classification": classification,
                    "content": report,
                    "task_object": task_object,
                    "final_draft": current_draft,
                    "evidence": evidence,
                    "critique_rounds": rounds,
                    "elapsed_seconds": elapsed_so_far,
                    "trace_id": tctx.get("trace_id", ""),
                }
                with memory_write_stage(
                    write_result,
                    judge_score=judge_result.get("overall_score", 0),
                ) as mctx:
                    sctx["written"] = mctx.get("written", 0)
                    sctx["fitness"] = mctx.get("fitness")
                    stages.append({
                        "stage": "memory.write",
                        "written": mctx.get("written", 0),
                        "fitness": mctx.get("fitness"),
                    })

        elapsed = round(time.time() - start_time, 1)
        _emit_progress("Complete", f"finished in {elapsed}s")

        result = {
            "success": True,
            "protocol_id": protocol_id,
            "mode": mode,
            "classification": classification,
            "content": report,
            "task_object": task_object,
            "final_draft": current_draft,
            "evidence": evidence,
            "critique_rounds": rounds,
            "judge": {
                "overall_score": judge_result.get("overall_score", 0),
                "verdict": judge_result.get("verdict", "unknown"),
                "scores": judge_result.get("scores", {}),
            },
            "stages": stages,
            "total_usage": total_usage,
            "elapsed_seconds": elapsed,
            "source": "hermes.ecoseek.org",
        }
        if tctx.get("trace_id"):
            result["trace_id"] = tctx["trace_id"]
        return json.dumps(result, ensure_ascii=False)
