"""SQLite storage: doc metadata plus an FTS5 full-text index.

WAL mode so the API (reader) and the daemon (writer) don't block each other.
`store_path` is an addition beyond the brief's literal column list - the API
(section 6.6) must serve the original file and retry a locked PDF, which
needs to know where on disk that file is.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
    id TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL UNIQUE,
    original_ext TEXT NOT NULL,
    store_path TEXT,
    pages INTEGER,
    added_at TEXT NOT NULL,
    status TEXT NOT NULL,
    doc_type TEXT,
    doc_date TEXT,
    person TEXT,
    gist TEXT,
    tag_source TEXT
);
CREATE INDEX IF NOT EXISTS idx_docs_status ON docs(status);
CREATE INDEX IF NOT EXISTS idx_docs_sha256 ON docs(sha256);
CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(doc_id, body);
"""


class Fts5UnavailableError(RuntimeError):
    pass


def connect(db_path: str | Path) -> sqlite3.Connection:
    db_path = Path(db_path).expanduser()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        conn.executescript(SCHEMA)
    except sqlite3.OperationalError as e:
        if "fts5" in str(e).lower():
            raise Fts5UnavailableError(
                "sqlite3 build lacks FTS5 - rebuild/upgrade python/sqlite"
            ) from e
        raise
    conn.commit()
    return conn


def check_fts5(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_probe USING fts5(x)")
        conn.execute("DROP TABLE _fts5_probe")
        return True
    except sqlite3.OperationalError:
        return False


def utcnow_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def get_doc_by_sha256(conn: sqlite3.Connection, sha256: str) -> sqlite3.Row | None:
    cur = conn.execute("SELECT * FROM docs WHERE sha256 = ?", (sha256,))
    return cur.fetchone()


def get_doc(conn: sqlite3.Connection, doc_id: str) -> sqlite3.Row | None:
    cur = conn.execute("SELECT * FROM docs WHERE id = ?", (doc_id,))
    return cur.fetchone()


def get_docs_by_status(conn: sqlite3.Connection, status: str) -> list[sqlite3.Row]:
    cur = conn.execute("SELECT * FROM docs WHERE status = ? ORDER BY added_at", (status,))
    return cur.fetchall()


def insert_doc(
    conn: sqlite3.Connection,
    *,
    doc_id: str,
    sha256: str,
    original_ext: str,
    status: str,
    store_path: str | None = None,
    pages: int | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO docs (id, sha256, original_ext, store_path, pages, added_at, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (doc_id, sha256, original_ext, store_path, pages, utcnow_iso(), status),
    )
    conn.commit()


def update_status(conn: sqlite3.Connection, doc_id: str, status: str) -> None:
    conn.execute("UPDATE docs SET status = ? WHERE id = ?", (status, doc_id))
    conn.commit()


def set_extracted(conn: sqlite3.Connection, doc_id: str, pages: int, body: str) -> None:
    conn.execute(
        "UPDATE docs SET status = 'extracted', pages = ? WHERE id = ?", (pages, doc_id)
    )
    conn.execute("DELETE FROM docs_fts WHERE doc_id = ?", (doc_id,))
    conn.execute("INSERT INTO docs_fts (doc_id, body) VALUES (?, ?)", (doc_id, body))
    conn.commit()


def set_tags(
    conn: sqlite3.Connection,
    doc_id: str,
    *,
    doc_type: str | None,
    doc_date: str | None,
    person: str | None,
    gist: str | None,
    tag_source: str,
) -> None:
    conn.execute(
        """
        UPDATE docs SET doc_type = ?, doc_date = ?, person = ?, gist = ?, tag_source = ?
        WHERE id = ?
        """,
        (doc_type, doc_date, person, gist, tag_source, doc_id),
    )
    conn.commit()


def _fts_escape_token(token: str) -> str:
    return '"' + token.replace('"', '""') + '"'


def _fts_query(q: str) -> str:
    """Turns free text into a safe FTS5 query: each token as a literal phrase,
    ANDed together (FTS5's default), so hyphens/punctuation in doc text can't
    be misread as FTS5 query syntax."""
    tokens = q.split()
    if not tokens:
        return '""'
    return " ".join(_fts_escape_token(t) for t in tokens)


def search(
    conn: sqlite3.Connection,
    q: str,
    *,
    doc_type: str | None = None,
    person: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 20,
) -> list[dict]:
    sql = [
        "SELECT d.id AS id, d.doc_type AS doc_type, d.doc_date AS doc_date,",
        "       d.gist AS gist,",
        "       snippet(docs_fts, 1, '[', ']', ' ... ', 10) AS snippet",
        "FROM docs_fts JOIN docs d ON d.id = docs_fts.doc_id",
        "WHERE docs_fts MATCH ?",
    ]
    params: list = [_fts_query(q)]
    if doc_type:
        sql.append("AND d.doc_type = ?")
        params.append(doc_type)
    if person:
        sql.append("AND d.person = ?")
        params.append(person)
    if date_from:
        sql.append("AND d.doc_date >= ?")
        params.append(date_from)
    if date_to:
        sql.append("AND d.doc_date <= ?")
        params.append(date_to)
    sql.append("ORDER BY rank LIMIT ?")
    params.append(limit)

    cur = conn.execute(" ".join(sql), params)
    return [dict(r) for r in cur.fetchall()]


def status_counts(conn: sqlite3.Connection) -> dict[str, int]:
    cur = conn.execute("SELECT status, COUNT(*) AS n FROM docs GROUP BY status")
    return {row["status"]: row["n"] for row in cur.fetchall()}
