"""Authentication, session management, and rate limiting helpers.

Shared across all route modules.
"""

from __future__ import annotations
import logging
import os
import sqlite3
import time
import secrets
from pathlib import Path
from typing import Any

from fastapi import Request, HTTPException

from .. import config
from ..database import authenticate_user, create_user, get_user_by_email

logger = logging.getLogger(__name__)


# ── Authentication ──────────────────────────────────────────────

def _get_api_keys() -> list[str]:
    """Carrega API keys do settings ou env."""
    settings = config.load_settings()
    keys = settings.get("webapp", {}).get("api_keys", [])
    env_key = os.getenv("CLOW_API_KEY", "")
    if env_key and env_key not in keys:
        keys.append(env_key)
    return keys


def _generate_api_key() -> str:
    """Gera uma nova API key segura."""
    return f"clow_{secrets.token_urlsafe(32)}"


def _verify_api_key(key: str) -> bool:
    """Verifica se uma API key e valida."""
    valid_keys = _get_api_keys()
    if not valid_keys:
        # So permite dev mode se CLOW_DEV_MODE=true explicitamente
        import os
        return os.getenv("CLOW_DEV_MODE", "").lower() in ("true", "1")
    return key in valid_keys


async def _auth_dependency(request: Request) -> None:
    """FastAPI dependency para verificar autenticacao."""
    keys = _get_api_keys()
    if not keys:
        import os
        if os.getenv("CLOW_DEV_MODE", "").lower() in ("true", "1"):
            return  # Dev mode explicito
        raise HTTPException(status_code=401, detail="API key necessaria")

    # Tenta Authorization header
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if _verify_api_key(token):
            return

    # Tenta query param
    api_key = request.query_params.get("api_key", "")
    if api_key and _verify_api_key(api_key):
        return

    raise HTTPException(status_code=401, detail="API key invalida ou ausente")


# ── Login / Session (SQLite-persisted + memory cache) ────────────

_session_cache: dict[str, dict] = {}
_SESSION_TTL = 86400 * 30  # 30 dias


def _init_sessions_table():
    """Create sessions table if not exists."""
    from ..database import get_db
    with get_db() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS web_sessions (
            token TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            user_id TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            plan TEXT DEFAULT 'free',
            created REAL NOT NULL
        )""")


def _create_session(user: dict) -> str:
    token = secrets.token_urlsafe(48)
    sess = {
        "email": user["email"],
        "user_id": user["id"],
        "is_admin": bool(user.get("is_admin")),
        "plan": user.get("plan", "free"),
        "created": time.time(),
    }
    _session_cache[token] = sess
    try:
        from ..database import get_db
        _init_sessions_table()
        with get_db() as db:
            db.execute(
                "INSERT OR REPLACE INTO web_sessions (token, email, user_id, is_admin, plan, created) VALUES (?,?,?,?,?,?)",
                (token, sess["email"], sess["user_id"], int(sess["is_admin"]), sess["plan"], sess["created"]),
            )
    except Exception:
        pass  # Memory fallback
    return token


def _validate_session(token: str) -> dict | None:
    if not token:
        return None

    # Check memory cache first
    sess = _session_cache.get(token)
    if sess:
        if time.time() - sess["created"] > _SESSION_TTL:
            _session_cache.pop(token, None)
            _delete_session_db(token)
            return None
        return sess

    # Check SQLite
    try:
        from ..database import get_db
        _init_sessions_table()
        with get_db() as db:
            row = db.execute("SELECT * FROM web_sessions WHERE token=?", (token,)).fetchone()
            if row:
                sess = {
                    "email": row["email"],
                    "user_id": row["user_id"],
                    "is_admin": bool(row["is_admin"]),
                    "plan": row["plan"],
                    "created": row["created"],
                }
                if time.time() - sess["created"] > _SESSION_TTL:
                    _delete_session_db(token)
                    return None
                _session_cache[token] = sess
                return sess
    except Exception:
        pass
    return None


def _delete_session_db(token: str):
    try:
        from ..database import get_db
        with get_db() as db:
            db.execute("DELETE FROM web_sessions WHERE token=?", (token,))
    except Exception:
        pass


def _get_session_from_request(request: Request) -> str | None:
    """Returns email string for backwards compat."""
    token = request.cookies.get("clow_session", "")
    sess = _validate_session(token)
    return sess["email"] if sess else None


def _get_user_session(request: Request) -> dict | None:
    """Returns full session dict. Checks cookie first, then Bearer token."""
    token = request.cookies.get("clow_session", "")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    return _validate_session(token)


# ── Rate Limiting (SQLite persistente) ──────────────────────────

_RATE_LIMIT_DB = Path(__file__).resolve().parent.parent.parent / "data" / "rate_limits.db"
_RATE_LIMIT_DB.parent.mkdir(parents=True, exist_ok=True)


def _get_rate_db():
    """Retorna conexao SQLite para rate limiting."""
    conn = sqlite3.connect(str(_RATE_LIMIT_DB), timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""CREATE TABLE IF NOT EXISTS rate_limits (
        key TEXT NOT NULL,
        timestamp REAL NOT NULL
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rl_key_ts ON rate_limits(key, timestamp)")
    return conn


class RateLimiter:
    """Rate limiter por IP com sliding window persistido em SQLite."""

    def __init__(self, max_requests: int = 60, window_seconds: int = 60, prefix: str = ""):
        self.max_requests = max_requests
        self.window = window_seconds
        self.prefix = prefix

    def _key(self, ip: str) -> str:
        return f"{self.prefix}:{ip}" if self.prefix else ip

    def is_allowed(self, ip: str) -> bool:
        now = time.time()
        window_start = now - self.window
        key = self._key(ip)

        try:
            conn = _get_rate_db()
            try:
                # Limpa registros antigos
                conn.execute("DELETE FROM rate_limits WHERE key=? AND timestamp<=?", (key, window_start))
                # Conta requests na janela
                row = conn.execute(
                    "SELECT COUNT(*) FROM rate_limits WHERE key=? AND timestamp>?",
                    (key, window_start),
                ).fetchone()
                count = row[0] if row else 0

                if count >= self.max_requests:
                    conn.commit()
                    return False

                conn.execute("INSERT INTO rate_limits (key, timestamp) VALUES (?, ?)", (key, now))
                conn.commit()
                return True
            finally:
                conn.close()
        except sqlite3.OperationalError as e:
            logger.warning("Rate limiter DB error: %s", e)
            return True  # Falha aberta — nao bloqueia se DB falhar

    def remaining(self, ip: str) -> int:
        now = time.time()
        window_start = now - self.window
        key = self._key(ip)

        try:
            conn = _get_rate_db()
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM rate_limits WHERE key=? AND timestamp>?",
                    (key, window_start),
                ).fetchone()
                count = row[0] if row else 0
                return max(0, self.max_requests - count)
            finally:
                conn.close()
        except sqlite3.OperationalError:
            return self.max_requests


_rate_limiter = RateLimiter(max_requests=60, window_seconds=60, prefix="http")
_ws_rate_limiter = RateLimiter(max_requests=10, window_seconds=60, prefix="ws")


async def _rate_limit_dependency(request: Request) -> None:
    """FastAPI dependency para rate limiting."""
    client_ip = request.client.host if request.client else "unknown"
    if not _rate_limiter.is_allowed(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Rate limit excedido. Tente novamente em alguns segundos.",
            headers={"Retry-After": "60"},
        )
