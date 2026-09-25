"""EcoSeek World — persistent artifact substrate (SwarmWorld-aligned).

One SQLite registry + append-only JSONL event log shared by every agent that
runs this plugin (Emily local, Hermes remote, or any hermes-agent instance).
Artifacts are content-addressed, typed, executable-capable objects that outlive
the session that created them — the "world" agents modify and later agents
encounter (stigmergy).

Event vocabulary (recorded, never inferred):
  propose → test → install → observe | fork | repair | dismantle | attest | validate

Status is derived from events:  proposed → tested → installed → validated,
or → retired (dismantle).  The ``validate`` event is the two-gate promotion:
it REQUIRES an ``installed`` artifact plus replay evidence — a run of the
frozen artifact on held-out inputs with zero LLM in the loop (agent-free
evaluation).  ``attest`` records advisory LLM-judge scores; it can flag but
never promotes.

Env vars:
  ECOSEEK_WORLD_DIR   - registry dir (default: ~/.ecoseek/world)
  ECOSEEK_WORLD_DB    - SQLite filename (default: world.db)
  ECOSEEK_AGENT_ID    - identity recorded on events (default: "emily")

Federation: events.jsonl is the replication unit — export/import or commit it
to git to share world state between instances.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager

logger = logging.getLogger(__name__)

_EVENT_KINDS = (
    "propose",
    "test",
    "install",
    "observe",
    "fork",
    "repair",
    "dismantle",
    "attest",
    "validate",
)

_ARTIFACT_TYPES = (
    "pipeline",
    "model",
    "script",
    "dataset_pin",
    "methods_section",
    "report",
    "other",
)

_STATUSES = ("proposed", "tested", "installed", "validated", "retired")

_local = threading.local()


def _world_dir() -> str:
    return os.environ.get(
        "ECOSEEK_WORLD_DIR", os.path.join(os.path.expanduser("~"), ".ecoseek", "world")
    )


def _db_path() -> str:
    return os.path.join(_world_dir(), os.environ.get("ECOSEEK_WORLD_DB", "world.db"))


def _agent_id() -> str:
    return os.environ.get("ECOSEEK_AGENT_ID", "emily")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS artifacts (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    type        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'proposed',
    summary     TEXT DEFAULT '',
    spec        TEXT DEFAULT '{}',
    executable  TEXT DEFAULT '{}',
    parents     TEXT DEFAULT '[]',
    evidence    TEXT DEFAULT '[]',
    metrics     TEXT DEFAULT '{}',
    author      TEXT DEFAULT 'unknown',
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL NOT NULL,
    artifact_id TEXT NOT NULL,
    agent       TEXT NOT NULL,
    kind        TEXT NOT NULL,
    payload     TEXT DEFAULT '{}',
    task_id     TEXT DEFAULT '',
    FOREIGN KEY (artifact_id) REFERENCES artifacts(id)
);
CREATE INDEX IF NOT EXISTS idx_events_artifact ON events(artifact_id);
CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind);
CREATE VIRTUAL TABLE IF NOT EXISTS world_fts USING fts5(
    artifact_id UNINDEXED, name, summary, spec, evidence
);
"""


@contextmanager
def _connect():
    os.makedirs(_world_dir(), exist_ok=True)
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(_db_path())
        _local.conn.row_factory = sqlite3.Row
        _local.conn.executescript(_SCHEMA)
    try:
        yield _local.conn
        _local.conn.commit()
    except Exception:
        _local.conn.rollback()
        raise


# ---------------------------------------------------------------------------
# Event log (JSONL — the federation/replication unit)
# ---------------------------------------------------------------------------


def _append_jsonl(event: dict) -> None:
    try:
        path = os.path.join(_world_dir(), "events.jsonl")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError as exc:
        logger.warning("world: could not append events.jsonl: %s", exc)


def _emit(
    conn,
    artifact_id: str,
    kind: str,
    payload: dict | None = None,
    agent: str | None = None,
    task_id: str = "",
) -> dict:
    if kind not in _EVENT_KINDS:
        raise ValueError(f"unknown event kind {kind!r}; allowed: {_EVENT_KINDS}")
    event = {
        "ts": time.time(),
        "artifact_id": artifact_id,
        "agent": agent or _agent_id(),
        "kind": kind,
        "payload": payload or {},
        "task_id": task_id,
    }
    conn.execute(
        "INSERT INTO events (ts, artifact_id, agent, kind, payload, task_id)"
        " VALUES (?,?,?,?,?,?)",
        (
            event["ts"],
            artifact_id,
            event["agent"],
            kind,
            json.dumps(event["payload"], ensure_ascii=False),
            task_id,
        ),
    )
    _append_jsonl(event)
    return event


# ---------------------------------------------------------------------------
# Artifact identity + status machine
# ---------------------------------------------------------------------------


def _artifact_id(
    name: str, type_: str, spec: dict, executable: dict, evidence: list
) -> str:
    """Content-addressed id — same canonical content ⇒ same id (novelty gate)."""
    canon = json.dumps(
        {
            "name": name,
            "type": type_,
            "spec": spec,
            "executable": executable,
            "evidence": sorted(str(e) for e in evidence),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def _apply_transition(
    conn, artifact_id: str, kind: str, payload: dict, agent: str
) -> str:
    """Update artifacts.status from an event. Returns the new status."""
    row = conn.execute(
        "SELECT status FROM artifacts WHERE id = ?", (artifact_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"artifact {artifact_id} not found")
    status = row["status"]

    new = status
    if kind == "test":
        if status not in ("proposed", "tested"):
            raise ValueError(f"cannot test artifact in status {status}")
        new = "tested"
        if payload.get("metrics"):
            conn.execute(
                "UPDATE artifacts SET metrics = ? WHERE id = ?",
                (json.dumps(payload["metrics"], ensure_ascii=False), artifact_id),
            )
    elif kind == "install":
        if status != "tested":
            raise ValueError(
                f"cannot install artifact in status {status} (need tested)"
            )
        new = "installed"
    elif kind == "validate":
        if status != "installed":
            raise ValueError(
                f"cannot validate artifact in status {status} (need installed)"
            )
        metrics = payload.get("metrics") or {}
        replay = payload.get("replay") or {}
        if not metrics:
            raise ValueError(
                "validate requires non-empty metrics (measured, not claimed)"
            )
        if not replay.get("run_id") or replay.get("exit_code") != 0:
            raise ValueError(
                "validate requires replay evidence: {run_id, exit_code: 0, holdout}"
            )
        new = "validated"
    elif kind == "dismantle":
        new = "retired"
    # propose/observe/fork/repair/attest leave status unchanged

    if new != status:
        conn.execute(
            "UPDATE artifacts SET status = ?, updated_at = ? WHERE id = ?",
            (new, time.time(), artifact_id),
        )
    return new


def _row_to_artifact(row: sqlite3.Row) -> dict:
    d = dict(row)
    for key in ("spec", "executable", "metrics"):
        d[key] = json.loads(d.get(key) or "{}")
    for key in ("parents", "evidence"):
        d[key] = json.loads(d.get(key) or "[]")
    return d


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------


def propose(
    name: str,
    artifact_type: str = "other",
    summary: str = "",
    spec: dict | None = None,
    executable: dict | None = None,
    evidence: list | None = None,
    author: str | None = None,
    task_id: str = "",
) -> dict:
    """Register a new artifact (status=proposed) and emit a propose event."""
    if artifact_type not in _ARTIFACT_TYPES:
        return {
            "success": False,
            "error": f"invalid type {artifact_type!r}",
            "allowed": list(_ARTIFACT_TYPES),
        }
    spec = spec or {}
    executable = executable or {}
    evidence = evidence or []
    aid = _artifact_id(name, artifact_type, spec, executable, evidence)
    now = time.time()

    with _connect() as conn:
        existing = conn.execute(
            "SELECT id, status FROM artifacts WHERE id = ?", (aid,)
        ).fetchone()
        if existing:
            return {
                "success": False,
                "error": "already_registered",
                "artifact_id": aid,
                "status": existing["status"],
                "message": (
                    "Identical content already registered — this fails the "
                    "novelty gate. Fork it (world_fork) to create a descendant."
                ),
            }
        conn.execute(
            "INSERT INTO artifacts"
            " (id, name, type, status, summary, spec, executable, parents,"
            "  evidence, author, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                aid,
                name,
                artifact_type,
                "proposed",
                summary,
                json.dumps(spec, ensure_ascii=False),
                json.dumps(executable, ensure_ascii=False),
                "[]",
                json.dumps(evidence, ensure_ascii=False),
                author or _agent_id(),
                now,
                now,
            ),
        )
        conn.execute(
            "INSERT INTO world_fts (artifact_id, name, summary, spec, evidence)"
            " VALUES (?,?,?,?,?)",
            (
                aid,
                name,
                summary,
                json.dumps(spec, ensure_ascii=False),
                " ".join(str(e) for e in evidence),
            ),
        )
        _emit(
            conn, aid, "propose", {"name": name, "type": artifact_type}, author, task_id
        )

    return {"success": True, "artifact_id": aid, "status": "proposed"}


def record_event(
    artifact_id: str,
    kind: str,
    payload: dict | None = None,
    agent: str | None = None,
    task_id: str = "",
) -> dict:
    """Append an event to an artifact's history and apply the status machine."""
    payload = payload or {}
    with _connect() as conn:
        try:
            new_status = _apply_transition(
                conn, artifact_id, kind, payload, agent or _agent_id()
            )
        except (KeyError, ValueError) as exc:
            return {"success": False, "error": str(exc)}
        _emit(conn, artifact_id, kind, payload, agent, task_id)
    return {"success": True, "artifact_id": artifact_id, "status": new_status}


def validate(
    artifact_id: str,
    metrics: dict,
    replay: dict,
    agent: str | None = None,
    task_id: str = "",
) -> dict:
    """Two-gate promotion: installed artifact + measured metrics + agent-free
    replay evidence (run_id, exit_code=0, holdout spec) → status=validated."""
    return record_event(
        artifact_id,
        "validate",
        {"metrics": metrics, "replay": replay},
        agent,
        task_id,
    )


def fork(
    artifact_id: str,
    agent: str | None = None,
    edits: dict | None = None,
    task_id: str = "",
) -> dict:
    """Create a child artifact inheriting the parent's content (executable
    inheritance). Records parents=[parent_id] and a fork event on both."""
    edits = edits or {}
    with _connect() as conn:
        parent = conn.execute(
            "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
        if parent is None:
            return {"success": False, "error": f"artifact {artifact_id} not found"}
        p = _row_to_artifact(parent)

    child = propose(
        name=edits.get("name", f"{p['name']}-fork"),
        artifact_type=edits.get("type", p["type"]),
        summary=edits.get("summary", p["summary"]),
        spec=edits.get("spec", p["spec"]),
        executable=edits.get("executable", p["executable"]),
        evidence=edits.get("evidence", p["evidence"]),
        author=agent,
        task_id=task_id,
    )
    if not child.get("success"):
        return child

    child_id = child["artifact_id"]
    with _connect() as conn:
        conn.execute(
            "UPDATE artifacts SET parents = ? WHERE id = ?",
            (json.dumps([artifact_id]), child_id),
        )
        _emit(
            conn,
            child_id,
            "fork",
            {"parent": artifact_id, "edits": sorted(edits.keys())},
            agent,
            task_id,
        )
        _emit(
            conn,
            artifact_id,
            "fork",
            {"child": child_id, "direction": "parent"},
            agent,
            task_id,
        )
    return {"success": True, "artifact_id": child_id, "parent": artifact_id}


def observe(artifact_id: str, agent: str | None = None, task_id: str = "") -> dict:
    """Record that an agent encountered/used an artifact (stigmergic reuse —
    the ~95% observation-first diffusion channel from SwarmWorld)."""
    return record_event(artifact_id, "observe", {}, agent, task_id)


def get(artifact_id: str, include_events: bool = True) -> dict:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
        if row is None:
            return {"success": False, "error": f"artifact {artifact_id} not found"}
        artifact = _row_to_artifact(row)
        if include_events:
            events = conn.execute(
                "SELECT ts, agent, kind, payload, task_id FROM events"
                " WHERE artifact_id = ? ORDER BY seq",
                (artifact_id,),
            ).fetchall()
            artifact["events"] = [
                {
                    "ts": e["ts"],
                    "agent": e["agent"],
                    "kind": e["kind"],
                    "payload": json.loads(e["payload"] or "{}"),
                    "task_id": e["task_id"],
                }
                for e in events
            ]
    return {"success": True, "artifact": artifact}


def query(
    text: str = "",
    artifact_type: str = "",
    status: str = "",
    author: str = "",
    limit: int = 10,
) -> dict:
    """Stigmergic lookup — 'what validated artifacts match this task?'
    FTS5 over name/summary/spec/evidence, plus structured filters."""
    with _connect() as conn:
        where, params = [], []
        if artifact_type:
            where.append("a.type = ?")
            params.append(artifact_type)
        if status:
            where.append("a.status = ?")
            params.append(status)
        if author:
            where.append("a.author = ?")
            params.append(author)

        rows = []
        if text:
            try:
                sql = (
                    "SELECT a.* FROM artifacts a"
                    " JOIN world_fts f ON f.artifact_id = a.id"
                    " WHERE world_fts MATCH ?"
                )
                if where:
                    sql += " AND " + " AND ".join(where)
                sql += " ORDER BY rank LIMIT ?"
                rows = conn.execute(sql, [text, *params, limit]).fetchall()
            except sqlite3.OperationalError:
                # bad FTS syntax → fall back to LIKE
                like = f"%{text}%"
                sql = (
                    "SELECT a.* FROM artifacts a WHERE"
                    " (a.name LIKE ? OR a.summary LIKE ? OR a.spec LIKE ?)"
                )
                if where:
                    sql += " AND " + " AND ".join(where)
                sql += " ORDER BY a.updated_at DESC LIMIT ?"
                rows = conn.execute(sql, [like, like, like, *params, limit]).fetchall()
        else:
            sql = "SELECT a.* FROM artifacts a"
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY a.updated_at DESC LIMIT ?"
            rows = conn.execute(sql, [*params, limit]).fetchall()

    return {
        "success": True,
        "count": len(rows),
        "artifacts": [_row_to_artifact(r) for r in rows],
    }


def lineage(artifact_id: str) -> dict:
    """Ancestors (walking parents) + direct descendants — executable
    inheritance graph, recorded edges only."""
    with _connect() as conn:
        if (
            conn.execute(
                "SELECT 1 FROM artifacts WHERE id = ?", (artifact_id,)
            ).fetchone()
            is None
        ):
            return {"success": False, "error": f"artifact {artifact_id} not found"}

        ancestors, seen, queue = [], set(), [artifact_id]
        while queue:
            cur = queue.pop(0)
            row = conn.execute(
                "SELECT id, name, type, status, author, parents"
                " FROM artifacts WHERE id = ?",
                (cur,),
            ).fetchone()
            if row is None:
                continue
            for pid in json.loads(row["parents"] or "[]"):
                if pid not in seen:
                    seen.add(pid)
                    queue.append(pid)
                    prow = conn.execute(
                        "SELECT id, name, type, status, author"
                        " FROM artifacts WHERE id = ?",
                        (pid,),
                    ).fetchone()
                    if prow:
                        ancestors.append(dict(prow))

        descendants = [
            dict(r)
            for r in conn.execute(
                "SELECT id, name, type, status, author FROM artifacts"
                " WHERE parents LIKE ?",
                (f'%"{artifact_id}"%',),
            ).fetchall()
        ]
    return {
        "success": True,
        "artifact_id": artifact_id,
        "ancestors": ancestors,
        "descendants": descendants,
        "depth": len(ancestors),
    }


def stats() -> dict:
    """Portfolio-level endpoints à la SwarmWorld: breadth, validated
    inventions, lineage depth, observation-first reuse fraction."""
    with _connect() as conn:
        by_status = {
            r["status"]: r["n"]
            for r in conn.execute(
                "SELECT status, COUNT(*) n FROM artifacts GROUP BY status"
            )
        }
        by_type = {
            r["type"]: r["n"]
            for r in conn.execute(
                "SELECT type, COUNT(*) n FROM artifacts GROUP BY type"
            )
        }
        total = sum(by_status.values())
        # max lineage depth via recursive walk of parents
        depths = []
        for r in conn.execute("SELECT id, parents FROM artifacts").fetchall():
            d, seen, queue = 0, set(), [r["id"]]
            while queue:
                cur = queue.pop(0)
                prow = conn.execute(
                    "SELECT parents FROM artifacts WHERE id = ?", (cur,)
                ).fetchone()
                nexts = []
                if prow:
                    nexts = [
                        p for p in json.loads(prow["parents"] or "[]") if p not in seen
                    ]
                if nexts:
                    d += 1
                    seen.update(nexts)
                    queue.extend(nexts)
            depths.append(d)
        # observation-first reuse: artifacts with ≥1 observe event from a
        # non-author agent
        reused = conn.execute(
            "SELECT COUNT(DISTINCT e.artifact_id) n FROM events e"
            " JOIN artifacts a ON a.id = e.artifact_id"
            " WHERE e.kind = 'observe' AND e.agent != a.author"
        ).fetchone()["n"]
        event_counts = {
            r["kind"]: r["n"]
            for r in conn.execute("SELECT kind, COUNT(*) n FROM events GROUP BY kind")
        }
    return {
        "success": True,
        "total_artifacts": total,
        "by_status": by_status,
        "by_type": by_type,
        "validated_inventions": by_status.get("validated", 0),
        "max_lineage_depth": max(depths, default=0),
        "cross_agent_reused": reused,
        "reuse_fraction": (reused / total) if total else 0.0,
        "events": event_counts,
        "world_dir": _world_dir(),
        "agent_id": _agent_id(),
    }


# ---------------------------------------------------------------------------
# Federation: events.jsonl export/import (the replication unit)
# ---------------------------------------------------------------------------


def export_events() -> dict:
    path = os.path.join(_world_dir(), "events.jsonl")
    if not os.path.exists(path):
        return {"success": True, "events": [], "path": path}
    with open(path, encoding="utf-8") as fh:
        events = [json.loads(line) for line in fh if line.strip()]
    return {"success": True, "events": events, "path": path}


def import_artifact(artifact: dict, events: list | None = None) -> dict:
    """Merge a remote artifact (+ optional events) into this world.
    Artifacts are content-addressed: re-import is idempotent."""
    aid = artifact.get("id")
    if not aid:
        return {"success": False, "error": "artifact missing id"}
    with _connect() as conn:
        exists = conn.execute("SELECT 1 FROM artifacts WHERE id = ?", (aid,)).fetchone()
        if exists:
            return {"success": True, "artifact_id": aid, "merged": False}
        conn.execute(
            "INSERT INTO artifacts"
            " (id, name, type, status, summary, spec, executable, parents,"
            "  evidence, metrics, author, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                aid,
                artifact.get("name", ""),
                artifact.get("type", "other"),
                artifact.get("status", "proposed"),
                artifact.get("summary", ""),
                json.dumps(artifact.get("spec") or {}, ensure_ascii=False),
                json.dumps(artifact.get("executable") or {}, ensure_ascii=False),
                json.dumps(artifact.get("parents") or [], ensure_ascii=False),
                json.dumps(artifact.get("evidence") or [], ensure_ascii=False),
                json.dumps(artifact.get("metrics") or {}, ensure_ascii=False),
                artifact.get("author", "unknown"),
                artifact.get("created_at", time.time()),
                artifact.get("updated_at", time.time()),
            ),
        )
        conn.execute(
            "INSERT INTO world_fts (artifact_id, name, summary, spec, evidence)"
            " VALUES (?,?,?,?,?)",
            (
                aid,
                artifact.get("name", ""),
                artifact.get("summary", ""),
                json.dumps(artifact.get("spec") or {}, ensure_ascii=False),
                " ".join(str(e) for e in (artifact.get("evidence") or [])),
            ),
        )
        for ev in events or []:
            conn.execute(
                "INSERT INTO events (ts, artifact_id, agent, kind, payload, task_id)"
                " VALUES (?,?,?,?,?,?)",
                (
                    ev.get("ts", time.time()),
                    aid,
                    ev.get("agent", "remote"),
                    ev.get("kind", "propose"),
                    json.dumps(ev.get("payload") or {}, ensure_ascii=False),
                    ev.get("task_id", ""),
                ),
            )
    return {"success": True, "artifact_id": aid, "merged": True}
