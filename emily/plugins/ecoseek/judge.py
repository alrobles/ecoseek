"""DiDAL Judge — score final answer quality and intermediate trajectory.

Criteria (from DiDAL Protocol spec):
  - Did the answer address the real scientific question?
  - Did it distinguish definition from interpretation?
  - Did it cite or ground major claims?
  - Did it contrast at least two relevant perspectives when needed?
  - Did it avoid superficiality?
  - Did it produce a scientist-like mini-report?

The judge produces both numeric scores and reasons.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_REMOTE_URL = os.environ.get(
    "HERMES_REMOTE_URL", "https://hermes.ecoseek.org"
).rstrip("/")
_API_KEY = os.environ.get("HERMES_ECOSEEK_API_KEY", "")
_MODEL = os.environ.get("HERMES_REMOTE_MODEL", "hermes")
_TIMEOUT = int(os.environ.get("DIDAL_JUDGE_TIMEOUT", "120"))
_JUDGE_ENABLED = os.environ.get("DIDAL_JUDGE_ENABLED", "true").lower() in (
    "1", "true", "yes",
)


# ---------------------------------------------------------------------------
# Judge system prompt
# ---------------------------------------------------------------------------

JUDGE_SYSTEM_PROMPT = """You are a scientific quality judge for the EcoSeek DiDAL protocol.

You evaluate the quality of ecological/scientific answers produced by the DiDAL system.
Score each criterion from 0.0 to 1.0 and provide brief reasons.

## Criteria

1. **scientific_accuracy** (0-1): Does the answer address the real scientific question correctly?
2. **definition_clarity** (0-1): Does it distinguish definition from interpretation clearly?
3. **evidence_grounding** (0-1): Does it cite or ground major claims with evidence/references?
4. **perspective_contrast** (0-1): Does it contrast relevant perspectives when the question requires it?
5. **depth** (0-1): Does it avoid superficiality? Is it substantive enough for a scientist?
6. **report_structure** (0-1): Does it follow a scientist-like mini-report structure?

## Output Format

Return ONLY valid JSON:
{
  "scores": {
    "scientific_accuracy": 0.0,
    "definition_clarity": 0.0,
    "evidence_grounding": 0.0,
    "perspective_contrast": 0.0,
    "depth": 0.0,
    "report_structure": 0.0
  },
  "overall_score": 0.0,
  "reasons": [
    "Brief reason for the most notable score",
    "Brief reason for a weakness"
  ],
  "verdict": "excellent|good|adequate|needs_improvement|poor"
}

The overall_score should be a weighted average:
  overall = 0.25*accuracy + 0.20*evidence + 0.15*depth + 0.15*structure + 0.15*definition + 0.10*contrast

Be rigorous. A scientist reading this answer should find it useful."""


# ---------------------------------------------------------------------------
# Judge function
# ---------------------------------------------------------------------------

def judge_answer(
    prompt: str,
    answer: str,
    mode: str = "didal",
    evidence: Optional[dict] = None,
    classification: Optional[dict] = None,
) -> dict:
    """Score a DiDAL protocol answer.

    Parameters
    ----------
    prompt : str
        The original user question.
    answer : str
        The final answer/report content.
    mode : str
        Protocol mode that was used (direct/didal/didal_literature).
    evidence : dict, optional
        Evidence/sources used in the answer.
    classification : dict, optional
        Classifier result for context.

    Returns
    -------
    dict
        Judge result with scores, overall_score, reasons, and verdict.
    """
    if not _JUDGE_ENABLED or not _API_KEY:
        return _fallback_judge(answer, mode, evidence)

    # Build judge prompt
    judge_input = f"""## Question
{prompt}

## Mode Used
{mode}

## Answer to Judge
{answer[:4000]}
"""

    if evidence and isinstance(evidence, dict):
        sources = evidence.get("sources", [])
        if sources:
            judge_input += f"\n## Sources Provided ({len(sources)} total)\n"
            for s in sources[:5]:
                title = s.get("title", "Unknown")
                judge_input += f"- {title}\n"

    if classification:
        judge_input += f"\n## Classification\nComplexity: {classification.get('complexity_score', 'N/A')}\n"
        judge_input += f"Reasons: {', '.join(classification.get('reasons', []))}\n"

    try:
        req_body = json.dumps({
            "model": _MODEL,
            "messages": [
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": judge_input},
            ],
            "temperature": 0.1,
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{_REMOTE_URL}/v1/chat/completions",
            data=req_body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {_API_KEY}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

        # Parse JSON from response
        result = _parse_judge_json(content)
        if result:
            logger.info(
                "judge: overall=%.2f verdict=%s",
                result.get("overall_score", 0),
                result.get("verdict", "unknown"),
            )
            return result

        logger.warning("Judge returned unparseable response, using fallback")
        return _fallback_judge(answer, mode, evidence)

    except Exception as exc:
        logger.warning("Judge call failed: %s, using fallback", exc)
        return _fallback_judge(answer, mode, evidence)


def _parse_judge_json(content: str) -> Optional[dict]:
    """Extract JSON from judge response (may be wrapped in ```json blocks)."""
    content = content.strip()

    # Try direct parse
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Try extracting from ```json block
    if "```json" in content:
        start = content.index("```json") + 7
        end = content.index("```", start)
        try:
            return json.loads(content[start:end].strip())
        except (json.JSONDecodeError, ValueError):
            pass

    # Try extracting first { ... }
    brace_start = content.find("{")
    brace_end = content.rfind("}")
    if brace_start >= 0 and brace_end > brace_start:
        try:
            return json.loads(content[brace_start:brace_end + 1])
        except json.JSONDecodeError:
            pass

    return None


def _fallback_judge(
    answer: str,
    mode: str,
    evidence: Optional[dict] = None,
) -> dict:
    """Heuristic-based judge when LLM judge is unavailable.

    Uses simple text analysis to estimate quality scores.
    """
    answer_len = len(answer)
    has_headers = answer.count("#") >= 2
    has_evidence = bool(evidence and isinstance(evidence, dict) and evidence.get("sources"))
    n_sources = len(evidence.get("sources", [])) if has_evidence else 0
    has_lists = "- " in answer or "1." in answer
    has_refs = any(w in answer.lower() for w in ["reference", "citation", "doi", "http", "et al"])

    # Heuristic scores
    depth = min(1.0, answer_len / 3000)  # longer = deeper (up to 3k chars)
    structure = 0.3
    if has_headers:
        structure += 0.3
    if has_lists:
        structure += 0.2
    if answer_len > 500:
        structure += 0.2

    evidence_score = 0.2
    if has_evidence:
        evidence_score = min(1.0, 0.3 + n_sources * 0.15)
    if has_refs:
        evidence_score = min(1.0, evidence_score + 0.2)

    accuracy = 0.5 if mode == "direct" else 0.65
    if mode == "didal_literature":
        accuracy = 0.7

    definition = 0.5 if answer_len > 200 else 0.3
    contrast = 0.3
    if any(w in answer.lower() for w in ["however", "in contrast", "alternatively", "debate"]):
        contrast += 0.3

    overall = (
        0.25 * accuracy
        + 0.20 * evidence_score
        + 0.15 * depth
        + 0.15 * structure
        + 0.15 * definition
        + 0.10 * contrast
    )

    if overall >= 0.75:
        verdict = "good"
    elif overall >= 0.55:
        verdict = "adequate"
    elif overall >= 0.35:
        verdict = "needs_improvement"
    else:
        verdict = "poor"

    return {
        "scores": {
            "scientific_accuracy": round(accuracy, 2),
            "definition_clarity": round(definition, 2),
            "evidence_grounding": round(evidence_score, 2),
            "perspective_contrast": round(contrast, 2),
            "depth": round(depth, 2),
            "report_structure": round(structure, 2),
        },
        "overall_score": round(overall, 3),
        "reasons": [
            f"Heuristic judge (LLM unavailable): mode={mode}, length={answer_len}",
        ],
        "verdict": verdict,
        "judge_type": "heuristic",
    }
