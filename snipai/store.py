"""Local snip history — SQLite. Every snip + answer saved, searchable.

DB lives at ~/.snipai/history.db. Thumbnails stored as small PNG blobs.
All calls are synchronous and fast (local file); safe to call from the UI thread
for single-row ops, but searches run on demand from the history window.
"""
from __future__ import annotations
import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

DB_DIR = Path.home() / ".snipai"
DB_PATH = DB_DIR / "history.db"


@dataclass
class SnipRecord:
    id: int
    ts: float
    mode: str           # "crop" | "text" | "stack"
    question: str
    answer: str
    selected_text: str
    thumb_png: bytes | None


def _connect() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS snips (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                ts            REAL    NOT NULL,
                mode          TEXT    NOT NULL,
                question      TEXT    NOT NULL DEFAULT '',
                answer        TEXT    NOT NULL DEFAULT '',
                selected_text TEXT    NOT NULL DEFAULT '',
                thumb_png     BLOB
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_snips_ts ON snips(ts DESC)")
    log.info("history db ready at %s", DB_PATH)


def save_snip(mode: str, question: str, answer: str,
              selected_text: str = "", thumb_png: bytes | None = None) -> int:
    """Insert one snip. Returns row id. Never raises into caller."""
    try:
        with _connect() as conn:
            cur = conn.execute(
                "INSERT INTO snips (ts, mode, question, answer, selected_text, thumb_png) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (time.time(), mode, question, answer, selected_text, thumb_png),
            )
            return int(cur.lastrowid)
    except Exception:
        log.exception("save_snip failed")
        return -1


def _row_to_record(r: sqlite3.Row) -> SnipRecord:
    return SnipRecord(
        id=r["id"], ts=r["ts"], mode=r["mode"], question=r["question"],
        answer=r["answer"], selected_text=r["selected_text"],
        thumb_png=r["thumb_png"],
    )


def recent(limit: int = 100) -> list[SnipRecord]:
    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT * FROM snips ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_row_to_record(r) for r in rows]
    except Exception:
        log.exception("recent failed")
        return []


def search(query: str, limit: int = 100) -> list[SnipRecord]:
    """Substring match across question, answer, selected_text."""
    q = f"%{query.strip()}%"
    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT * FROM snips WHERE question LIKE ? OR answer LIKE ? "
                "OR selected_text LIKE ? ORDER BY ts DESC LIMIT ?",
                (q, q, q, limit),
            ).fetchall()
        return [_row_to_record(r) for r in rows]
    except Exception:
        log.exception("search failed")
        return []


def get(snip_id: int) -> SnipRecord | None:
    try:
        with _connect() as conn:
            r = conn.execute("SELECT * FROM snips WHERE id = ?", (snip_id,)).fetchone()
        return _row_to_record(r) if r else None
    except Exception:
        log.exception("get failed")
        return None


def delete(snip_id: int) -> None:
    try:
        with _connect() as conn:
            conn.execute("DELETE FROM snips WHERE id = ?", (snip_id,))
    except Exception:
        log.exception("delete failed")


def clear_all() -> None:
    try:
        with _connect() as conn:
            conn.execute("DELETE FROM snips")
    except Exception:
        log.exception("clear_all failed")
