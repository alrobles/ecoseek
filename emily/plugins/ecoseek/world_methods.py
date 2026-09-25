"""Methods-section renderer — provenance edges → publication-grade text.

Walks an artifact's recorded lineage (parents → …) plus its event history and
composes a deterministic "Methods" draft — no LLM in the loop. The rendered
section is itself registered as a ``methods_section`` artifact whose
``evidence`` carries the source artifact ids, so the text is traceable back to
the exact artifacts and replay runs it describes (SwarmWorld: writing is
itself an artifact, inheriting provenance).

Determinism contract: same world state ⇒ byte-identical output. Timestamps are
rendered from recorded event ts (UTC), never from wall clock at render time.
"""

from __future__ import annotations

import json
import time

try:
    from . import world, world_trace
except ImportError:  # top-level import in tests
    import world
    import world_trace


def _ts(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def _fmt_spec(spec: dict) -> str:
    """Render spec keys as an inline 'k=v' list (stable order)."""
    if not spec:
        return ""
    parts = []
    for k in sorted(spec):
        v = spec[k]
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False, sort_keys=True)
        parts.append(f"{k}={v}")
    return "; ".join(parts)


def _fmt_metrics(metrics: dict) -> str:
    if not metrics:
        return ""
    return ", ".join(
        f"{k}={metrics[k]:.4g}"
        if isinstance(metrics[k], float)
        else f"{k}={metrics[k]}"
        for k in sorted(metrics)
    )


def _exec_line(exe: dict) -> str:
    kind = exe.get("kind")
    if not kind:
        return ""
    ref = exe.get("ref", "?")
    return f" executable `{kind}:{ref}`"


def _validate_payload(artifact: dict) -> dict | None:
    """Latest validate event payload, if any."""
    payload = None
    for ev in artifact.get("events", []):
        if ev.get("kind") == "validate":
            payload = ev.get("payload") or payload
    return payload


def render_methods(
    artifact_id: str,
    register: bool = True,
    author: str | None = None,
    task_id: str = "",
) -> dict:
    """Compose a Methods section from an artifact's provenance.

    Sources = the target artifact plus every recorded ancestor (lineage walk).
    When ``register`` is true the text is proposed into the world as a
    ``methods_section`` artifact (content-addressed; re-rendering the same
    world state is a no-op that returns the existing id).
    """
    with world_trace.span("methods", artifact_id=artifact_id) as _attrs:
        result = _render(artifact_id, register=register, author=author, task_id=task_id)
    return result


def _render(
    artifact_id: str,
    register: bool = True,
    author: str | None = None,
    task_id: str = "",
) -> dict:
    rec = world.get(artifact_id)
    if not rec.get("success"):
        return rec
    target = rec["artifact"]

    lin = world.lineage(artifact_id)
    ancestors = lin.get("ancestors", []) if lin.get("success") else []

    # Fetch full records for ancestors (lineage rows lack spec/events).
    sources = []
    seen = {artifact_id}
    for anc in ancestors:
        r = world.get(anc["id"])
        if r.get("success"):
            sources.append(r["artifact"])
            seen.add(anc["id"])

    # Evidence-linked artifacts (e.g. dataset pins cited in `evidence`) are
    # provenance too — resolve ids that exist in the registry.
    for e in target.get("evidence", []):
        if isinstance(e, str) and e not in seen:
            r = world.get(e)
            if r.get("success"):
                sources.append(r["artifact"])
                seen.add(e)

    sources.append(target)  # ancestors/evidence first, target last

    paragraphs = []

    # --- Data -------------------------------------------------------------
    data_pins = [a for a in sources if a["type"] == "dataset_pin"]
    if data_pins:
        bits = []
        for a in data_pins:
            b = f"`{a['name']}`"
            spec = _fmt_spec(a.get("spec") or {})
            if spec:
                b += f" ({spec})"
            bits.append(b)
        paragraphs.append(
            "**Data.** Analyses used pinned dataset(s): " + "; ".join(bits) + "."
        )

    # --- Methods / software ----------------------------------------------
    steps = [
        a for a in sources if a["type"] in ("pipeline", "model", "script", "other")
    ]
    if steps:
        sentences = []
        for a in steps:
            s = f"`{a['name']}` ({a['type']}, status={a['status']})"
            if a.get("summary"):
                s += f" — {a['summary'].rstrip('.')}"
            s += _exec_line(a.get("executable") or {})
            spec = _fmt_spec(a.get("spec") or {})
            if spec:
                s += f"; parameters: {spec}"
            sentences.append(s)
        paragraphs.append(
            "**Workflow.** The analysis chain comprised: " + "; ".join(sentences) + "."
        )

    # --- Validation --------------------------------------------------------
    vp = _validate_payload(target)
    if vp:
        replay = vp.get("replay") or {}
        metrics = vp.get("metrics") or target.get("metrics") or {}
        holdout = replay.get("holdout") or {}
        hold_label = (
            holdout.get("name") if isinstance(holdout, dict) else holdout
        ) or "held-out inputs"
        m = _fmt_metrics(metrics)
        para = (
            f"**Validation.** `{target['name']}` was validated by frozen replay "
            f"(no LLM in the evaluation loop) on {hold_label}; "
            f"run_id=`{replay.get('run_id', '?')}`"
        )
        if m:
            para += f"; measured metrics: {m}"
        para += "."
        paragraphs.append(para)
    elif target.get("metrics"):
        paragraphs.append(
            f"**Evaluation.** Reported metrics for `{target['name']}`: "
            f"{_fmt_metrics(target['metrics'])} (not yet validated by replay)."
        )

    # --- Provenance / reproducibility --------------------------------------
    n_events = len(target.get("events", []))
    agents = sorted({e.get("agent", "?") for e in target.get("events", [])})
    paragraphs.append(
        "**Reproducibility.** All artifacts and events above are recorded in the "
        "EcoSeek World registry (append-only event log); "
        f"`{target['name']}` has {n_events} recorded event(s) from agent(s) "
        f"{', '.join(agents) or 'unknown'}"
        + (f", created {_ts(target['created_at'])}" if target.get("created_at") else "")
        + ". Replaying run evidence is stored under `runs/<run_id>/`."
    )

    text = "## Methods\n\n" + "\n\n".join(paragraphs) + "\n"
    source_ids = [a["id"] for a in sources]

    result = {
        "success": True,
        "target": artifact_id,
        "sources": source_ids,
        "methods_text": text,
        "validated": target["status"] == "validated",
        "registered": False,
    }

    if register:
        prop = world.propose(
            name=f"methods-{target['name']}",
            artifact_type="methods_section",
            summary=f"Methods section rendered from {target['name']} provenance",
            spec={
                "rendered_from": artifact_id,
                "sources": source_ids,
                "renderer": "world_methods/1",
            },
            evidence=source_ids,
            author=author,
            task_id=task_id,
        )
        if prop.get("success"):
            result["registered"] = True
            result["artifact_id"] = prop["artifact_id"]
        elif prop.get("error") == "already_registered":
            result["registered"] = True
            result["artifact_id"] = prop["artifact_id"]
            result["idempotent"] = True
        else:
            result["register_error"] = prop.get("error")
    return result
