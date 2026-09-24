"""Smoke tests for EcoSeek World — persistent artifact substrate.

Tests the full artifact lifecycle offline: propose → test → install →
validate (two-gate), fork/lineage (executable inheritance), observe
(stigmergic reuse), query (FTS), stats, dismantle, and federation import.
No network calls. Uses a temp ECOSEEK_WORLD_DIR per test session.

Run with:
    cd emily/plugins/ecoseek && python -m pytest test_world_smoke.py -v
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture()
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("ECOSEEK_WORLD_DIR", str(tmp_path / "world"))
    monkeypatch.setenv("ECOSEEK_AGENT_ID", "emily")
    import world as w

    # fresh thread-local connection per test dir
    w._local.conn = None
    yield w
    try:
        w._local.conn.close()
    except Exception:
        pass
    w._local.conn = None


def _pipeline(world):
    return world.propose(
        name="sdm-maxent-gbif",
        artifact_type="pipeline",
        summary="GBIF query → clean → MaxEnt SDM → TSS eval",
        spec={"tools": ["gbif_query", "run_maxent_model"], "gate": {"tss": 0.6}},
        executable={"kind": "ecoagent_tool", "ref": "sdm_pipeline", "args": {"species": "Quercus alba"}},
        evidence=["gbif:doi/10.15468/dl.test"],
        author="emily",
    )


class TestLifecycle:
    def test_propose(self, world):
        r = _pipeline(world)
        assert r["success"] and r["status"] == "proposed"
        assert len(r["artifact_id"]) == 16

    def test_novelty_gate_rejects_duplicate(self, world):
        _pipeline(world)
        dup = _pipeline(world)
        assert not dup["success"] and dup["error"] == "already_registered"

    def test_status_machine_order(self, world):
        aid = _pipeline(world)["artifact_id"]
        # cannot install before test
        r = world.record_event(aid, "install")
        assert not r["success"]
        # cannot validate before install
        r = world.validate(aid, {"tss": 0.7}, {"run_id": "x", "exit_code": 0})
        assert not r["success"]
        # legal order
        assert world.record_event(aid, "test", {"metrics": {"tss": 0.71}})["status"] == "tested"
        assert world.record_event(aid, "install")["status"] == "installed"

    def test_validate_requires_replay_and_metrics(self, world):
        aid = _pipeline(world)["artifact_id"]
        world.record_event(aid, "test", {"metrics": {"tss": 0.71}})
        world.record_event(aid, "install")
        # no metrics → rejected
        assert not world.validate(aid, {}, {"run_id": "r1", "exit_code": 0})["success"]
        # no replay → rejected
        assert not world.validate(aid, {"tss": 0.7}, {})["success"]
        # failed replay → rejected
        assert not world.validate(
            aid, {"tss": 0.7}, {"run_id": "r1", "exit_code": 1}
        )["success"]
        # LLM-only evidence → rejected (attest is advisory, not a gate)
        world.record_event(aid, "attest", {"score": 0.95, "verdict": "excellent"})
        assert not world.validate(aid, {"judge": 0.95}, {})["success"]
        # full gate → validated
        ok = world.validate(
            aid,
            {"tss": 0.68, "auc": 0.91},
            {"run_id": "replay-001", "exit_code": 0, "holdout": "gbif-snapshot-2026-09"},
        )
        assert ok["success"] and ok["status"] == "validated"

    def test_dismantle_retires(self, world):
        aid = _pipeline(world)["artifact_id"]
        assert world.record_event(aid, "dismantle")["status"] == "retired"


class TestInheritance:
    def test_fork_creates_lineage(self, world):
        parent = _pipeline(world)["artifact_id"]
        child = world.fork(parent, edits={"name": "sdm-maxent-gbif-v2"})
        assert child["success"] and child["parent"] == parent
        rec = world.get(child["artifact_id"])["artifact"]
        assert rec["parents"] == [parent]
        lin = world.lineage(child["artifact_id"])
        assert lin["depth"] == 1 and lin["ancestors"][0]["id"] == parent

    def test_grandchild_depth(self, world):
        a = _pipeline(world)["artifact_id"]
        b = world.fork(a, edits={"name": "v2"})["artifact_id"]
        c = world.fork(b, edits={"name": "v3"})["artifact_id"]
        assert world.lineage(c)["depth"] == 2
        assert world.stats()["max_lineage_depth"] == 2


class TestStigmergy:
    def test_observe_cross_agent_reuse(self, world):
        aid = _pipeline(world)["artifact_id"]  # author=emily
        world.observe(aid, agent="hermes")  # remote agent reuses it
        s = world.stats()
        assert s["cross_agent_reused"] == 1 and s["reuse_fraction"] == 1.0

    def test_query_finds_validated(self, world):
        aid = _pipeline(world)["artifact_id"]
        world.record_event(aid, "test", {"metrics": {"tss": 0.71}})
        world.record_event(aid, "install")
        world.validate(aid, {"tss": 0.68}, {"run_id": "r1", "exit_code": 0})
        r = world.query(text="MaxEnt", status="validated")
        assert r["count"] == 1 and r["artifacts"][0]["id"] == aid
        # filters combine
        assert world.query(text="MaxEnt", status="proposed")["count"] == 0
        assert world.query(artifact_type="pipeline")["count"] == 1


class TestProvenance:
    def test_event_history_recorded(self, world):
        aid = _pipeline(world)["artifact_id"]
        world.record_event(aid, "test", {"metrics": {"tss": 0.71}})
        world.observe(aid, agent="hermes")
        rec = world.get(aid)["artifact"]
        kinds = [e["kind"] for e in rec["events"]]
        assert kinds == ["propose", "test", "observe"]
        assert rec["metrics"]["tss"] == 0.71

    def test_jsonl_log_written(self, world):
        _pipeline(world)
        path = os.path.join(world._world_dir(), "events.jsonl")
        assert os.path.exists(path)
        with open(path) as f:
            lines = [json.loads(l) for l in f if l.strip()]
        assert lines[0]["kind"] == "propose" and lines[0]["agent"] == "emily"


class TestFederation:
    def test_import_artifact_idempotent(self, world):
        aid = _pipeline(world)["artifact_id"]
        art = world.get(aid)["artifact"]
        # same artifact imported again → no merge
        r = world.import_artifact(art)
        assert r["success"] and r["merged"] is False
        # foreign artifact → merged
        foreign = dict(art, id="deadbeefcafef00d", name="remote-pipe")
        r = world.import_artifact(foreign, events=[{"kind": "propose", "agent": "hermes"}])
        assert r["success"] and r["merged"] is True
        assert world.get("deadbeefcafef00d")["success"]
