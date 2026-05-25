"""DiDAL Memory — persistent episodic/semantic/procedural memory with SQLite.

Memory classes (from DiDAL Protocol spec):
  - Episodic:   Previous sessions, user intent, prior clarifications.
  - Semantic:   Stable ecological concepts, known source preferences, recurring
                definitions.
  - Procedural: Successful answer strategies, retrieval policies, report
                templates, classifier behaviors.

Writeback policy — only write when:
  - User confirms answer was useful.
  - Judge score exceeds threshold.
  - Repeated task pattern detected.
  - New stable concept-summary pair generated.

All reads/writes are auditable via Phoenix trace spans.
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
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_MEMORY_DIR = os.environ.get(
    "DIDAL_MEMORY_DIR",
    os.path.join(os.path.expanduser("~"), ".hermes", "didal_memory"),
)
_MEMORY_ENABLED = os.environ.get("DIDAL_MEMORY_ENABLED", "true").lower() in (
    "1", "true", "yes",
)
_MEMORY_MAX_RESULTS = int(os.environ.get("DIDAL_MEMORY_MAX_RESULTS", "5"))
_WRITEBACK_SCORE_THRESHOLD = float(
    os.environ.get("DIDAL_WRITEBACK_SCORE_THRESHOLD", "0.6")
)

# Thread-local DB connections (SQLite is not thread-safe by default)
_local = threading.local()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id          TEXT PRIMARY KEY,
    class       TEXT NOT NULL CHECK (class IN ('episodic', 'semantic', 'procedural')),
    key         TEXT NOT NULL,
    content     TEXT NOT NULL,
    metadata    TEXT DEFAULT '{}',
    score       REAL DEFAULT 0.0,
    access_count INTEGER DEFAULT 0,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    protocol_id TEXT,
    trace_id    TEXT
);

CREATE INDEX IF NOT EXISTS idx_memories_class ON memories(class);
CREATE INDEX IF NOT EXISTS idx_memories_key ON memories(key);
CREATE INDEX IF NOT EXISTS idx_memories_score ON memories(score DESC);

-- FTS5 for semantic search over memory content
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    key, content, class,
    content=memories,
    content_rowid=rowid
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, key, content, class)
    VALUES (new.rowid, new.key, new.content, new.class);
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, key, content, class)
    VALUES ('delete', old.rowid, old.key, old.content, old.class);
END;

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, key, content, class)
    VALUES ('delete', old.rowid, old.key, old.content, old.class);
    INSERT INTO memories_fts(rowid, key, content, class)
    VALUES (new.rowid, new.key, new.content, new.class);
END;

-- Policy evolution: track fitness signals per protocol run
CREATE TABLE IF NOT EXISTS policy_signals (
    id            TEXT PRIMARY KEY,
    protocol_id   TEXT NOT NULL,
    trace_id      TEXT,
    mode          TEXT,
    judge_score   REAL,
    evidence_quality REAL,
    report_quality   REAL,
    clarification_quality REAL,
    latency_s     REAL,
    rounds        INTEGER,
    sources_used  INTEGER,
    fitness       REAL,
    metadata      TEXT DEFAULT '{}',
    created_at    REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_policy_protocol ON policy_signals(protocol_id);
CREATE INDEX IF NOT EXISTS idx_policy_fitness ON policy_signals(fitness DESC);
CREATE INDEX IF NOT EXISTS idx_policy_mode ON policy_signals(mode);
"""


# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------

def _get_db() -> sqlite3.Connection:
    """Get or create a thread-local SQLite connection."""
    db = getattr(_local, "db", None)
    if db is not None:
        return db

    os.makedirs(_MEMORY_DIR, exist_ok=True)
    db_path = os.path.join(_MEMORY_DIR, "didal_memory.db")
    db = sqlite3.connect(db_path, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(_SCHEMA)
    _local.db = db
    logger.debug("Opened memory DB: %s", db_path)
    return db


def is_memory_enabled() -> bool:
    """Return True when memory is configured and enabled."""
    return _MEMORY_ENABLED


# ---------------------------------------------------------------------------
# Memory ID helpers
# ---------------------------------------------------------------------------

def _memory_id(mem_class: str, key: str) -> str:
    """Deterministic ID for upsert semantics."""
    raw = f"{mem_class}:{key}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _signal_id(protocol_id: str) -> str:
    return hashlib.sha256(f"signal:{protocol_id}".encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------

def recall(
    query: str,
    mem_class: Optional[str] = None,
    max_results: int = 0,
) -> list[dict]:
    """Search memory using FTS5 full-text search.

    Parameters
    ----------
    query : str
        Natural-language search query.
    mem_class : str, optional
        Filter to a specific memory class ('episodic', 'semantic', 'procedural').
    max_results : int, optional
        Max results to return (default: DIDAL_MEMORY_MAX_RESULTS env).

    Returns
    -------
    list[dict]
        Matching memory entries, sorted by relevance.
    """
    if not _MEMORY_ENABLED:
        return []

    limit = max_results if max_results > 0 else _MEMORY_MAX_RESULTS

    try:
        db = _get_db()

        # Build FTS query — escape special chars
        fts_query = " ".join(
            w for w in query.split() if len(w) > 1
        )
        if not fts_query:
            return []

        if mem_class:
            rows = db.execute(
                """
                SELECT m.*, rank
                FROM memories_fts fts
                JOIN memories m ON m.rowid = fts.rowid
                WHERE memories_fts MATCH ? AND m.class = ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_query, mem_class, limit),
            ).fetchall()
        else:
            rows = db.execute(
                """
                SELECT m.*, rank
                FROM memories_fts fts
                JOIN memories m ON m.rowid = fts.rowid
                WHERE memories_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()

        results = []
        for row in rows:
            # Increment access count
            db.execute(
                "UPDATE memories SET access_count = access_count + 1 WHERE id = ?",
                (row["id"],),
            )
            results.append({
                "id": row["id"],
                "class": row["class"],
                "key": row["key"],
                "content": row["content"],
                "metadata": json.loads(row["metadata"] or "{}"),
                "score": row["score"],
                "access_count": row["access_count"] + 1,
            })
        db.commit()
        return results

    except Exception as exc:
        logger.warning("Memory recall failed: %s", exc)
        return []


def recall_by_class(mem_class: str, limit: int = 10) -> list[dict]:
    """Get recent memories by class, ordered by score and recency."""
    if not _MEMORY_ENABLED:
        return []

    try:
        db = _get_db()
        rows = db.execute(
            """
            SELECT * FROM memories
            WHERE class = ?
            ORDER BY score DESC, updated_at DESC
            LIMIT ?
            """,
            (mem_class, limit),
        ).fetchall()

        return [
            {
                "id": row["id"],
                "class": row["class"],
                "key": row["key"],
                "content": row["content"],
                "metadata": json.loads(row["metadata"] or "{}"),
                "score": row["score"],
            }
            for row in rows
        ]
    except Exception as exc:
        logger.warning("Memory recall_by_class failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------

def memorize(
    mem_class: str,
    key: str,
    content: str,
    score: float = 0.0,
    metadata: Optional[dict] = None,
    protocol_id: str = "",
    trace_id: str = "",
) -> Optional[str]:
    """Write a memory entry (upsert — updates if same class+key exists).

    Parameters
    ----------
    mem_class : str
        'episodic', 'semantic', or 'procedural'.
    key : str
        Short descriptive key (e.g. "niche_concept", "sdm_pipeline_strategy").
    content : str
        The memory content to store.
    score : float
        Quality/relevance score (0-1). Higher = more likely to be recalled.
    metadata : dict, optional
        Arbitrary metadata (mode, sources, protocol_id, etc.).
    protocol_id : str, optional
        Protocol run that generated this memory.
    trace_id : str, optional
        Phoenix trace ID for audit.

    Returns
    -------
    str or None
        The memory ID, or None if write failed.
    """
    if not _MEMORY_ENABLED:
        return None

    if mem_class not in ("episodic", "semantic", "procedural"):
        logger.warning("Invalid memory class: %s", mem_class)
        return None

    mid = _memory_id(mem_class, key)
    now = time.time()
    meta_json = json.dumps(metadata or {})

    try:
        db = _get_db()
        db.execute(
            """
            INSERT INTO memories (id, class, key, content, metadata, score,
                                  access_count, created_at, updated_at,
                                  protocol_id, trace_id)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                content = excluded.content,
                metadata = excluded.metadata,
                score = MAX(memories.score, excluded.score),
                updated_at = excluded.updated_at,
                protocol_id = excluded.protocol_id,
                trace_id = excluded.trace_id
            """,
            (mid, mem_class, key, content, meta_json, score,
             now, now, protocol_id, trace_id),
        )
        db.commit()
        logger.debug("memorize[%s] %s/%s score=%.2f", mid, mem_class, key, score)
        return mid

    except Exception as exc:
        logger.warning("Memory write failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Writeback policy helpers
# ---------------------------------------------------------------------------

def should_write(
    judge_score: float = 0.0,
    user_confirmed: bool = False,
    repeated_pattern: bool = False,
    new_concept: bool = False,
) -> bool:
    """Decide whether to persist a memory based on writeback policy.

    Write memory only when at least one condition is true:
      - User confirms the answer was useful.
      - Judge score exceeds threshold.
      - Repeated task pattern detected.
      - New stable concept-summary pair generated.
    """
    if not _MEMORY_ENABLED:
        return False

    if user_confirmed:
        return True
    if judge_score >= _WRITEBACK_SCORE_THRESHOLD:
        return True
    if repeated_pattern:
        return True
    if new_concept:
        return True

    return False


def extract_memories_from_protocol(
    protocol_result: dict,
    judge_score: float = 0.0,
) -> list[dict]:
    """Extract candidate memories from a completed protocol run.

    Returns a list of {class, key, content, score, metadata} dicts
    that can be passed to memorize() if writeback policy allows.
    """
    memories = []
    protocol_id = protocol_result.get("protocol_id", "")
    mode = protocol_result.get("mode", "unknown")
    classification = protocol_result.get("classification", {})
    prompt = classification.get("original_prompt", "")

    # Episodic: record what the user asked and what mode was used
    if prompt:
        prompt_key = hashlib.sha256(prompt.encode()).hexdigest()[:12]
        memories.append({
            "class": "episodic",
            "key": f"session_{prompt_key}",
            "content": json.dumps({
                "prompt": prompt[:500],
                "mode": mode,
                "complexity_score": classification.get("complexity_score", 0),
                "elapsed_seconds": protocol_result.get("elapsed_seconds", 0),
                "critique_rounds": protocol_result.get("critique_rounds", 0),
            }, ensure_ascii=False),
            "score": min(judge_score, 1.0),
            "metadata": {"mode": mode, "protocol_id": protocol_id},
        })

    # Semantic: extract stable concepts from the draft
    draft = protocol_result.get("final_draft", {})
    if isinstance(draft, dict):
        thesis = draft.get("thesis", "")
        if thesis and len(thesis) > 50:
            task_type = protocol_result.get("task_object", {}).get("task_type", "unknown")
            concept_key = f"concept_{task_type}_{hashlib.sha256(thesis[:100].encode()).hexdigest()[:8]}"
            memories.append({
                "class": "semantic",
                "key": concept_key,
                "content": json.dumps({
                    "thesis": thesis[:1000],
                    "key_points": draft.get("key_points", [])[:5],
                    "uncertainties": draft.get("uncertainties", [])[:3],
                }, ensure_ascii=False),
                "score": min(judge_score * 0.9, 1.0),
                "metadata": {"task_type": task_type, "mode": mode},
            })

    # Procedural: record what strategy worked
    if mode in ("didal", "didal_literature"):
        rounds = protocol_result.get("critique_rounds", 0)
        n_sources = 0
        evidence = protocol_result.get("evidence", {})
        if isinstance(evidence, dict):
            n_sources = len(evidence.get("sources", []))

        memories.append({
            "class": "procedural",
            "key": f"strategy_{mode}",
            "content": json.dumps({
                "mode": mode,
                "avg_rounds": rounds,
                "avg_sources": n_sources,
                "complexity_score": classification.get("complexity_score", 0),
            }, ensure_ascii=False),
            "score": min(judge_score * 0.8, 1.0),
            "metadata": {"mode": mode},
        })

    return memories


# ---------------------------------------------------------------------------
# Policy signals — fitness tracking for evolution
# ---------------------------------------------------------------------------

def record_policy_signal(
    protocol_id: str,
    mode: str,
    judge_score: float = 0.0,
    evidence_quality: float = 0.0,
    report_quality: float = 0.0,
    clarification_quality: float = 0.0,
    latency_s: float = 0.0,
    rounds: int = 0,
    sources_used: int = 0,
    trace_id: str = "",
    metadata: Optional[dict] = None,
) -> Optional[float]:
    """Record a fitness signal for a protocol run and return the fitness score.

    Fitness formula (from DiDAL Protocol spec):
      fitness = 0.25(answer_quality) + 0.20(evidence_quality)
              + 0.15(report_structure) + 0.15(clarification)
              + 0.10(memory_usefulness) - 0.10(excessive_rounds)
              - 0.05(unused_retrieval)
    """
    if not _MEMORY_ENABLED:
        return None

    # Compute fitness
    answer_quality = judge_score
    rounds_penalty = max(0, (rounds - 2) * 0.15) if rounds > 2 else 0.0
    unused_retrieval = 0.05 if mode == "didal_literature" and sources_used == 0 else 0.0

    fitness = (
        0.25 * answer_quality
        + 0.20 * evidence_quality
        + 0.15 * report_quality
        + 0.15 * clarification_quality
        + 0.10 * 0.5  # memory_usefulness placeholder
        - 0.10 * rounds_penalty
        - unused_retrieval
    )
    fitness = max(0.0, min(1.0, fitness))

    sid = _signal_id(protocol_id)
    now = time.time()

    try:
        db = _get_db()
        db.execute(
            """
            INSERT OR REPLACE INTO policy_signals
            (id, protocol_id, trace_id, mode, judge_score, evidence_quality,
             report_quality, clarification_quality, latency_s, rounds,
             sources_used, fitness, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (sid, protocol_id, trace_id, mode, judge_score, evidence_quality,
             report_quality, clarification_quality, latency_s, rounds,
             sources_used, fitness, json.dumps(metadata or {}), now),
        )
        db.commit()
        logger.debug(
            "policy_signal[%s] mode=%s fitness=%.3f judge=%.2f",
            protocol_id, mode, fitness, judge_score,
        )
        return fitness

    except Exception as exc:
        logger.warning("Policy signal write failed: %s", exc)
        return None


def get_policy_stats(mode: Optional[str] = None, limit: int = 50) -> dict:
    """Aggregate policy signals for threshold tuning.

    Returns stats that can be used to evolve classifier thresholds,
    round limits, retrieval policies, etc.
    """
    if not _MEMORY_ENABLED:
        return {}

    try:
        db = _get_db()

        if mode:
            rows = db.execute(
                "SELECT * FROM policy_signals WHERE mode = ? ORDER BY created_at DESC LIMIT ?",
                (mode, limit),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM policy_signals ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()

        if not rows:
            return {"count": 0}

        scores = [r["fitness"] for r in rows]
        judge_scores = [r["judge_score"] for r in rows if r["judge_score"]]
        rounds_list = [r["rounds"] for r in rows if r["rounds"] is not None]

        return {
            "count": len(rows),
            "avg_fitness": sum(scores) / len(scores),
            "avg_judge_score": sum(judge_scores) / len(judge_scores) if judge_scores else 0,
            "avg_rounds": sum(rounds_list) / len(rounds_list) if rounds_list else 0,
            "mode_distribution": _count_modes(rows),
        }
    except Exception as exc:
        logger.warning("Policy stats failed: %s", exc)
        return {}


def _count_modes(rows) -> dict:
    counts: dict[str, int] = {}
    for r in rows:
        m = r["mode"] or "unknown"
        counts[m] = counts.get(m, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Context managers for tracing integration
# ---------------------------------------------------------------------------

@contextmanager
def memory_read_stage(prompt: str, classification: dict):
    """Read relevant memories before framing the task.

    Yields a dict with recalled memories for injection into the protocol.
    """
    ctx = {"memories": [], "recall_count": 0}

    if not _MEMORY_ENABLED:
        yield ctx
        return

    try:
        # Recall episodic memories (similar past sessions)
        episodic = recall(prompt, mem_class="episodic", max_results=2)

        # Recall semantic memories (relevant concepts)
        semantic = recall(prompt, mem_class="semantic", max_results=3)

        # Recall procedural memories (strategy for this mode)
        mode = classification.get("mode", "didal")
        procedural = recall_by_class("procedural", limit=2)

        ctx["memories"] = episodic + semantic + procedural
        ctx["recall_count"] = len(ctx["memories"])

        logger.debug(
            "memory.read: %d episodic, %d semantic, %d procedural",
            len(episodic), len(semantic), len(procedural),
        )
    except Exception as exc:
        logger.warning("memory.read failed: %s", exc)

    yield ctx


@contextmanager
def memory_write_stage(
    protocol_result: dict,
    judge_score: float = 0.0,
    user_confirmed: bool = False,
):
    """Write memories after protocol completion (if writeback policy allows).

    Yields a dict with write stats.
    """
    ctx = {"written": 0, "skipped": 0, "fitness": None}

    if not _MEMORY_ENABLED:
        yield ctx
        return

    try:
        # Check writeback policy
        new_concept = bool(protocol_result.get("final_draft", {}).get("thesis"))
        if not should_write(
            judge_score=judge_score,
            user_confirmed=user_confirmed,
            new_concept=new_concept,
        ):
            ctx["skipped"] = 1
            logger.debug("memory.write: writeback policy rejected (score=%.2f)", judge_score)
            yield ctx
            return

        # Extract and write memories
        candidates = extract_memories_from_protocol(protocol_result, judge_score)
        protocol_id = protocol_result.get("protocol_id", "")
        trace_id = protocol_result.get("trace_id", "")

        for mem in candidates:
            mid = memorize(
                mem_class=mem["class"],
                key=mem["key"],
                content=mem["content"],
                score=mem["score"],
                metadata=mem.get("metadata"),
                protocol_id=protocol_id,
                trace_id=trace_id,
            )
            if mid:
                ctx["written"] += 1

        # Record policy signal
        mode = protocol_result.get("mode", "unknown")
        ctx["fitness"] = record_policy_signal(
            protocol_id=protocol_id,
            mode=mode,
            judge_score=judge_score,
            latency_s=protocol_result.get("elapsed_seconds", 0),
            rounds=protocol_result.get("critique_rounds", 0),
            sources_used=len(
                (protocol_result.get("evidence") or {}).get("sources", [])
            ),
            trace_id=trace_id,
        )

        logger.info(
            "memory.write: wrote %d memories, fitness=%.3f",
            ctx["written"], ctx["fitness"] or 0,
        )
    except Exception as exc:
        logger.warning("memory.write failed: %s", exc)

    yield ctx
