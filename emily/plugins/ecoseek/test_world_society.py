"""Society smoke + endpoint metrics for EcoSeek World.

Two-agent scripted scenarios (no LLM) under the three SwarmWorld-style
conditions — shared world, isolated worlds (independent-search control),
and federated worlds (world_sync file transport) — asserting that the
shared substrate produces the stigmergic signature the endpoints measure.

Run with:
    cd emily/plugins/ecoseek && python -m pytest test_world_society.py -v
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import society
import world
import world_metrics


@pytest.fixture()
def society_dir(tmp_path, monkeypatch):
    """Scratch workdir; replays execute (the run's explicit trust decision)."""
    monkeypatch.setenv("ECOSEEK_WORLD_REPLAY_EXEC", "1")
    return str(tmp_path / "soc")


def _close_conn():
    if getattr(world._local, "conn", None) is not None:
        world._local.conn.close()
        world._local.conn = None


@pytest.fixture(autouse=True)
def _cleanup_conn():
    yield
    _close_conn()


class TestSharedSociety:
    def test_shared_world_produces_stigmergic_signature(self, society_dir):
        rep = society.run_society(
            os.path.join(society_dir, "shared"), mode="shared", allow_exec=True
        )
        assert rep["success"], rep
        ep = rep["endpoints"]
        # two validated inventions — alpha's root + beta's derived fork
        assert ep["inventions"]["validated_inventions"] == 2
        assert rep["derived_validated"] == 1
        # executable inheritance happened, across authors
        assert ep["lineage"]["edges"] >= 1
        assert ep["lineage"]["cross_author_forks"] == 1
        assert ep["lineage"]["max_depth"] == 1
        # observation-first reuse: beta observed before forking/testing
        assert ep["reuse"]["observation_first"] >= 1
        assert ep["reuse"]["observation_first_fraction"] > 0
        # frozen replay really ran (both holdouts)
        assert ep["replay_resilience"]["succeeded"] == 2
        assert len(ep["replay_resilience"]["distinct_holdouts"]) == 2
        # methods section registered as provenance artifact
        assert ep["artifacts"]["by_type"].get("methods_section", 0) == 1
        # both agents active in the same world
        assert set(ep["agents"]) >= {"alpha", "beta"}

    def test_all_steps_ok(self, society_dir):
        rep = society.run_society(
            os.path.join(society_dir, "shared2"), mode="shared", allow_exec=True
        )
        failed = [s for s in rep["steps"] if not s["ok"]]
        assert not failed, failed


class TestIsolatedControl:
    def test_isolated_worlds_show_no_collective_signature(self, society_dir):
        """Same work, disconnected worlds: same validated count, but zero
        reuse, zero lineage, zero derived validation — the control condition
        shows the endpoints discriminate substrate vs no-substrate."""
        rep = society.run_society(
            os.path.join(society_dir, "iso"), mode="isolated", allow_exec=True
        )
        assert rep["success"], rep
        union = rep["endpoints"]["union"]
        # both agents still validated their own pipeline (equal work output)
        assert union["validated_inventions"] == 2
        assert union["artifacts"] == 2
        # but nothing was shared: no lineage, no reuse, no observation
        assert union["lineage_edges"] == 0
        assert union["reuse_events"] == 0
        assert union["observation_first"] == 0
        assert rep["derived_validated"] == 0
        # beta's query in an empty world — the miss that forces re-derivation
        q = next(s for s in rep["steps"] if s["step"] == "beta:world_query")
        assert "count=0" in q["detail"]


class TestFederatedSociety:
    def test_federated_converges_to_shared_signature(self, society_dir):
        """Two world dirs + world_sync file transport: beta inherits alpha's
        validated artifact across the replication boundary, and the merged
        world shows the same signature as the shared condition."""
        rep = society.run_society(
            os.path.join(society_dir, "fed"), mode="federated", allow_exec=True
        )
        assert rep["success"], rep
        ep = rep["endpoints"]
        assert ep["inventions"]["validated_inventions"] == 2
        assert rep["derived_validated"] == 1
        assert ep["lineage"]["cross_author_forks"] == 1
        assert ep["reuse"]["observation_first"] >= 1
        # sync steps actually transferred state both ways
        s1 = next(s for s in rep["steps"] if s["step"] == "beta:sync<-alpha")
        s2 = next(s for s in rep["steps"] if s["step"] == "alpha:sync<-beta")
        assert s1["ok"] and s1["detail"]["merged"] >= 1
        assert s2["ok"]


class TestEndpointsModule:
    def test_empty_world_is_honest_zero(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ECOSEEK_WORLD_DIR", str(tmp_path / "empty"))
        _close_conn()
        ep = world_metrics.swarm_endpoints()
        assert ep["success"] and ep["artifacts"]["total"] == 0
        assert ep["inventions"]["validated_inventions"] == 0
        assert ep["replay_resilience"]["runs"] == 0

    def test_endpoint_series_tracks_growth(self, society_dir):
        society.run_society(
            os.path.join(society_dir, "ser"), mode="shared", allow_exec=True
        )
        ser = world_metrics.endpoint_series(points=5)
        assert ser["points"] >= 2
        vals = [s["validated_inventions"] for s in ser["series"]]
        assert vals[0] == 0 and vals[-1] == 2
        assert vals == sorted(vals)  # monotonic accumulation

    def test_series_on_empty_world(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ECOSEEK_WORLD_DIR", str(tmp_path / "e2"))
        _close_conn()
        ser = world_metrics.endpoint_series()
        assert ser["success"] and ser["series"] == []


class TestComparison:
    def test_compare_table_deltas(self, society_dir):
        reports = {}
        for mode in ("shared", "isolated"):
            reports[mode] = society.run_society(
                os.path.join(society_dir, f"cmp-{mode}"),
                mode=mode,
                allow_exec=True,
            )
        comp = society._compare(reports)
        sh, iso = comp["shared"], comp["isolated"]
        assert sh["validated_inventions"] == iso["validated_inventions"] == 2
        # the measurable advantage is structural, not in count
        assert sh["derived_validated"] > iso["derived_validated"]
        assert sh["observation_first_fraction"] > 0
        assert iso["observation_first"] == 0
        assert sh["replay_success_rate"] == 1.0
