"""EcoSeek World — scripted two-agent society smoke (the substrate probe).

Drives two agents (``alpha``, ``beta``) through a fixed scientific-work
scenario using the *real* world API — no LLM anywhere — under three
conditions that mirror the SwarmWorld experiment:

  shared     — both agents inhabit ONE world dir (artifact stigmergy)
  isolated   — two world dirs, no sync (independent-search control: the
               strong baseline; each agent must re-derive everything)
  federated  — two world dirs joined by world_sync file transport (the
               actual mesh replication path)

The comparison is the measurement: isolated can reach the same count of
validated artifacts but with zero reuse, zero lineage, zero observation-first
diffusion — shared/federated should show the stigmergic signature (derived
validated artifacts, cross-author forks, observe→reuse edges).

Determinism: the executable artifact is a frozen shell stub that emits
metrics.json — replays really execute (ECOSEEK_WORLD_REPLAY_EXEC=1) so the
validated statuses are earned by the two-gate promotion, not narrated.

CLI:
    python society.py --workdir /tmp/society --mode all --exec
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import world
import world_methods
import world_metrics
import world_replay
import world_sync

AGENTS = ("alpha", "beta")

# The "technology" the society builds: a GBIF→clean→MaxEnt→eval pipeline,
# frozen as a shell executable. Emits the metrics contract so frozen replay
# produces real evidence; `fold` is the holdout axis (spatial-block CV).
_PIPELINE_STUB = """\
import json, os, sys
kv = {}
argv = sys.argv[1:]
for i in range(0, len(argv) - 1, 2):
    kv[argv[i].lstrip("-")] = argv[i + 1]
fold = int(kv.get("fold", 0) or 0)
metrics = {
    "tss": round(0.62 + 0.04 * (fold % 3), 3),
    "auc": round(0.80 + 0.03 * (fold % 3), 3),
    "fold": fold,
}
with open(os.environ["REPLAY_METRICS_PATH"], "w") as f:
    json.dump(metrics, f)
print("pipeline done", metrics)
"""


def _use_world(world_dir: str, agent: str) -> None:
    """Point the whole world stack at ``world_dir`` acting as ``agent`` —
    same mechanism as the pytest fixtures (env + thread-local conn reset)."""
    os.environ["ECOSEEK_WORLD_DIR"] = world_dir
    os.environ["ECOSEEK_AGENT_ID"] = agent
    if getattr(world._local, "conn", None) is not None:
        world._local.conn.close()
        world._local.conn = None


def _write_stub(workdir: str) -> str:
    path = os.path.join(workdir, "bin", "pipeline.py")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(_PIPELINE_STUB)
    return path


def _build_and_validate(
    log: list, agent: str, stub: str, name: str, species: str, fold: int, holdout: str
) -> str | None:
    """Full propose→test→install→replay_validate cycle for one pipeline."""
    r = world.propose(
        name=name,
        artifact_type="pipeline",
        summary=f"GBIF → clean → MaxEnt SDM → spatial-block eval ({species})",
        spec={"tools": ["gbif_query", "run_maxent_model"], "gate": {"tss": 0.6}},
        executable={
            "kind": "shell",
            "ref": f"{sys.executable} {stub}",
            "args": {"species": species, "fold": fold},
        },
        evidence=["gbif:doi/10.15468/dl.society-smoke"],
        author=agent,
    )
    if not r.get("success"):
        log.append(
            {"step": f"{agent}:propose:{name}", "ok": False, "detail": r.get("error")}
        )
        return None
    aid = r["artifact_id"]
    log.append({"step": f"{agent}:propose:{name}", "ok": True, "detail": aid})
    world.record_event(aid, "test", {"metrics": {"tss": 0.71}}, agent=agent)
    world.record_event(aid, "install", agent=agent)
    rep = world_replay.replay_and_validate(
        aid,
        holdout={"name": holdout, "args": {"fold": 1}},
        gate={"tss": 0.6},
        agent=agent,
    )
    ok = rep.get("validation", {}).get("success", False)
    log.append(
        {
            "step": f"{agent}:replay_validate:{name}",
            "ok": ok,
            "detail": {
                "exit_code": rep.get("exit_code"),
                "metrics": rep.get("metrics"),
                "holdout": rep.get("holdout"),
            },
        }
    )
    return aid if ok else None


def _beta_reuses(log: list, stub: str, holdout: str) -> str | None:
    """Beta discovers alpha's validated artifact in the shared/federated
    world, observes it, forks it (executable inheritance), and re-earns
    validation on a different holdout."""
    found = world.query(status="validated", artifact_type="pipeline")
    parent = next((a for a in found["artifacts"] if a["author"] == "alpha"), None)
    if parent is None:
        log.append(
            {
                "step": "beta:world_query",
                "ok": False,
                "detail": "no validated alpha artifact found",
            }
        )
        return None
    pid = parent["id"]
    log.append({"step": "beta:world_query", "ok": True, "detail": pid})
    world.observe(pid, agent="beta")
    child = world.fork(
        pid,
        agent="beta",
        edits={
            "name": "sdm-gbif-maxent-rubra",
            "summary": "Fork: Quercus rubra SDM (inherited MaxEnt pipeline)",
            "executable": {
                "kind": "shell",
                "ref": f"{sys.executable} {stub}",
                "args": {"species": "Quercus rubra", "fold": 0},
            },
            "evidence": [
                "gbif:doi/10.15468/dl.society-smoke",
                "gbif:taxon/Quercus-rubra",
            ],
        },
    )
    if not child.get("success"):
        log.append({"step": "beta:fork", "ok": False, "detail": child.get("error")})
        return None
    cid = child["artifact_id"]
    log.append(
        {"step": "beta:fork", "ok": True, "detail": {"child": cid, "parent": pid}}
    )
    world.record_event(cid, "test", {"metrics": {"tss": 0.68}}, agent="beta")
    world.record_event(cid, "install", agent="beta")
    rep = world_replay.replay_and_validate(
        cid,
        holdout={"name": holdout, "args": {"fold": 2}},
        gate={"tss": 0.6},
        agent="beta",
    )
    ok = rep.get("validation", {}).get("success", False)
    log.append(
        {
            "step": "beta:replay_validate",
            "ok": ok,
            "detail": {
                "exit_code": rep.get("exit_code"),
                "metrics": rep.get("metrics"),
            },
        }
    )
    if not ok:
        return None
    meth = world_methods.render_methods(cid, author="beta")
    log.append(
        {
            "step": "beta:methods",
            "ok": meth.get("success", False),
            "detail": {
                "artifact_id": meth.get("artifact_id"),
                "sources": meth.get("sources"),
            },
        }
    )
    return cid


def _alpha_notices(log: list, child_id: str | None) -> None:
    """Alpha encounters beta's descendant — cross-agent reuse both ways."""
    if not child_id:
        return
    found = world.query(text="rubra")
    if any(a["id"] == child_id for a in found["artifacts"]):
        world.observe(child_id, agent="alpha")
        log.append({"step": "alpha:observe:child", "ok": True, "detail": child_id})


def run_society(workdir: str, mode: str = "shared", allow_exec: bool = False) -> dict:
    """Run the two-agent scenario under ``mode``. Returns the endpoint report.

    ``allow_exec=True`` sets ECOSEEK_WORLD_REPLAY_EXEC=1 for the run — the
    explicit trust decision to let frozen replays execute the stub.
    """
    if mode not in ("shared", "isolated", "federated"):
        return {"success": False, "error": f"unknown mode {mode!r}"}
    os.makedirs(workdir, exist_ok=True)
    stub = _write_stub(workdir)
    prev_exec = os.environ.get("ECOSEEK_WORLD_REPLAY_EXEC")
    if allow_exec:
        os.environ["ECOSEEK_WORLD_REPLAY_EXEC"] = "1"

    log: list[dict] = []
    started = time.time()
    try:
        if mode == "shared":
            world_dir = os.path.join(workdir, "world")
            _use_world(world_dir, "alpha")
            _build_and_validate(
                log,
                "alpha",
                stub,
                "sdm-gbif-maxent",
                "Quercus alba",
                fold=0,
                holdout="gbif-snapshot-2026-09",
            )
            _use_world(world_dir, "beta")
            cid = _beta_reuses(log, stub, holdout="spatial-block-cv")
            _use_world(world_dir, "alpha")
            _alpha_notices(log, cid)
            endpoints = world_metrics.swarm_endpoints()

        elif mode == "isolated":
            dir_a = os.path.join(workdir, "world_alpha")
            dir_b = os.path.join(workdir, "world_beta")
            _use_world(dir_a, "alpha")
            _build_and_validate(
                log,
                "alpha",
                stub,
                "sdm-gbif-maxent",
                "Quercus alba",
                fold=0,
                holdout="gbif-snapshot-2026-09",
            )
            _use_world(dir_b, "beta")
            # beta's world is empty: world_query finds nothing → independent
            # re-derivation (the independent-search control condition)
            found = world.query(status="validated", artifact_type="pipeline")
            log.append(
                {
                    "step": "beta:world_query",
                    "ok": True,
                    "detail": f"count={found['count']} (isolated world)",
                }
            )
            _build_and_validate(
                log,
                "beta",
                stub,
                "sdm-gbif-maxent",
                "Quercus rubra",
                fold=0,
                holdout="spatial-block-cv",
            )
            ep_b = world_metrics.swarm_endpoints()
            _use_world(dir_a, "alpha")
            ep_a = world_metrics.swarm_endpoints()
            # union view: the society's aggregate outcome across worlds
            endpoints = {
                "success": True,
                "condition": "isolated (union of disconnected worlds)",
                "worlds": {"alpha": ep_a, "beta": ep_b},
                "union": {
                    "artifacts": ep_a["artifacts"]["total"]
                    + ep_b["artifacts"]["total"],
                    "validated_inventions": ep_a["inventions"]["validated_inventions"]
                    + ep_b["inventions"]["validated_inventions"],
                    "lineage_edges": ep_a["lineage"]["edges"]
                    + ep_b["lineage"]["edges"],
                    "reuse_events": ep_a["reuse"]["reuse_events"]
                    + ep_b["reuse"]["reuse_events"],
                    "observation_first": ep_a["reuse"]["observation_first"]
                    + ep_b["reuse"]["observation_first"],
                    "derived_validated": 0,  # no cross-world parents exist
                },
            }

        else:  # federated
            dir_a = os.path.join(workdir, "world_alpha")
            dir_b = os.path.join(workdir, "world_beta")
            _use_world(dir_a, "alpha")
            _build_and_validate(
                log,
                "alpha",
                stub,
                "sdm-gbif-maxent",
                "Quercus alba",
                fold=0,
                holdout="gbif-snapshot-2026-09",
            )
            world_sync.export_state()
            _use_world(dir_b, "beta")
            sync1 = world_sync.sync_file(dir_a)
            log.append(
                {
                    "step": "beta:sync<-alpha",
                    "ok": sync1.get("success", False),
                    "detail": {
                        "merged": sync1.get("artifacts_merged"),
                        "events_new": sync1.get("events_new"),
                    },
                }
            )
            cid = _beta_reuses(log, stub, holdout="spatial-block-cv")
            world_sync.export_state()
            _use_world(dir_a, "alpha")
            sync2 = world_sync.sync_file(dir_b)
            log.append(
                {
                    "step": "alpha:sync<-beta",
                    "ok": sync2.get("success", False),
                    "detail": {
                        "merged": sync2.get("artifacts_merged"),
                        "events_new": sync2.get("events_new"),
                    },
                }
            )
            _alpha_notices(log, cid)
            endpoints = world_metrics.swarm_endpoints()

        derived_validated = _count_derived_validated()
        report = {
            "success": True,
            "mode": mode,
            "workdir": workdir,
            "wall_s": round(time.time() - started, 2),
            "endpoints": endpoints,
            "derived_validated": derived_validated,
            "steps": log,
        }
        if mode == "isolated":
            report["derived_validated"] = 0
        return report
    finally:
        if allow_exec:
            if prev_exec is None:
                os.environ.pop("ECOSEEK_WORLD_REPLAY_EXEC", None)
            else:
                os.environ["ECOSEEK_WORLD_REPLAY_EXEC"] = prev_exec


def _count_derived_validated() -> int:
    """Validated artifacts with non-empty lineage — technology that was
    inherited, not re-derived. The substrate-advantage endpoint."""
    with world._connect() as conn:
        rows = conn.execute(
            "SELECT parents FROM artifacts WHERE status='validated'"
        ).fetchall()
    return sum(1 for r in rows if json.loads(r["parents"] or "[]"))


def _compare(reports: dict[str, dict]) -> dict:
    """Side-by-side endpoint comparison across conditions — the actual
    SwarmWorld-style readout: does the shared/federated world beat the
    isolated envelope on structure (reuse, lineage, derived validation)."""

    def pick(rep: dict) -> dict:
        if rep["mode"] == "isolated":
            return rep["endpoints"]["union"]
        ep = rep["endpoints"]
        return {
            "artifacts": ep["artifacts"]["total"],
            "validated_inventions": ep["inventions"]["validated_inventions"],
            "lineage_edges": ep["lineage"]["edges"],
            "max_lineage_depth": ep["lineage"]["max_depth"],
            "cross_author_forks": ep["lineage"]["cross_author_forks"],
            "reuse_events": ep["reuse"]["reuse_events"],
            "observation_first": ep["reuse"]["observation_first"],
            "observation_first_fraction": ep["reuse"]["observation_first_fraction"],
            "replay_success_rate": ep["replay_resilience"]["success_rate"],
            "derived_validated": rep["derived_validated"],
        }

    return {mode: pick(rep) for mode, rep in reports.items()}


def main() -> None:  # pragma: no cover - CLI
    ap = argparse.ArgumentParser(
        description="Two-agent world society smoke — SwarmWorld endpoint probe"
    )
    ap.add_argument(
        "--workdir",
        required=True,
        help="scratch dir for worlds + stub (created if absent)",
    )
    ap.add_argument(
        "--mode", default="all", choices=["shared", "isolated", "federated", "all"]
    )
    ap.add_argument(
        "--exec",
        action="store_true",
        help="allow code-executing replays "
        "(sets ECOSEEK_WORLD_REPLAY_EXEC=1 for the run)",
    )
    args = ap.parse_args()
    modes = ("shared", "isolated", "federated") if args.mode == "all" else (args.mode,)
    reports = {}
    for mode in modes:
        reports[mode] = run_society(
            os.path.join(args.workdir, mode), mode=mode, allow_exec=args.exec
        )
    out = {"reports": reports}
    if len(reports) > 1:
        out["comparison"] = _compare(reports)
    json.dump(out, sys.stdout, indent=2, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":  # pragma: no cover
    main()
