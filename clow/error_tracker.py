"""Lightweight error tracking — stores errors in SQLite with context."""

import logging
import os
import json
import time
import traceback
import threading
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

_DB_PATH = Path(os.path.expanduser("~/.clow/errors.db"))
_lock = threading.Lock()


def _get_db() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS errors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp REAL NOT NULL,
        level TEXT NOT NULL,
        message TEXT NOT NULL,
        traceback TEXT,
        context TEXT,
        resolved INTEGER DEFAULT 0
    )""")
    return conn


def capture_exception(exc: Exception, context: dict | None = None) -> int:
    """Capture and store an exception. Returns error ID."""
    tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
    with _lock:
        conn = _get_db()
        try:
            cur = conn.execute(
                "INSERT INTO errors (timestamp, level, message, traceback, context) VALUES (?,?,?,?,?)",
                (time.time(), "ERROR", str(exc), "".join(tb), json.dumps(context or {})),
            )
            conn.commit()
            error_id = cur.lastrowid
            logger.error("Error #%d captured: %s", error_id, exc)
            return error_id
        finally:
            conn.close()


def capture_warning(message: str, context: dict | None = None) -> int:
    """Capture a warning. Returns error ID."""
    with _lock:
        conn = _get_db()
        try:
            cur = conn.execute(
                "INSERT INTO errors (timestamp, level, message, context) VALUES (?,?,?,?)",
                (time.time(), "WARNING", message, json.dumps(context or {})),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()


def get_recent_errors(limit: int = 50, unresolved_only: bool = False) -> list[dict]:
    """Return recent errors."""
    conn = _get_db()
    try:
        q = "SELECT * FROM errors"
        if unresolved_only:
            q += " WHERE resolved = 0"
        q += " ORDER BY id DESC LIMIT ?"
        return [dict(r) for r in conn.execute(q, (limit,)).fetchall()]
    finally:
        conn.close()


def resolve_error(error_id: int) -> None:
    """Mark an error as resolved."""
    conn = _get_db()
    try:
        conn.execute("UPDATE errors SET resolved = 1 WHERE id = ?", (error_id,))
        conn.commit()
    finally:
        conn.close()


def error_stats() -> dict:
    """Return error statistics."""
    conn = _get_db()
    try:
        now = time.time()
        total = conn.execute("SELECT COUNT(*) FROM errors").fetchone()[0]
        unresolved = conn.execute("SELECT COUNT(*) FROM errors WHERE resolved = 0").fetchone()[0]
        last_hour = conn.execute("SELECT COUNT(*) FROM errors WHERE timestamp > ?", (now - 3600,)).fetchone()[0]
        last_24h = conn.execute("SELECT COUNT(*) FROM errors WHERE timestamp > ?", (now - 86400,)).fetchone()[0]
        return {
            "total": total,
            "unresolved": unresolved,
            "last_hour": last_hour,
            "last_24h": last_24h,
        }
    finally:
        conn.close()
