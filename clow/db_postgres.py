"""PostgreSQL backend adapter for Clow.

Drop-in replacement for SQLite connection pool.
Activated via CLOW_DB_BACKEND=postgres and DATABASE_URL env var.

Uses psycopg2 with a thread-safe connection pool. Returns connections
that emulate sqlite3.Row via RealDictCursor, so existing code works
with minimal changes.
"""
from __future__ import annotations

import logging
import os
import threading
from contextlib import contextmanager

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    os.getenv("CLOW_DATABASE_URL", "postgresql://chatwoot:ChAtW00t_PV_2026@localhost:5432/clow_app"),
)

_pool = None
_pool_lock = threading.Lock()
_POOL_MIN = int(os.getenv("CLOW_DB_POOL_MIN", "2"))
_POOL_MAX = int(os.getenv("CLOW_DB_POOL_MAX", "10"))


def _get_pool():
    """Lazy-init a threaded connection pool."""
    global _pool
    if _pool is not None:
        return _pool

    with _pool_lock:
        if _pool is not None:
            return _pool

        from psycopg2 import pool as pg_pool
        _pool = pg_pool.ThreadedConnectionPool(
            _POOL_MIN, _POOL_MAX, DATABASE_URL,
        )
        logger.info("PostgreSQL pool created (%d-%d conns)", _POOL_MIN, _POOL_MAX)
        return _pool


class _PgRowWrapper:
    """Wraps a dict row to support both dict-style and attribute access,
    mimicking sqlite3.Row for backward compatibility."""

    def __init__(self, data: dict):
        self._data = data

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self._data.values())[key]
        return self._data[key]

    def __contains__(self, key):
        return key in self._data

    def __iter__(self):
        return iter(self._data.values())

    def __len__(self):
        return len(self._data)

    def get(self, key, default=None):
        return self._data.get(key, default)

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()

    def items(self):
        return self._data.items()


class PgCursorWrapper:
    """Wraps a psycopg2 cursor to return _PgRowWrapper rows and support
    sqlite3-compatible .fetchone()/.fetchall()/.fetchmany()."""

    def __init__(self, cursor):
        self._cursor = cursor

    @property
    def description(self):
        return self._cursor.description

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        # PostgreSQL doesn't have lastrowid natively
        # Use RETURNING in INSERT statements instead
        return None

    def fetchone(self):
        row = self._cursor.fetchone()
        return _PgRowWrapper(row) if row else None

    def fetchall(self):
        return [_PgRowWrapper(r) for r in self._cursor.fetchall()]

    def fetchmany(self, size=100):
        return [_PgRowWrapper(r) for r in self._cursor.fetchmany(size)]


class PgConnectionWrapper:
    """Wraps a psycopg2 connection to behave like sqlite3.Connection.

    Key differences handled:
    - Uses %s instead of ? for placeholders (auto-converted)
    - Returns wrapped cursor with Row-like behavior
    - Tracks total_changes for compat
    """

    def __init__(self, conn):
        self._conn = conn
        self.total_changes = 0

    def execute(self, sql: str, params=None):
        """Execute SQL, converting ? placeholders to %s for psycopg2."""
        sql = _convert_placeholders(sql)
        from psycopg2.extras import RealDictCursor
        cur = self._conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(sql, params or ())
            self.total_changes = cur.rowcount if cur.rowcount > 0 else 0
            return PgCursorWrapper(cur)
        except Exception:
            cur.close()
            raise

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        # Don't close — return to pool in get_db
        pass

    @property
    def raw(self):
        """Access underlying psycopg2 connection."""
        return self._conn


def _convert_placeholders(sql: str) -> str:
    """Convert SQLite ? placeholders to PostgreSQL %s.

    Handles:
    - Simple ? → %s
    - Skips ? inside string literals
    - Converts SQLite-specific syntax
    """
    # Skip if already has %s (already PostgreSQL syntax)
    if "%s" in sql:
        return sql

    # Convert INTEGER PRIMARY KEY AUTOINCREMENT → SERIAL PRIMARY KEY
    sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")

    # Convert strftime to extract
    sql = sql.replace("strftime('%s','now')", "EXTRACT(EPOCH FROM NOW())")
    sql = sql.replace("strftime('%s', 'now')", "EXTRACT(EPOCH FROM NOW())")
    sql = sql.replace("strftime('%s', 'now', '-30 days')", "EXTRACT(EPOCH FROM NOW() - INTERVAL '30 days')")
    sql = sql.replace("strftime('%s', 'now', '-7 days')", "EXTRACT(EPOCH FROM NOW() - INTERVAL '7 days')")

    # Convert date() to TO_CHAR
    sql = sql.replace("date(created_at,'unixepoch')", "TO_CHAR(TO_TIMESTAMP(created_at), 'YYYY-MM-DD')")
    sql = sql.replace("date(created_at, 'unixepoch')", "TO_CHAR(TO_TIMESTAMP(created_at), 'YYYY-MM-DD')")

    # Convert ? to %s (simple replacement, avoiding string literals)
    result = []
    in_string = False
    for char in sql:
        if char == "'" and not in_string:
            in_string = True
            result.append(char)
        elif char == "'" and in_string:
            in_string = False
            result.append(char)
        elif char == "?" and not in_string:
            result.append("%s")
        else:
            result.append(char)
    return "".join(result)


@contextmanager
def get_db():
    """Get a PostgreSQL connection from the pool, wrapped for SQLite compat."""
    pool = _get_pool()
    conn = pool.getconn()
    wrapper = PgConnectionWrapper(conn)
    try:
        yield wrapper
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            pool.putconn(conn)
        except Exception:
            pass


def init_db():
    """Run migrations on PostgreSQL."""
    from .migrations_pg import run_pg_migrations
    run_pg_migrations()
