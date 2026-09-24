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
        executable={
            "kind": "ecoagent_tool",
            "ref": "sdm_pipeline",
            "args": {"species": "Quercus alba"},
        },
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
        assert (
            world.record_event(aid, "test", {"metrics": {"tss": 0.71}})["status"]
            == "tested"
        )
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
        assert not world.validate(aid, {"tss": 0.7}, {"run_id": "r1", "exit_code": 1})[
            "success"
        ]
        # LLM-only evidence → rejected (attest is advisory, not a gate)
        world.record_event(aid, "attest", {"score": 0.95, "verdict": "excellent"})
        assert not world.validate(aid, {"judge": 0.95}, {})["success"]
        # full gate → validated
        ok = world.validate(
            aid,
            {"tss": 0.68, "auc": 0.91},
            {
                "run_id": "replay-001",
                "exit_code": 0,
                "holdout": "gbif-snapshot-2026-09",
            },
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
        r = world.import_artifact(
            foreign, events=[{"kind": "propose", "agent": "hermes"}]
        )
        assert r["success"] and r["merged"] is True
        assert world.get("deadbeefcafef00d")["success"]


@pytest.fixture()
def replay(world, monkeypatch):
    """Frozen replay runner bound to the same temp world dir."""
    import world_replay as wr

    monkeypatch.setenv("ECOSEEK_WORLD_REPLAY_EXEC", "1")
    return wr


def _installed_shell(world, tmp_path, script_body, args=None, script_name="pipe.py"):
    """Propose + install a shell-executable artifact; returns (aid, script)."""
    script = tmp_path / script_name
    script.write_text(script_body)
    r = world.propose(
        name="frozen-pipe",
        artifact_type="pipeline",
        executable={
            "kind": "shell",
            "ref": f"{sys.executable} {script}",
            "args": args or {},
        },
    )
    aid = r["artifact_id"]
    world.record_event(aid, "test", {"metrics": {"tss": 0.71}})
    world.record_event(aid, "install")
    return aid


_OK_SCRIPT = """\
import json, os
with open(os.environ["REPLAY_METRICS_PATH"], "w") as f:
    json.dump({"tss": 0.74, "auc": 0.91}, f)
print("replay done")
"""


class TestFrozenReplay:
    def test_gated_by_default(self, world, tmp_path, monkeypatch):
        monkeypatch.delenv("ECOSEEK_WORLD_REPLAY_EXEC", raising=False)
        import world_replay as wr

        aid = _installed_shell(world, tmp_path, _OK_SCRIPT)
        r = wr.replay(aid)
        assert not r["success"] and "fail-closed" in r["error"]

    def test_shell_replay_metrics_and_evidence(self, world, replay, tmp_path):
        aid = _installed_shell(world, tmp_path, _OK_SCRIPT)
        r = replay.replay(aid, holdout={"name": "gbif-2026-09"})
        assert r["success"] and r["exit_code"] == 0
        assert r["metrics"]["tss"] == 0.74
        assert r["holdout"] == "gbif-2026-09"
        # durable evidence on disk
        with open(os.path.join(r["run_dir"], "replay.json")) as f:
            ev = json.load(f)
        assert ev["run_id"] == r["run_id"] and ev["artifact_id"] == aid
        assert os.path.exists(os.path.join(r["run_dir"], "stdout.log"))

    def test_replay_and_validate_promotes(self, world, replay, tmp_path):
        aid = _installed_shell(world, tmp_path, _OK_SCRIPT)
        r = replay.replay_and_validate(
            aid, holdout={"name": "block-cv"}, gate={"tss": 0.6}
        )
        assert r["validation"]["success"] and r["validation"]["status"] == "validated"
        assert world.get(aid)["artifact"]["status"] == "validated"

    def test_gate_blocks_below_floor(self, world, replay, tmp_path):
        aid = _installed_shell(world, tmp_path, _OK_SCRIPT)
        r = replay.replay_and_validate(aid, gate={"tss": 0.9})
        assert r["exit_code"] == 0 and not r["validation"]["success"]
        assert world.get(aid)["artifact"]["status"] == "installed"

    def test_nonzero_exit_preserves_code_and_skips(self, world, replay, tmp_path):
        aid = _installed_shell(
            world, tmp_path, 'import sys; sys.stderr.write("boom"); sys.exit(3)\n'
        )
        r = replay.replay_and_validate(aid)
        assert r["exit_code"] == 3 and r["validation"]["skipped"]
        assert world.get(aid)["artifact"]["status"] == "installed"

    def test_no_metrics_no_validate(self, world, replay, tmp_path):
        aid = _installed_shell(world, tmp_path, 'print("no metrics here")\n')
        r = replay.replay_and_validate(aid)
        assert r["exit_code"] == 0 and r["metrics"] == {}
        assert r["validation"]["skipped"]

    def test_holdout_args_merged_and_exposed(self, world, replay, tmp_path):
        body = """\
import json, os
h = json.loads(os.environ["REPLAY_HOLDOUT"])
with open(os.environ["REPLAY_METRICS_PATH"], "w") as f:
    json.dump({"species": h["args"]["species"], "reps": h["args"]["reps"]}, f)
"""
        aid = _installed_shell(world, tmp_path, body, args={"reps": 1})
        r = replay.replay(
            aid, holdout={"name": "h1", "args": {"species": "Q. rubra", "reps": 5}}
        )
        # holdout args override executable.args
        assert r["metrics"] == {"species": "Q. rubra", "reps": 5}

    def test_missing_and_malformed_executables(self, world, replay, tmp_path):
        r = world.propose(name="no-exe")
        out = replay.replay(r["artifact_id"])
        assert not out["success"] and "unsupported" in out["error"]
        r = world.propose(name="bad-kind", executable={"kind": "magic", "ref": "x"})
        assert not replay.replay(r["artifact_id"])["success"]
        r = world.propose(name="no-ref", executable={"kind": "shell"})
        out = replay.replay(r["artifact_id"])
        assert not out["success"] and "ref" in out["error"]

    def test_timeout_and_secrets_stripped(self, world, replay, tmp_path, monkeypatch):
        monkeypatch.setenv("GBIF_API_KEY", "secret-key-123")
        body = """\
import json, os
with open(os.environ["REPLAY_METRICS_PATH"], "w") as f:
    json.dump({"has_key": "GBIF_API_KEY" in os.environ}, f)
"""
        aid = _installed_shell(world, tmp_path, body)
        r = replay.replay(aid)
        assert r["exit_code"] == 0 and r["metrics"]["has_key"] is False
        # timeout → exit 124
        aid2 = _installed_shell(
            world, tmp_path, "import time; time.sleep(30)\n", script_name="s2.py"
        )
        r = replay.replay(aid2, timeout_s=1)
        assert r["exit_code"] == 124

    def test_ecoagent_tool_dispatch(self, world, replay, monkeypatch):
        """ecoagent_tool runs via tools.registry.dispatch — zero LLM."""
        import types

        calls = {}

        class FakeRegistry:
            def dispatch(self, name, args, **kw):
                calls["name"], calls["args"] = name, args
                return json.dumps({"metrics": {"tss": 0.66}, "ok": True})

        reg_mod = types.ModuleType("tools.registry")
        reg_mod.registry = FakeRegistry()
        pkg = types.ModuleType("tools")
        pkg.registry = reg_mod
        monkeypatch.setitem(sys.modules, "tools", pkg)
        monkeypatch.setitem(sys.modules, "tools.registry", reg_mod)

        aid = _pipeline(world)["artifact_id"]
        r = replay.replay(aid)
        assert r["exit_code"] == 0
        assert calls["name"] == "sdm_pipeline"
        assert calls["args"]["species"] == "Quercus alba"
        assert r["metrics"]["tss"] == 0.66

    def test_ecoagent_tool_error_payload_and_missing_registry(
        self, world, replay, monkeypatch
    ):
        import types

        class ErrRegistry:
            def dispatch(self, name, args, **kw):
                return {"error": f"Unknown tool: {name}"}

        reg_mod = types.ModuleType("tools.registry")
        reg_mod.registry = ErrRegistry()
        monkeypatch.setitem(sys.modules, "tools.registry", reg_mod)
        aid = _pipeline(world)["artifact_id"]
        r = replay.replay(aid)
        assert r["exit_code"] == 1 and "Unknown tool" in r["stderr_tail"]

        # no registry at all → exit 2
        monkeypatch.setitem(sys.modules, "tools", None)
        monkeypatch.delitem(sys.modules, "tools.registry", raising=False)
        aid2 = world.fork(aid, edits={"name": "sdm-v2"})["artifact_id"]
        r = replay.replay(aid2)
        assert r["exit_code"] == 2 and "tools.registry" in r["stderr_tail"]


@pytest.fixture()
def methods(world):
    import world_methods as wm

    return wm


def _validated_pipeline(world):
    aid = _pipeline(world)["artifact_id"]
    world.record_event(aid, "test", {"metrics": {"tss": 0.71}})
    world.record_event(aid, "install")
    world.validate(
        aid,
        {"tss": 0.68, "auc": 0.91},
        {"run_id": "run-abc", "exit_code": 0, "holdout": {"name": "block-cv"}},
    )
    return aid


class TestMethods:
    def test_render_validated_sections(self, world, methods):
        aid = _validated_pipeline(world)
        r = methods.render_methods(aid)
        assert r["success"] and r["validated"] and r["registered"]
        t = r["methods_text"]
        assert "## Methods" in t
        assert "**Workflow.**" in t and "sdm-maxent-gbif" in t
        assert "**Validation.**" in t and "run-abc" in t and "block-cv" in t
        assert "tss=0.68" in t and "auc=0.91" in t
        assert "**Reproducibility.**" in t
        # the section itself became a methods_section artifact
        art = world.get(r["artifact_id"])["artifact"]
        assert art["type"] == "methods_section"
        assert aid in art["evidence"] and aid in art["spec"]["sources"]

    def test_lineage_sources_included(self, world, methods):
        world.propose(
            name="gbif-pin",
            artifact_type="dataset_pin",
            spec={"source": "gbif", "n_records": 4211},
        )["artifact_id"]
        parent = _pipeline(world)["artifact_id"]
        child = world.fork(parent, edits={"name": "sdm-v2"})["artifact_id"]
        r = methods.render_methods(child, register=False)
        assert r["sources"][0] == parent and r["sources"][-1] == child
        assert "sdm-maxent-gbif" in r["methods_text"]
        assert not r["registered"]

    def test_evidence_linked_pin_rendered(self, world, methods):
        """dataset_pin cited via evidence[] joins the Data paragraph."""
        pin = world.propose(
            name="gbif-quercus-pin",
            artifact_type="dataset_pin",
            spec={"source": "gbif", "n_records": 4211},
        )["artifact_id"]
        r = world.propose(
            name="sdm-pin-cited",
            artifact_type="pipeline",
            evidence=[pin],
        )
        out = methods.render_methods(r["artifact_id"], register=False)
        assert "**Data.**" in out["methods_text"]
        assert "gbif-quercus-pin" in out["methods_text"]
        assert pin in out["sources"]

    def test_data_pin_paragraph(self, world, methods):
        pin = world.propose(
            name="gbif-pin",
            artifact_type="dataset_pin",
            spec={"source": "gbif", "n_records": 4211},
        )["artifact_id"]
        r = methods.render_methods(pin, register=False)
        assert "**Data.**" in r["methods_text"]
        assert "n_records=4211" in r["methods_text"]

    def test_unvalidated_marks_not_validated(self, world, methods):
        aid = _pipeline(world)["artifact_id"]
        world.record_event(aid, "test", {"metrics": {"tss": 0.71}})
        r = methods.render_methods(aid, register=False)
        assert r["validated"] is False
        assert "not yet validated by replay" in r["methods_text"]
        assert "**Validation.**" not in r["methods_text"]

    def test_deterministic_and_idempotent(self, world, methods):
        aid = _validated_pipeline(world)
        r1 = methods.render_methods(aid)
        r2 = methods.render_methods(aid)
        assert r1["methods_text"] == r2["methods_text"]
        assert r1["artifact_id"] == r2["artifact_id"]
        assert r2.get("idempotent")

    def test_missing_artifact(self, world, methods):
        r = methods.render_methods("deadbeef")
        assert not r["success"]


@pytest.fixture()
def sync(world, tmp_path, monkeypatch):
    """world_sync bound to the test world; `peer_world(dir)` helper builds a
    second live world in another dir (same module, re-pointed env)."""
    import world_sync as ws

    def peer_world(path):
        monkeypatch.setenv("ECOSEEK_WORLD_DIR", str(path))
        world._local.conn = None
        return world

    def back_to_main():
        monkeypatch.setenv("ECOSEEK_WORLD_DIR", str(tmp_path / "world"))
        world._local.conn = None

    ws._peer_world = peer_world
    ws._back = back_to_main
    return ws


class TestSync:
    def test_file_sync_pulls_artifacts_and_events(self, world, sync, tmp_path):
        peer_dir = tmp_path / "peer"
        sync._peer_world(peer_dir)
        aid = _pipeline(world)["artifact_id"]
        world.record_event(aid, "test", {"metrics": {"tss": 0.71}})
        world.record_event(aid, "install")
        world.validate(aid, {"tss": 0.7}, {"run_id": "r1", "exit_code": 0})
        sync.export_state()
        sync._back()

        r = sync.sync_file(str(peer_dir))
        assert r["success"] and r["artifacts_merged"] == 1
        art = world.get(aid)["artifact"]
        assert art["status"] == "validated"
        assert len(art["events"]) == 4

    def test_status_precedence_never_downgrades(self, world, sync, tmp_path):
        aid = _pipeline(world)["artifact_id"]
        world.record_event(aid, "test", {"metrics": {"tss": 0.9}})
        world.record_event(aid, "install")
        world.validate(aid, {"tss": 0.9}, {"run_id": "r1", "exit_code": 0})
        sync.export_state()

        # peer has the SAME artifact id but only at proposed (stale replica)
        peer_dir = tmp_path / "peer"
        peer_dir.mkdir()
        art = world.get(aid)["artifact"]
        stale = dict(art, status="proposed", metrics={})
        stale.pop("events", None)
        with open(peer_dir / "artifacts.jsonl", "w") as f:
            f.write(json.dumps(stale, sort_keys=True) + "\n")

        r = sync.sync_file(str(peer_dir))
        assert r["artifacts_kept"] == 1
        assert world.get(aid)["artifact"]["status"] == "validated"

    def test_merge_union_and_idempotent(self, world, sync, tmp_path):
        peer_dir = tmp_path / "peer"
        sync._peer_world(peer_dir)
        _pipeline(world)  # same content-addressed artifact in both worlds
        remote = world.propose(name="remote-only", artifact_type="report")
        sync.export_state()
        sync._back()

        r1 = sync.sync_file(str(peer_dir))
        assert r1["artifacts_merged"] == 2  # local world was empty → both merge
        assert world.get(remote["artifact_id"])["success"]
        # second sync: nothing new
        r2 = sync.sync_file(str(peer_dir))
        assert r2["artifacts_merged"] == 0 and r2["events_new"] == 0

    def test_bidirectional_writeback(self, world, sync, tmp_path):
        local = world.propose(name="local-only", artifact_type="report")
        sync.export_state()
        peer_dir = tmp_path / "peer"
        peer_dir.mkdir()
        sync.sync_file(str(peer_dir))
        # peer snapshot now carries our artifact
        with open(peer_dir / "artifacts.jsonl") as fh:
            rows = [json.loads(l) for l in fh if l.strip()]
        assert any(r["id"] == local["artifact_id"] for r in rows)

    def test_git_transport_merge_and_push(self, world, sync, tmp_path):
        # remote bare repo + peer clone pre-populated with a remote artifact
        remote = tmp_path / "remote.git"
        peer_dir = tmp_path / "peer"
        import subprocess

        subprocess.run(
            ["git", "init", "--bare", str(remote)], check=True, capture_output=True
        )
        sync._peer_world(peer_dir)
        aid = _pipeline(world)["artifact_id"]
        sync.export_state()
        subprocess.run(
            ["git", "-C", str(peer_dir), "init", "-b", "main"],
            check=True,
            capture_output=True,
        )
        for c in (
            ["config", "user.email", "t@t"],
            ["config", "user.name", "t"],
            ["remote", "add", "origin", str(remote)],
            ["add", "artifacts.jsonl", "events.jsonl"],
            ["commit", "-m", "peer state"],
            ["push", "-u", "origin", "main"],
        ):
            subprocess.run(
                ["git", "-C", str(peer_dir), *c], check=True, capture_output=True
            )
        sync._back()

        # our world dir becomes a repo tracking the same remote
        sync.export_state()  # materializes the dir + snapshot first
        wdir = world._world_dir()
        for c in (
            ["init", "-b", "main"],
            ["config", "user.email", "t@t"],
            ["config", "user.name", "t"],
            ["remote", "add", "origin", str(remote)],
        ):
            subprocess.run(["git", "-C", wdir, *c], check=True, capture_output=True)

        r = sync.sync_git()
        assert r["success"] and r["pushed"], json.dumps(r)
        assert r["artifacts_merged"] == 1
        assert world.get(aid)["success"]

    def test_not_a_git_repo(self, world, sync):
        r = sync.sync_git()
        assert not r["success"] and "not a git repo" in r["error"]


class TestPromptSection:
    def test_renders_policy_and_live_stats(self, world):
        aid = _pipeline(world)["artifact_id"]
        world.record_event(aid, "test", {"metrics": {"tss": 0.7}})
        world.record_event(aid, "install")
        world.validate(aid, {"tss": 0.7}, {"run_id": "r1", "exit_code": 0})
        text = world.prompt_section({})
        assert "world_query" in text and "observe" in text
        assert "world_replay" in text and "world_sync" in text
        assert "1 artifact(s), 1 validated" in text

    def test_empty_world_still_renders(self, world):
        text = world.prompt_section(None)
        assert "0 artifact(s), 0 validated" in text
        assert "## EcoSeek World" in text


class TestWorldTrace:
    """Phoenix span export — fire-and-forget, never blocks world ops."""

    @pytest.fixture()
    def spans(self, monkeypatch):
        captured = []
        import world_trace

        monkeypatch.setattr(
            world_trace, "_post", lambda span: captured.append(span) or True
        )
        yield captured

    def test_event_span_emitted(self, world, spans):
        aid = _pipeline(world)["artifact_id"]
        assert spans, "propose should emit an event span"
        span = spans[-1]
        assert span["name"] == "ecoseek.world.event"
        assert span["status"] == "OK"
        attrs = span["attributes"]
        assert attrs["ecoseek.world.kind"] == "propose"
        assert attrs["ecoseek.world.artifact_id"] == aid
        assert attrs["ecoseek.world.agent"] == "emily"

    def test_replay_span_with_result_attrs(self, world, spans, monkeypatch):
        monkeypatch.setenv("ECOSEEK_WORLD_REPLAY_EXEC", "1")
        aid = world.propose(
            name="noop-pipe",
            artifact_type="pipeline",
            executable={"kind": "shell", "ref": "true"},
        )["artifact_id"]
        world.record_event(aid, "install")
        import world_replay

        rep = world_replay.replay(aid)
        assert rep["success"]
        rspan = [s for s in spans if s["name"] == "ecoseek.world.replay"][-1]
        assert rspan["status"] == "OK"
        assert rspan["attributes"]["ecoseek.world.exit_code"] == 0
        assert rspan["attributes"]["ecoseek.world.run_id"] == rep["run_id"]

    def test_error_status_on_exception(self, world, spans):
        import world_trace

        with pytest.raises(ValueError), world_trace.span("boom"):
            raise ValueError("x")
        assert spans[-1]["status"] == "ERROR"
        assert spans[-1]["name"] == "ecoseek.world.boom"

    def test_disabled_env_suppresses(self, world, monkeypatch):
        import world_trace

        calls = []
        monkeypatch.setattr(world_trace, "_post", lambda s: calls.append(s) or True)
        monkeypatch.setenv("ECOSEEK_WORLD_TRACE", "0")
        _pipeline(world)
        assert calls == []

    def test_endpoint_down_still_works(self, world, monkeypatch):
        # No mock: real urlopen to a closed port must not break world ops.
        monkeypatch.setenv("PHOENIX_ENDPOINT", "http://127.0.0.1:1")
        import world_trace

        monkeypatch.setattr(world_trace, "_ENDPOINT", "http://127.0.0.1:1")
        aid = _pipeline(world)["artifact_id"]
        assert world.get(aid)["success"]

    def test_sync_span(self, world, sync, spans, tmp_path):
        peer = tmp_path / "peer"
        peer.mkdir()
        r = sync.sync(transport="file", peer=str(peer))
        assert r["success"]
        sspan = [s for s in spans if s["name"] == "ecoseek.world.sync"][-1]
        assert sspan["attributes"]["ecoseek.world.transport"] == "file"
        assert sspan["attributes"]["ecoseek.world.success"] is True
