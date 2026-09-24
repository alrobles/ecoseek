"""World federation — sync artifact+event state between instances.

`events.jsonl` + `artifacts.jsonl` are the replication unit (ADR-007).
Sync is pull-driven convergence: each side merges the peer's snapshot into
its SQLite registry and re-exports the union. Merges are deterministic and
idempotent:

- artifacts: content-addressed id; status by precedence
  (retired > validated > installed > tested > proposed); metrics/evidence/
  parents union — never a downgrade.
- events: natural-key dedup (artifact_id+ts+agent+kind+payload) — a line
  arriving via two paths lands once.

Transports:
  file  — another world dir on this filesystem (tests, same-host instances)
  ssh:  — `ssh:user@host:path` — scp pull + push over the mesh
  git   — the world dir is a git repo with a remote; pull→merge→push

Zero LLM, deterministic. Peer DBs converge when each side syncs.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile

try:
    from . import world, world_trace
except ImportError:  # top-level import in tests
    import world
    import world_trace

_STATE_FILES = ("artifacts.jsonl", "events.jsonl")


def _world_dir() -> str:
    return world._world_dir()


def export_state() -> dict:
    """Snapshot the registry to artifacts.jsonl next to events.jsonl."""
    d = _world_dir()
    os.makedirs(d, exist_ok=True)
    with world._connect() as conn:
        rows = conn.execute("SELECT * FROM artifacts ORDER BY id").fetchall()
        artifacts = [world._row_to_artifact(r) for r in rows]
    path = os.path.join(d, "artifacts.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        for a in artifacts:
            a = {k: v for k, v in a.items() if k != "events"}
            fh.write(json.dumps(a, ensure_ascii=False, sort_keys=True) + "\n")
    # a world with zero events still exports an (empty) replication log
    open(os.path.join(d, "events.jsonl"), "a", encoding="utf-8").close()
    return {"success": True, "path": path, "count": len(artifacts)}


def _read_jsonl(path: str) -> list:
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def _write_jsonl(path: str, rows: list) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.writelines(
            json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows
        )


def _merge_event_files(local_path: str, remote_events: list) -> int:
    """Union local events.jsonl with remote events (sorted by ts); returns
    number of new lines added locally."""
    local = _read_jsonl(local_path)
    seen = {json.dumps(e, sort_keys=True) for e in local}
    new = [e for e in remote_events if json.dumps(e, sort_keys=True) not in seen]
    merged = local + new
    merged.sort(key=lambda e: (e.get("ts", 0), e.get("artifact_id", "")))
    if new:
        _write_jsonl(local_path, merged)
    return len(new)


def import_state(state_dir: str) -> dict:
    """Merge artifacts.jsonl + events.jsonl from a directory into this
    world. Idempotent; events for unknown artifacts are skipped."""
    artifacts = _read_jsonl(os.path.join(state_dir, "artifacts.jsonl"))
    events = _read_jsonl(os.path.join(state_dir, "events.jsonl"))

    by_artifact: dict[str, list] = {}
    for ev in events:
        by_artifact.setdefault(ev.get("artifact_id", ""), []).append(ev)

    merged = updated = kept = skipped = 0
    events_inserted = 0
    incoming_ids = {a.get("id") for a in artifacts}
    for art in artifacts:
        aid = art.get("id")
        if not aid:
            skipped += 1
            continue
        r = world.import_artifact(art, events=by_artifact.get(aid))
        if not r.get("success"):
            skipped += 1
            continue
        if r.get("merged"):
            merged += 1
        elif r.get("outcome") == "updated":
            updated += 1
        else:
            kept += 1

    # events for artifacts we already had locally but whose event lines are new
    with world._connect() as conn:
        known = {r["id"] for r in conn.execute("SELECT id FROM artifacts").fetchall()}
        for aid, evs in by_artifact.items():
            if aid in known and aid not in incoming_ids:
                for ev in evs:
                    if world._insert_event_dedup(conn, aid, ev):
                        events_inserted += 1

    # mirror the union into local events.jsonl (replication unit)
    added_lines = _merge_event_files(os.path.join(_world_dir(), "events.jsonl"), events)
    return {
        "success": True,
        "artifacts_merged": merged,
        "artifacts_updated": updated,
        "artifacts_kept": kept,
        "artifacts_skipped": skipped,
        "events_new": events_inserted + added_lines,
    }


def _export_peer_snapshot(peer_dir: str) -> None:
    """Write our merged state into a peer dir (file transport write-back)."""
    export_state()
    for f in _STATE_FILES:
        src = os.path.join(_world_dir(), f)
        if os.path.exists(src):
            shutil.copyfile(src, os.path.join(peer_dir, f))


def sync_file(peer_dir: str) -> dict:
    """Bidirectional merge with another world dir on this filesystem."""
    peer_dir = os.path.expanduser(peer_dir)
    if not os.path.isdir(peer_dir):
        os.makedirs(peer_dir, exist_ok=True)  # bootstrap a fresh replica
    result = import_state(peer_dir)
    _export_peer_snapshot(peer_dir)
    result["peer"] = peer_dir
    result["transport"] = "file"
    return result


def sync_ssh(target: str) -> dict:
    """Sync with a remote world dir over SSH — `user@host:path` or
    `host:path`. Pulls the peer's snapshot via scp, merges locally, pushes
    the union back. Requires working ssh/scp (mesh nodes)."""
    if ":" not in target:
        return {"success": False, "error": "ssh target needs host:path"}
    host, _, remote_dir = target.partition(":")
    remote_dir = remote_dir or "~/.ecoseek/world"
    with tempfile.TemporaryDirectory(prefix="ecoseek-sync-") as tmp:
        scp_pull = ["scp", "-q"]
        for f in _STATE_FILES:
            scp_pull.append(f"{host}:{remote_dir}/{f}")
        scp_pull.append(tmp)
        subprocess.run(
            scp_pull, capture_output=True, text=True, timeout=60, check=False
        )
        pulled = [f for f in _STATE_FILES if os.path.exists(os.path.join(tmp, f))]
        # empty pull = fresh replica (bootstrap) — push-only
        result = (
            import_state(tmp) if pulled else {"artifacts_merged": 0, "events_new": 0}
        )
        result["bootstrapped"] = not pulled
        # ensure remote dir exists, then push the merged snapshot back —
        # peer converges on its next import
        subprocess.run(
            ["ssh", host, "mkdir", "-p", remote_dir],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        export_state()
        push = subprocess.run(
            ["scp", "-q"]
            + [os.path.join(_world_dir(), f) for f in _STATE_FILES]
            + [f"{host}:{remote_dir}/"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        result["pushed"] = push.returncode == 0
        if push.returncode != 0:
            result["push_error"] = (push.stderr or "")[:300]
            result["success"] = False
            result["peer"] = target
            result["transport"] = "ssh"
            return result
    result["peer"] = target
    result["transport"] = "ssh"
    result["success"] = True
    return result


def sync_git(remote: str = "origin", branch: str = "main") -> dict:
    """Git transport — the world dir is a repo; fetch remote state, merge
    into the registry, re-export, commit and push the union."""
    d = _world_dir()

    def git(*args) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", d, *args],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    if not os.path.isdir(os.path.join(d, ".git")):
        return {
            "success": False,
            "error": "world dir is not a git repo",
            "hint": f"git -C {d} init && git -C {d} remote add origin <url>",
        }

    export_state()
    git("add", *list(_STATE_FILES))
    git("commit", "-m", "world: pre-sync snapshot", "--allow-empty")

    fetch = git("fetch", remote, branch)
    remote_ref = f"{remote}/{branch}"
    has_remote = (
        fetch.returncode == 0
        and git("rev-parse", "--verify", remote_ref).returncode == 0
    )

    merge = None
    merged_report = {"artifacts_merged": 0, "events_new": 0}
    if has_remote:
        # 1) join histories on a clean tree — `-X ours` keeps our snapshot;
        #    the data-level union is committed right after
        merge = git(
            "merge",
            "-X",
            "ours",
            "--allow-unrelated-histories",
            "--no-edit",
            remote_ref,
        )
        # 2) merge the remote snapshot into the registry (rewrites
        #    events.jsonl with the union — tree is dirty by design now)
        with tempfile.TemporaryDirectory(prefix="ecoseek-git-") as tmp:
            got_any = False
            for f in _STATE_FILES:
                show = git("show", f"{remote_ref}:{f}")
                if show.returncode == 0 and show.stdout.strip():
                    with open(os.path.join(tmp, f), "w", encoding="utf-8") as fh:
                        fh.write(show.stdout)
                    got_any = True
            if got_any:
                merged_report = import_state(tmp)
        # 3) commit the union snapshot — push then fast-forwards
        export_state()
        git("add", *list(_STATE_FILES))
        git("commit", "-m", "world: federated merge", "--allow-empty")
    push = git("push", remote, f"HEAD:{branch}")
    result = {
        "success": push.returncode == 0,
        "transport": "git",
        "pushed": push.returncode == 0,
        "push_error": "" if push.returncode == 0 else (push.stderr or "")[:300],
        **merged_report,
    }
    if merge is not None and merge.returncode != 0:
        result["merge_error"] = (merge.stderr or merge.stdout or "")[:300]
    if fetch.returncode != 0:
        result["fetch_error"] = (fetch.stderr or "")[:300]
    return result


def sync(peer: str = "", transport: str = "", **kwargs) -> dict:
    """Dispatch: explicit transport, or inferred from the peer string."""
    if not transport:
        if peer.startswith("ssh:") or (":" in peer and "/" not in peer.split(":")[0]):
            transport = "ssh"
        elif peer == "git" or (
            not peer and os.path.isdir(os.path.join(_world_dir(), ".git"))
        ):
            transport = "git"
        else:
            transport = "file"
    with world_trace.span("sync", transport=transport, peer=peer) as attrs:
        if transport == "ssh":
            result = sync_ssh(peer.removeprefix("ssh:"))
        elif transport == "git":
            result = sync_git(
                remote=kwargs.get("remote", "origin"),
                branch=kwargs.get("branch", "main"),
            )
        else:
            result = sync_file(peer)
        attrs["merged"] = result.get("artifacts_merged", 0)
        attrs["success"] = result.get("success", False)
    return result
