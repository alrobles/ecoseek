"""Literature database — persistent SQLite cache for retrieved papers.

Stores papers from OpenAlex, GBIF Literature, Semantic Scholar, and Entrez
so repeated queries hit the local cache instead of the API. Provides FTS5
full-text search over titles and abstracts for fast retrieval.

The database is created at DIDAL_MEMORY_DIR/literature.db (same volume
as the memory store) so it persists across Docker restarts.

Architecture:
  retrieve_literature() → litdb.search() → if miss → API call → litdb.store()
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Generator

logger = logging.getLogger(__name__)

_DB_DIR = os.environ.get(
    "DIDAL_MEMORY_DIR", os.path.expanduser("~/.ecoseek/didal_memory")
)
_DB_PATH = os.path.join(_DB_DIR, "literature.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    doi         TEXT UNIQUE,
    title       TEXT NOT NULL,
    authors     TEXT DEFAULT '',
    year        INTEGER,
    abstract    TEXT DEFAULT '',
    url         TEXT DEFAULT '',
    source_type TEXT DEFAULT 'paper',
    provider    TEXT DEFAULT '',
    confidence  REAL DEFAULT 0.0,
    raw_json    TEXT DEFAULT '{}',
    created_at  REAL NOT NULL,
    last_used   REAL NOT NULL,
    use_count   INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_papers_provider ON papers(provider);
CREATE INDEX IF NOT EXISTS idx_papers_year ON papers(year);

-- FTS5 full-text search over titles and abstracts
CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
    title, abstract, authors,
    content='papers',
    content_rowid='id',
    tokenize='porter unicode61'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS papers_ai AFTER INSERT ON papers BEGIN
    INSERT INTO papers_fts(rowid, title, abstract, authors)
    VALUES (new.id, new.title, new.abstract, new.authors);
END;

CREATE TRIGGER IF NOT EXISTS papers_ad AFTER DELETE ON papers BEGIN
    INSERT INTO papers_fts(papers_fts, rowid, title, abstract, authors)
    VALUES ('delete', old.id, old.title, old.abstract, old.authors);
END;

CREATE TRIGGER IF NOT EXISTS papers_au AFTER UPDATE ON papers BEGIN
    INSERT INTO papers_fts(papers_fts, rowid, title, abstract, authors)
    VALUES ('delete', old.id, old.title, old.abstract, old.authors);
    INSERT INTO papers_fts(rowid, title, abstract, authors)
    VALUES (new.id, new.title, new.abstract, new.authors);
END;

-- User-uploaded documents (PDFs, etc.)
CREATE TABLE IF NOT EXISTS user_papers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    filename    TEXT NOT NULL,
    title       TEXT DEFAULT '',
    authors     TEXT DEFAULT '',
    year        INTEGER,
    abstract    TEXT DEFAULT '',
    full_text   TEXT DEFAULT '',
    num_pages   INTEGER DEFAULT 0,
    num_tokens  INTEGER DEFAULT 0,
    file_hash   TEXT UNIQUE,
    created_at  REAL NOT NULL
);

-- FTS5 for user-uploaded documents
CREATE VIRTUAL TABLE IF NOT EXISTS user_papers_fts USING fts5(
    title, abstract, full_text, authors,
    content='user_papers',
    content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS user_papers_ai AFTER INSERT ON user_papers BEGIN
    INSERT INTO user_papers_fts(rowid, title, abstract, full_text, authors)
    VALUES (new.id, new.title, new.abstract, new.full_text, new.authors);
END;

CREATE TRIGGER IF NOT EXISTS user_papers_ad AFTER DELETE ON user_papers BEGIN
    INSERT INTO user_papers_fts(user_papers_fts, rowid, title, abstract, full_text, authors)
    VALUES ('delete', old.id, old.title, old.abstract, old.full_text, old.authors);
END;

-- Statistics table for cache monitoring
CREATE TABLE IF NOT EXISTS lit_stats (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _ensure_dir():
    os.makedirs(_DB_DIR, exist_ok=True)


@contextmanager
def _connect() -> Generator[sqlite3.Connection, None, None]:
    _ensure_dir()
    conn = sqlite3.connect(_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create tables if they don't exist."""
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        logger.info("litdb initialized at %s", _DB_PATH)


def store_paper(
    doi: str,
    title: str,
    authors: str = "",
    year: int | None = None,
    abstract: str = "",
    url: str = "",
    source_type: str = "paper",
    provider: str = "",
    confidence: float = 0.0,
    raw_json: dict | None = None,
) -> bool:
    """Store a paper in the cache. Returns True if inserted, False if duplicate."""
    if not doi and not title:
        return False

    now = time.time()
    raw = json.dumps(raw_json or {}, ensure_ascii=False)

    with _connect() as conn:
        # Use DOI as dedup key if available, otherwise title hash
        dedup_key = doi.lower().strip() if doi else None
        if dedup_key:
            existing = conn.execute(
                "SELECT id FROM papers WHERE doi = ?", (dedup_key,)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE papers SET last_used = ?, use_count = use_count + 1 WHERE id = ?",
                    (now, existing["id"]),
                )
                return False

        conn.execute(
            """INSERT INTO papers (doi, title, authors, year, abstract, url,
               source_type, provider, confidence, raw_json, created_at, last_used)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                dedup_key or "",
                title,
                authors,
                year,
                abstract[:2000],
                url,
                source_type,
                provider,
                confidence,
                raw,
                now,
                now,
            ),
        )
        return True


def store_many(papers: list[dict]) -> int:
    """Batch-store papers. Returns count of newly inserted papers."""
    inserted = 0
    for p in papers:
        if store_paper(
            doi=p.get("doi", ""),
            title=p.get("title", ""),
            authors=p.get("authors", ""),
            year=p.get("year"),
            abstract=p.get("abstract", ""),
            url=p.get("url", ""),
            source_type=p.get("source_type", "paper"),
            provider=p.get("provider", ""),
            confidence=p.get("confidence", 0.0),
            raw_json=p,
        ):
            inserted += 1
    return inserted


def search(query: str, limit: int = 10) -> list[dict]:
    """Full-text search over cached papers. Returns list of dicts."""
    if not query.strip():
        return []

    with _connect() as conn:
        try:
            rows = conn.execute(
                """SELECT p.*, rank
                   FROM papers_fts f
                   JOIN papers p ON p.id = f.rowid
                   WHERE papers_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (_fts_query(query), limit),
            ).fetchall()
        except sqlite3.OperationalError:
            # FTS query syntax error — fallback to LIKE
            like = f"%{query}%"
            rows = conn.execute(
                """SELECT *, 0 as rank FROM papers
                   WHERE title LIKE ? OR abstract LIKE ?
                   ORDER BY year DESC
                   LIMIT ?""",
                (like, like, limit),
            ).fetchall()

    now = time.time()
    results = []
    for row in rows:
        conn_upd = None
        try:
            with _connect() as conn_upd:
                conn_upd.execute(
                    "UPDATE papers SET last_used = ?, use_count = use_count + 1 WHERE id = ?",
                    (now, row["id"]),
                )
        except Exception:
            pass

        results.append(
            {
                "doi": row["doi"],
                "title": row["title"],
                "authors": row["authors"],
                "year": row["year"],
                "abstract": row["abstract"][:500],
                "url": row["url"],
                "source_type": row["source_type"],
                "provider": row["provider"],
                "confidence": row["confidence"],
            }
        )

    return results


def get_stats() -> dict:
    """Return database statistics."""
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) as n FROM papers").fetchone()["n"]
        by_provider = {}
        for row in conn.execute(
            "SELECT provider, COUNT(*) as n FROM papers GROUP BY provider"
        ).fetchall():
            by_provider[row["provider"]] = row["n"]
        recent = conn.execute(
            "SELECT COUNT(*) as n FROM papers WHERE created_at > ?",
            (time.time() - 86400,),
        ).fetchone()["n"]

    return {
        "total_papers": total,
        "by_provider": by_provider,
        "added_last_24h": recent,
        "db_path": _DB_PATH,
    }


def _fts_query(query: str) -> str:
    """Convert a user query into FTS5 syntax (OR-joined terms)."""
    # Remove FTS special chars and build OR query
    clean = "".join(c if c.isalnum() or c.isspace() else " " for c in query)
    terms = [t.strip() for t in clean.split() if len(t.strip()) >= 2]
    if not terms:
        return query
    return " OR ".join(terms)


# ---------------------------------------------------------------------------
# User-uploaded documents (PDFs)
# ---------------------------------------------------------------------------


def ingest_document(
    filename: str,
    full_text: str,
    title: str = "",
    authors: str = "",
    year: int | None = None,
    abstract: str = "",
    num_pages: int = 0,
) -> dict:
    """Ingest a user-uploaded document into the local FTS5 index.

    Parameters
    ----------
    filename : str
        Original filename (e.g., "smith_2023_niche.pdf").
    full_text : str
        Extracted text content from the document.
    title : str
        Paper title (auto-detected from first line if empty).
    authors, year, abstract : str/int
        Optional metadata.
    num_pages : int
        Number of pages in the source document.

    Returns
    -------
    dict
        Ingest result with id, num_tokens, and status.
    """
    import hashlib

    if not full_text.strip():
        return {"success": False, "error": "empty_document"}

    file_hash = hashlib.sha256(full_text.encode("utf-8")).hexdigest()[:32]
    num_tokens = len(full_text.split())

    if not title:
        first_line = full_text.strip().split("\n")[0][:200]
        title = first_line

    if not abstract and len(full_text) > 500:
        abstract = full_text[:500]

    now = time.time()

    with _connect() as conn:
        existing = conn.execute(
            "SELECT id FROM user_papers WHERE file_hash = ?", (file_hash,)
        ).fetchone()
        if existing:
            return {
                "success": True,
                "status": "already_indexed",
                "id": existing["id"],
                "filename": filename,
            }

        cursor = conn.execute(
            """INSERT INTO user_papers
               (filename, title, authors, year, abstract, full_text,
                num_pages, num_tokens, file_hash, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                filename,
                title,
                authors,
                year,
                abstract[:2000],
                full_text[:50000],
                num_pages,
                num_tokens,
                file_hash,
                now,
            ),
        )
        doc_id = cursor.lastrowid

    logger.info(
        "Ingested user document '%s': %d tokens, %d pages",
        filename,
        num_tokens,
        num_pages,
    )
    return {
        "success": True,
        "status": "indexed",
        "id": doc_id,
        "filename": filename,
        "title": title[:100],
        "num_pages": num_pages,
        "num_tokens": num_tokens,
    }


def search_user_papers(query: str, limit: int = 5) -> list[dict]:
    """Search user-uploaded documents via FTS5."""
    if not query.strip():
        return []

    with _connect() as conn:
        try:
            rows = conn.execute(
                """SELECT p.*, rank
                   FROM user_papers_fts f
                   JOIN user_papers p ON p.id = f.rowid
                   WHERE user_papers_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (_fts_query(query), limit),
            ).fetchall()
        except sqlite3.OperationalError:
            like = f"%{query}%"
            rows = conn.execute(
                """SELECT *, 0 as rank FROM user_papers
                   WHERE title LIKE ? OR full_text LIKE ?
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (like, like, limit),
            ).fetchall()

    results = []
    for row in rows:
        text = row["full_text"] or ""
        snippet = ""
        lower_q = query.lower()
        idx = text.lower().find(lower_q)
        if idx >= 0:
            start = max(0, idx - 100)
            end = min(len(text), idx + len(query) + 200)
            snippet = text[start:end]
        elif text:
            snippet = text[:300]

        results.append(
            {
                "id": row["id"],
                "filename": row["filename"],
                "title": row["title"],
                "authors": row["authors"],
                "year": row["year"],
                "snippet": snippet,
                "num_pages": row["num_pages"],
                "num_tokens": row["num_tokens"],
                "source_type": "user_upload",
                "provider": "user_upload",
                "confidence": 0.9,
            }
        )

    return results


def get_user_paper_stats() -> dict:
    """Return stats about user-uploaded documents."""
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) as n FROM user_papers").fetchone()["n"]
        total_tokens = conn.execute(
            "SELECT COALESCE(SUM(num_tokens), 0) as n FROM user_papers"
        ).fetchone()["n"]
    return {"total_documents": total, "total_tokens": total_tokens}


# Auto-initialize on import
try:
    init_db()
except Exception as exc:
    logger.warning("litdb init failed (will retry on first use): %s", exc)
