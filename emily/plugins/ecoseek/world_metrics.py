"""EcoSeek World — SwarmWorld endpoint metrics.

Computes the evaluation endpoints the substrate was built for
(``swarmworld-alignment.md`` §2/§4): whether a shared world actually produces
collective advantage over isolated work, measured — never claimed.

Endpoints (SwarmWorld analog in parentheses):

  validated_inventions   — artifacts that cleared the two-gate promotion
                           (objective "invention" gate: install + replay
                           evidence + measured metrics)
  portfolio_breadth      — validated artifacts by type (complementary
                           portfolio, not a single champion)
  lineage                — executable-inheritance graph: depth, fork edges,
                           cross-author fork fraction
  reuse                  — non-author test/install/fork/validate/repair events;
                           observation-first fraction = reuses preceded by an
                           ``observe`` from the same agent (the ~95% physical-
                           stigmergy channel)
  replay_resilience      — frozen-replay runs on disk and inside validate
                           events: exit-0 rate across held-out inputs — the
                           "remove the agents" test
  best_artifact          — per-metric champion across the world (the isolated-
                           search comparator endpoint)
  agents                 — per-agent activity/authorship/reuse breakdown
  timescale              — event span; ``series`` replays the endpoint suite
                           over event prefixes (per-endpoint timescales)

Read-only: a metrics call never writes to the world. Everything derives from
recorded events and artifact fields — no inference, no embeddings.
"""

from __future__ import annotations

import json
import os
import time

try:
    from . import world
except ImportError:  # standalone import (tests load the dir via sys.path)
    import world  # type: ignore[no-redef]

# Event kinds that count as *use* of an artifact (vs. authorship/metadata).
_REUSE_KINDS = ("test", "install", "validate", "repair")


def _load_events(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT seq, ts, artifact_id, agent, kind, payload, task_id"
        " FROM events ORDER BY seq"
    ).fetchall()
    return [
        {
            "seq": r["seq"],
            "ts": r["ts"],
            "artifact_id": r["artifact_id"],
            "agent": r["agent"],
            "kind": r["kind"],
            "payload": json.loads(r["payload"] or "{}"),
            "task_id": r["task_id"],
        }
        for r in rows
    ]


def _load_artifacts(conn) -> dict[str, dict]:
    rows = conn.execute("SELECT * FROM artifacts").fetchall()
    return {r["id"]: world._row_to_artifact(r) for r in rows}


def _reuse_events(events: list[dict], artifacts: dict[str, dict]) -> list[dict]:
    """Events where an agent *used* an artifact it did not author.

    ``fork`` is handled separately: the child-side event records authorship of
    the descendant; the parent-side row (payload.direction == 'parent') is the
    reuse edge — the forker consumed the parent's executable content.
    """
    out = []
    for e in events:
        art = artifacts.get(e["artifact_id"])
        if art is None or e["agent"] == art["author"]:
            continue
        if (
            e["kind"] in _REUSE_KINDS
            or e["kind"] == "fork"
            and e["payload"].get("direction") == "parent"
        ):
            out.append(e)
    return out


def _observation_first(
    events: list[dict], artifacts: dict[str, dict], reuse: list[dict]
) -> tuple[int, int]:
    """Of the (agent, artifact) pairs that reused, how many observed first.

    A pair is observation-first when the reusing agent recorded an ``observe``
    event on that artifact with a lower seq than their first reuse event.
    Returns (observation_first_pairs, reusing_pairs).
    """
    first_reuse: dict[tuple[str, str], int] = {}
    for e in reuse:
        key = (e["agent"], e["artifact_id"])
        if key not in first_reuse or e["seq"] < first_reuse[key]:
            first_reuse[key] = e["seq"]
    observe_seq: dict[tuple[str, str], int] = {}
    for e in events:
        if e["kind"] != "observe":
            continue
        key = (e["agent"], e["artifact_id"])
        if key not in observe_seq or e["seq"] < observe_seq[key]:
            observe_seq[key] = e["seq"]
    obs_first = sum(
        1
        for key, rseq in first_reuse.items()
        if key in observe_seq and observe_seq[key] < rseq
    )
    return obs_first, len(first_reuse)


def _lineage_stats(artifacts: dict[str, dict]) -> dict:
    edges = 0
    cross_author = 0
    roots = 0
    for a in artifacts.values():
        parents = [p for p in a["parents"] if p in artifacts]
        if not parents:
            roots += 1
            continue
        edges += len(parents)
        for p in parents:
            if artifacts[p]["author"] != a["author"]:
                cross_author += 1
    # depth = longest parent chain (memoized; cycles cannot form — parents
    # always point to earlier content ids, but guard anyway)
    depth_memo: dict[str, int] = {}

    def depth(aid: str, stack: set[str]) -> int:
        if aid in depth_memo:
            return depth_memo[aid]
        if aid in stack:
            return 0
        stack.add(aid)
        a = artifacts.get(aid)
        d = 0
        if a:
            for p in a["parents"]:
                if p in artifacts:
                    d = max(d, 1 + depth(p, stack))
        stack.discard(aid)
        depth_memo[aid] = d
        return d

    depths = [depth(aid, set()) for aid in artifacts]
    return {
        "edges": edges,
        "roots": roots,
        "max_depth": max(depths, default=0),
        "mean_depth": round(sum(depths) / len(depths), 3) if depths else 0.0,
        "cross_author_forks": cross_author,
        "cross_author_fork_fraction": round(cross_author / edges, 3) if edges else 0.0,
    }


def _replay_resilience(world_dir: str, events: list[dict]) -> dict:
    """Frozen-replay outcomes: run dirs under ``runs/`` plus replay evidence
    carried in validate-event payloads."""
    runs, succeeded, holdouts, seen_ids = 0, 0, set(), set()
    runs_dir = os.path.join(world_dir, "runs")
    if os.path.isdir(runs_dir):
        for entry in os.listdir(runs_dir):
            ev_path = os.path.join(runs_dir, entry, "replay.json")
            try:
                with open(ev_path) as fh:
                    ev = json.load(fh)
            except (OSError, ValueError):
                continue
            rid = ev.get("run_id") or entry
            if rid in seen_ids:
                continue
            seen_ids.add(rid)
            runs += 1
            if ev.get("exit_code") == 0:
                succeeded += 1
            if ev.get("holdout"):
                holdouts.add(str(ev["holdout"]))
    for e in events:
        if e["kind"] != "validate":
            continue
        rep = e["payload"].get("replay") or {}
        rid = rep.get("run_id")
        if not rid or rid in seen_ids:
            continue
        seen_ids.add(rid)
        runs += 1
        if rep.get("exit_code") == 0:
            succeeded += 1
        h = rep.get("holdout")
        if h:
            holdouts.add(str(h if not isinstance(h, dict) else h.get("name")))
    holdouts.discard("None")
    return {
        "runs": runs,
        "succeeded": succeeded,
        "success_rate": round(succeeded / runs, 3) if runs else 0.0,
        "distinct_holdouts": sorted(holdouts),
    }


def _best_artifact(artifacts: dict[str, dict]) -> dict:
    """Per-metric champion — the isolated-search endpoint a shared world must
    beat on breadth/resilience, since isolated search keeps the best single
    object (SwarmWorld finding 1)."""
    best: dict[str, dict] = {}
    for a in artifacts.values():
        for k, v in (a.get("metrics") or {}).items():
            if not isinstance(v, (int, float)):
                continue
            cur = best.get(k)
            if cur is None or v > cur["value"]:
                best[k] = {"artifact_id": a["id"], "value": v}
    return best


def _per_agent(events: list[dict], artifacts: dict[str, dict]) -> dict:
    agents: dict[str, dict] = {}

    def slot(agent: str) -> dict:
        return agents.setdefault(
            agent,
            {
                "events": 0,
                "proposed": 0,
                "validated_authored": 0,
                "reused_foreign": 0,
                "observed": 0,
            },
        )

    authors = {aid: a["author"] for aid, a in artifacts.items()}
    for e in events:
        s = slot(e["agent"])
        s["events"] += 1
        if e["kind"] == "propose":
            s["proposed"] += 1
        elif e["kind"] == "observe":
            s["observed"] += 1
        elif e["kind"] == "validate":
            if authors.get(e["artifact_id"]) == e["agent"]:
                s["validated_authored"] += 1
    for e in _reuse_events(events, artifacts):
        slot(e["agent"])["reused_foreign"] += 1
    return agents


def swarm_endpoints() -> dict:
    """Full endpoint suite for the world at ECOSEEK_WORLD_DIR. Read-only."""
    with world._connect() as conn:
        artifacts = _load_artifacts(conn)
        events = _load_events(conn)

    total = len(artifacts)
    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}
    validated_by_type: dict[str, int] = {}
    validate_latencies = []
    first_propose_ts: dict[str, float] = {}
    for e in events:
        if e["kind"] == "propose" and e["artifact_id"] not in first_propose_ts:
            first_propose_ts[e["artifact_id"]] = e["ts"]
    for a in artifacts.values():
        by_status[a["status"]] = by_status.get(a["status"], 0) + 1
        by_type[a["type"]] = by_type.get(a["type"], 0) + 1
        if a["status"] == "validated":
            validated_by_type[a["type"]] = validated_by_type.get(a["type"], 0) + 1
            t0 = first_propose_ts.get(a["id"])
            if t0:
                validate_latencies.append(a["updated_at"] - t0)

    reuse = _reuse_events(events, artifacts)
    obs_first, reusing_pairs = _observation_first(events, artifacts, reuse)
    reused_artifacts = {e["artifact_id"] for e in reuse}

    ts = [e["ts"] for e in events]
    return {
        "success": True,
        "world_dir": world._world_dir(),
        "artifacts": {
            "total": total,
            "by_status": by_status,
            "by_type": by_type,
        },
        "inventions": {
            "validated_inventions": by_status.get("validated", 0),
            "validated_by_type": validated_by_type,
            "validated_fraction": round(by_status.get("validated", 0) / total, 3)
            if total
            else 0.0,
            "mean_propose_to_validate_s": round(
                sum(validate_latencies) / len(validate_latencies), 1
            )
            if validate_latencies
            else None,
        },
        "lineage": _lineage_stats(artifacts),
        "reuse": {
            "reuse_events": len(reuse),
            "artifacts_reused": len(reused_artifacts),
            "cross_agent_reuse_fraction": round(len(reused_artifacts) / total, 3)
            if total
            else 0.0,
            "observation_first": obs_first,
            "observation_first_fraction": round(obs_first / reusing_pairs, 3)
            if reusing_pairs
            else 0.0,
        },
        "replay_resilience": _replay_resilience(world._world_dir(), events),
        "best_artifact": _best_artifact(artifacts),
        "agents": _per_agent(events, artifacts),
        "timescale": {
            "events": len(events),
            "first_ts": min(ts) if ts else None,
            "last_ts": max(ts) if ts else None,
            "span_s": round(max(ts) - min(ts), 1) if len(ts) > 1 else 0.0,
        },
    }


# ---------------------------------------------------------------------------
# Per-endpoint timescales — SwarmWorld finding 10: no single crossover tick;
# evaluate each endpoint over the event stream, not just at the endpoint.
# ---------------------------------------------------------------------------

_PREFIX_TRANSITIONS = {
    "propose": "proposed",
    "test": "tested",
    "install": "installed",
    "validate": "validated",
    "dismantle": "retired",
}


def _prefix_artifacts(events: list[dict]) -> dict[str, dict]:
    """Minimal artifact state reconstructed from an event prefix — enough for
    endpoints (status, author, type, parents, metrics) without touching the
    artifacts table."""
    arts: dict[str, dict] = {}
    for e in events:
        aid = e["artifact_id"]
        a = arts.setdefault(
            aid,
            {
                "id": aid,
                "author": "unknown",
                "type": "other",
                "status": "proposed",
                "parents": [],
                "metrics": {},
            },
        )
        if e["kind"] == "propose":
            a["author"] = e["agent"]
            a["type"] = e["payload"].get("type") or "other"
        elif e["kind"] == "fork" and e["payload"].get("parent"):
            if e["payload"]["parent"] not in a["parents"]:
                a["parents"].append(e["payload"]["parent"])
        elif e["kind"] in ("test", "validate") and e["payload"].get("metrics"):
            a["metrics"].update(e["payload"]["metrics"])
        new = _PREFIX_TRANSITIONS.get(e["kind"])
        if new and new != "proposed":
            # same legal-order rules as world._apply_transition, condensed:
            order = {"tested": 1, "installed": 2, "validated": 3, "retired": 4}
            if order[new] > order.get(a["status"], 0) or new == "retired":
                a["status"] = new
    return arts


def _prefix_endpoints(events: list[dict]) -> dict:
    """Compact endpoint vector over an event prefix (no disk reads)."""
    arts = _prefix_artifacts(events)
    total = len(arts)
    by_status: dict[str, int] = {}
    for a in arts.values():
        by_status[a["status"]] = by_status.get(a["status"], 0) + 1
    reuse = _reuse_events(events, arts)
    obs_first, pairs = _observation_first(events, arts, reuse)
    lineage = _lineage_stats(arts)
    return {
        "events": len(events),
        "artifacts": total,
        "validated_inventions": by_status.get("validated", 0),
        "max_lineage_depth": lineage["max_depth"],
        "cross_author_fork_fraction": lineage["cross_author_fork_fraction"],
        "reuse_events": len(reuse),
        "observation_first_fraction": round(obs_first / pairs, 3) if pairs else 0.0,
    }


def endpoint_series(points: int = 10) -> dict:
    """Endpoint vectors at ``points`` evenly spaced prefixes of the event
    stream — per-endpoint timescales instead of one final snapshot."""
    with world._connect() as conn:
        events = _load_events(conn)
    n = len(events)
    if n == 0:
        return {"success": True, "series": [], "points": 0}
    points = max(2, min(points, n))
    idxs = sorted({round(i * (n - 1) / (points - 1)) + 1 for i in range(points)})
    return {
        "success": True,
        "series": [_prefix_endpoints(events[:i]) for i in idxs],
        "points": len(idxs),
        "total_events": n,
    }


def main() -> None:  # pragma: no cover - CLI convenience
    """``python world_metrics.py [world_dir] [--series N]`` — print endpoints."""
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="EcoSeek World — SwarmWorld endpoints")
    ap.add_argument("world_dir", nargs="?", help="ECOSEEK_WORLD_DIR override")
    ap.add_argument(
        "--series",
        type=int,
        default=0,
        metavar="N",
        help="also emit the per-endpoint timeseries at N prefixes",
    )
    ap.add_argument("--agent", default=None, help="ECOSEEK_AGENT_ID for the report")
    args = ap.parse_args()
    if args.world_dir:
        os.environ["ECOSEEK_WORLD_DIR"] = args.world_dir
    if args.agent:
        os.environ["ECOSEEK_AGENT_ID"] = args.agent
    world._local.conn = None
    out = {"generated_at": time.time(), "endpoints": swarm_endpoints()}
    if args.series:
        out["series"] = endpoint_series(args.series)
    json.dump(out, sys.stdout, indent=2, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":  # pragma: no cover
    main()
