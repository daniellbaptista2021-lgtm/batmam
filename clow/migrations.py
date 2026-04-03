"""Database migrations for Clow.

Centralizes all table schemas and provides versioned migrations
so that scattered CREATE TABLE IF NOT EXISTS calls can be replaced
with a single ``run_migrations()`` invocation at startup.

Usage:
    from clow.migrations import run_migrations
    run_migrations()          # safe to call on every boot

Each migration is a (version, description, up_sql) tuple.  The helper
``run_migrations`` creates a ``_migrations`` bookkeeping table, then
applies any migrations whose version has not yet been recorded.
Columns are added with ``ADD COLUMN ... DEFAULT`` so existing data is
never lost.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Sequence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Migration definitions
# Each entry: (version: int, description: str, up_sql: str)
# up_sql may contain multiple statements separated by semicolons.
# ---------------------------------------------------------------------------

MIGRATIONS: list[tuple[int, str, str]] = [
    # ── v1: core tables (users, usage_log, conversations, messages) ──
    (
        1,
        "Create core tables: users, usage_log, conversations, messages",
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT DEFAULT '',
            plan TEXT DEFAULT 'free',
            active INTEGER DEFAULT 1,
            is_admin INTEGER DEFAULT 0,
            created_at REAL NOT NULL,
            last_login REAL
        );

        CREATE TABLE IF NOT EXISTS usage_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            model TEXT NOT NULL,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            cost_usd REAL DEFAULT 0,
            action TEXT DEFAULT 'chat',
            created_at REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT DEFAULT 'Nova conversa',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            file_data TEXT,
            created_at REAL NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_usage_user_date ON usage_log(user_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_id, updated_at);
        CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id, created_at);
        """,
    ),
    # ── v2: missions tables ──────────────────────────────────────────
    (
        2,
        "Create missions and mission_steps tables",
        """
        CREATE TABLE IF NOT EXISTS missions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT DEFAULT 'planning',
            plan_json TEXT,
            context_json TEXT DEFAULT '{}',
            current_step INTEGER DEFAULT 0,
            total_steps INTEGER DEFAULT 0,
            error_count INTEGER DEFAULT 0,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            completed_at REAL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS mission_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mission_id TEXT NOT NULL,
            step_number INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'pending',
            model TEXT DEFAULT 'haiku',
            result_json TEXT,
            error TEXT,
            attempts INTEGER DEFAULT 0,
            started_at REAL,
            completed_at REAL,
            FOREIGN KEY (mission_id) REFERENCES missions(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_missions_user ON missions(user_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_msteps_mission ON mission_steps(mission_id, step_number);
        """,
    ),
    # ── v3: claude_code_log (from claude_code_bridge.py) ─────────────
    (
        3,
        "Create claude_code_log table for CLI usage tracking",
        """
        CREATE TABLE IF NOT EXISTS claude_code_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            prompt_preview TEXT NOT NULL,
            elapsed_seconds REAL NOT NULL,
            created_at REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_cclog_user ON claude_code_log(user_id, created_at);
        """,
    ),
    # ── v4: rate_limit_events (optional audit trail for rate limits) ─
    (
        4,
        "Create rate_limit_events table",
        """
        CREATE TABLE IF NOT EXISTS rate_limit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT NOT NULL,
            user_id TEXT DEFAULT '',
            plan TEXT DEFAULT 'free',
            blocked INTEGER DEFAULT 0,
            created_at REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_rl_ip ON rate_limit_events(ip, created_at);
        CREATE INDEX IF NOT EXISTS idx_rl_user ON rate_limit_events(user_id, created_at);
        """,
    ),
]


# ---------------------------------------------------------------------------
# Migration runner
# ---------------------------------------------------------------------------

def _ensure_migrations_table(db) -> None:
    """Create the internal ``_migrations`` bookkeeping table."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS _migrations (
            version INTEGER PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at REAL NOT NULL
        )
    """)


def _applied_versions(db) -> set[int]:
    """Return the set of already-applied migration versions."""
    rows = db.execute("SELECT version FROM _migrations").fetchall()
    return {row[0] if isinstance(row, (tuple, list)) else row["version"] for row in rows}


def run_migrations(db_getter=None) -> list[int]:
    """Apply all pending migrations and return the list of newly applied versions.

    Parameters
    ----------
    db_getter:
        A callable that returns a context-manager yielding an ``sqlite3.Connection``.
        When *None*, falls back to ``clow.database.get_db`` (lazy import so the
        module can be used stand-alone for testing).

    Returns
    -------
    list[int]
        Versions that were applied during this call (empty if everything was
        already up-to-date).
    """
    if db_getter is None:
        from .database import get_db
        db_getter = get_db

    applied: list[int] = []

    with db_getter() as db:
        _ensure_migrations_table(db)
        already = _applied_versions(db)

        for version, description, up_sql in sorted(MIGRATIONS, key=lambda m: m[0]):
            if version in already:
                continue
            logger.info("Applying migration v%d: %s", version, description)
            try:
                db.executescript(up_sql)
                db.execute(
                    "INSERT INTO _migrations (version, description, applied_at) VALUES (?, ?, ?)",
                    (version, description, time.time()),
                )
                applied.append(version)
                logger.info("Migration v%d applied successfully.", version)
            except Exception:
                logger.exception("Migration v%d FAILED.", version)
                raise

    return applied


def add_column_safe(db, table: str, column: str, col_type: str, default: str = "") -> bool:
    """Add a column to *table* only if it does not already exist.

    Uses ``PRAGMA table_info`` to detect existing columns, then issues
    ``ALTER TABLE ... ADD COLUMN`` when the column is missing.  This is
    safe for SQLite (the only ALTER TABLE operation it supports without
    recreating the table).

    Returns True if the column was added, False if it already existed.
    """
    existing = {row[1] if isinstance(row, (tuple, list)) else row["name"]
                for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
    if column in existing:
        return False

    default_clause = f" DEFAULT {default}" if default else ""
    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}{default_clause}")
    logger.info("Added column %s.%s (%s%s)", table, column, col_type, default_clause)
    return True


def current_version(db_getter=None) -> int:
    """Return the highest migration version that has been applied, or 0."""
    if db_getter is None:
        from .database import get_db
        db_getter = get_db

    with db_getter() as db:
        try:
            row = db.execute("SELECT MAX(version) FROM _migrations").fetchone()
            val = row[0] if isinstance(row, (tuple, list)) else row["MAX(version)"]
            return val or 0
        except Exception:
            return 0
