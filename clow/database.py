"""Clow Database — SQLite ou PostgreSQL para users, usage e conversations.

Backend selecionado via env var CLOW_DB_BACKEND:
  - "sqlite" (default): arquivo local em data/clow.db
  - "postgres": PostgreSQL via DATABASE_URL
"""
from __future__ import annotations
import sqlite3
import hashlib
import hmac
import os
import time
import uuid
import json
from pathlib import Path
from contextlib import contextmanager

# ── Backend selection ──
_DB_BACKEND = os.getenv("CLOW_DB_BACKEND", "sqlite").lower()

DB_PATH = Path(__file__).parent.parent / "data" / "clow.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

if _DB_BACKEND == "postgres":
    from .db_postgres import get_db as _pg_get_db, init_db as _pg_init_db

# Planos pagos. Espelham billing.py (fonte de verdade para preço e limites).
PLANS = {
    "lite":      {"label": "ONE — R$ 139,90", "daily_tokens": 1_000_000},
    "starter":   {"label": "SMART — R$ 177,90", "daily_tokens": 1_800_000},
    "pro":       {"label": "PROFISSIONAL — R$ 289,90", "daily_tokens": 2_500_000},
    "business":  {"label": "BUSINESS — R$ 367,90", "daily_tokens": 3_000_000},
    "unlimited": {"label": "Admin", "daily_tokens": 0},
    "free":      {"label": "Gratuito", "daily_tokens": 500_000},
    "byok_free": {"label": "Gratuito", "daily_tokens": 500_000},
    "basic":     {"label": "Basico", "daily_tokens": 500_000},
}

# Admin email via env var (not hardcoded)
ADMIN_EMAIL = os.getenv("CLOW_ADMIN_EMAIL", "")


import queue as _queue
import threading as _threading

_DB_POOL_SIZE = int(os.getenv("CLOW_DB_POOL_SIZE", "5"))
_db_pool: _queue.Queue = _queue.Queue(maxsize=_DB_POOL_SIZE)
_db_pool_lock = _threading.Lock()
_db_pool_initialized = False


def _create_connection() -> sqlite3.Connection:
    """Create a new SQLite connection with optimal pragmas."""
    conn = sqlite3.connect(str(DB_PATH), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
    return conn


def _init_pool():
    """Initialize the connection pool."""
    global _db_pool_initialized
    with _db_pool_lock:
        if _db_pool_initialized:
            return
        for _ in range(_DB_POOL_SIZE):
            try:
                _db_pool.put_nowait(_create_connection())
            except _queue.Full:
                break
        _db_pool_initialized = True


@contextmanager
def _sqlite_get_db():
    _init_pool()
    conn = None
    try:
        conn = _db_pool.get(timeout=10)
    except _queue.Empty:
        conn = _create_connection()

    try:
        yield conn
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        if conn is not None:
            try:
                conn.execute("SELECT 1")
                _db_pool.put_nowait(conn)
            except (_queue.Full, Exception):
                try:
                    conn.close()
                except Exception:
                    pass


@contextmanager
def get_db():
    """Get database connection (SQLite or PostgreSQL based on CLOW_DB_BACKEND)."""
    if _DB_BACKEND == "postgres":
        with _pg_get_db() as conn:
            yield conn
    else:
        with _sqlite_get_db() as conn:
            yield conn


def init_db():
    """Inicializa o banco via migrations (SQLite ou PostgreSQL)."""
    if _DB_BACKEND == "postgres":
        _pg_init_db()
    else:
        from .migrations import run_migrations
        run_migrations()


# ── Users ────────────────────────────────────────────────────────

def _hash_pw(password: str, salt: str = "") -> str:
    """Hash password with PBKDF2-SHA256 + random salt."""
    if not salt:
        salt = os.urandom(16).hex()
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return f"{salt}${dk.hex()}"


def _verify_pw(password: str, stored_hash: str) -> bool:
    """Verify password against stored PBKDF2 hash. Supports legacy SHA-256."""
    if "$" in stored_hash:
        # New format: salt$hash
        salt, _ = stored_hash.split("$", 1)
        return hmac.compare_digest(_hash_pw(password, salt), stored_hash)
    else:
        # Legacy SHA-256 (no salt) — migrate on next login
        return hmac.compare_digest(hashlib.sha256(password.encode()).hexdigest(), stored_hash)


def create_user(email: str, password: str, name: str = "") -> dict | None:
    uid = str(uuid.uuid4())[:12]
    now = time.time()
    is_admin = 1 if email.lower() == ADMIN_EMAIL else 0
    plan = "unlimited" if is_admin else "lite"
    try:
        with get_db() as db:
            db.execute(
                "INSERT INTO users (id, email, password_hash, name, plan, is_admin, created_at) VALUES (?,?,?,?,?,?,?)",
                (uid, email.lower(), _hash_pw(password), name, plan, is_admin, now),
            )
        return {"id": uid, "email": email.lower(), "plan": plan, "is_admin": bool(is_admin)}
    except sqlite3.IntegrityError:
        return None


def authenticate_user(email: str, password: str) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM users WHERE email=?", (email.lower(),)).fetchone()
        if not row:
            return None
        if not _verify_pw(password, row["password_hash"]):
            return None
        if not row["active"]:
            return None
        # Migrate legacy SHA-256 hash to PBKDF2 on successful login
        if "$" not in row["password_hash"]:
            db.execute("UPDATE users SET password_hash=? WHERE id=?", (_hash_pw(password), row["id"]))
        db.execute("UPDATE users SET last_login=? WHERE id=?", (time.time(), row["id"]))
        return dict(row)


def get_user_by_email(email: str) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM users WHERE email=?", (email.lower(),)).fetchone()
        return dict(row) if row else None


def get_user_by_id(uid: str) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        return dict(row) if row else None


def list_users() -> list[dict]:
    with get_db() as db:
        rows = db.execute("SELECT id, email, name, plan, active, is_admin, created_at, last_login FROM users ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


def _migrate_byok_columns():
    """Adiciona colunas BYOK se nao existem."""
    try:
        with get_db() as db:
            cols = [r[1] for r in db.execute("PRAGMA table_info(users)").fetchall()]
            if "anthropic_api_key" not in cols:
                db.execute("ALTER TABLE users ADD COLUMN anthropic_api_key TEXT DEFAULT ''")
            if "byok_enabled" not in cols:
                db.execute("ALTER TABLE users ADD COLUMN byok_enabled INTEGER DEFAULT 0")
            if "api_key_set_at" not in cols:
                db.execute("ALTER TABLE users ADD COLUMN api_key_set_at REAL DEFAULT 0")
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("BYOK columns migration failed: %s", e)


# Roda migration na importacao
_migrate_byok_columns()


def set_user_api_key(uid: str, api_key: str) -> bool:
    """Salva API key do usuario (BYOK)."""
    with get_db() as db:
        db.execute(
            "UPDATE users SET anthropic_api_key=?, byok_enabled=1, api_key_set_at=? WHERE id=?",
            (api_key, time.time(), uid),
        )
        return db.total_changes > 0


def get_user_api_key(uid: str) -> str:
    """Retorna API key do usuario ou string vazia."""
    with get_db() as db:
        row = db.execute("SELECT anthropic_api_key FROM users WHERE id=?", (uid,)).fetchone()
        return row["anthropic_api_key"] if row and row["anthropic_api_key"] else ""


def remove_user_api_key(uid: str) -> bool:
    """Remove API key do usuario."""
    with get_db() as db:
        db.execute(
            "UPDATE users SET anthropic_api_key='', byok_enabled=0 WHERE id=?",
            (uid,),
        )
        return db.total_changes > 0


def validate_deepseek_key(api_key: str) -> dict:
    """Valida uma API key da DeepSeek com chamada real.

    Faz uma requisicao minima (1 token) para garantir que a key e valida.
    """
    if not api_key:
        return {"valid": False, "error": "API key vazia"}

    try:
        from openai import OpenAI
        from . import config
        base = config.DEEPSEEK_BASE_URL.rstrip("/")
        if not base.endswith("/v1"):
            base += "/v1"
        client = OpenAI(api_key=api_key, base_url=base)
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
        )
        return {"valid": True, "model": "deepseek-chat"}
    except Exception as e:
        err = str(e).lower()
        if "401" in err or "authentication" in err or "invalid x-api-key" in err or "invalid api key" in err:
            return {
                "valid": False,
                "error": "API key invalida. Verifique se copiou corretamente em platform.deepseek.com",
            }
        if "credit" in err or "billing" in err or "balance" in err:
            return {
                "valid": False,
                "error": "Sua conta DeepSeek esta sem saldo. Adicione creditos em platform.deepseek.com",
            }
        if "permission" in err or "forbidden" in err:
            return {
                "valid": False,
                "error": "Sua key nao tem permissao. Gere uma nova key com acesso completo em platform.deepseek.com",
            }
        if "rate" in err or "429" in str(e):
            # Rate limit = key valida, so esta sendo usada rapido demais
            return {"valid": True, "model": "deepseek-chat"}
        return {
            "valid": False,
            "error": f"Erro ao validar: {str(e)[:150]}. Verifique sua key e tente novamente.",
        }


def update_user(uid: str, **kwargs) -> bool:
    _ALLOWED_USER_FIELDS = {"name", "plan", "active", "is_admin"}
    fields = {k: v for k, v in kwargs.items() if k in _ALLOWED_USER_FIELDS}
    if not fields:
        return False
    # Build SET clause safely — field names come from hardcoded whitelist only
    set_parts = []
    vals = []
    for field_name in sorted(fields):
        set_parts.append(f"{field_name}=?")
        vals.append(fields[field_name])
    vals.append(uid)
    sql = "UPDATE users SET " + ", ".join(set_parts) + " WHERE id=?"
    with get_db() as db:
        db.execute(sql, vals)
    return True


# ── Usage ────────────────────────────────────────────────────────

def log_usage(user_id: str, model: str, input_tokens: int, output_tokens: int, cost_usd: float = 0, action: str = "chat"):
    with get_db() as db:
        db.execute(
            "INSERT INTO usage_log (user_id, model, input_tokens, output_tokens, cost_usd, action, created_at) VALUES (?,?,?,?,?,?,?)",
            (user_id, model, input_tokens, output_tokens, cost_usd, action, time.time()),
        )


def get_user_usage_today(user_id: str) -> dict:
    start_of_day = time.time() - (time.time() % 86400)
    with get_db() as db:
        row = db.execute(
            "SELECT COALESCE(SUM(input_tokens+output_tokens),0) as total_tokens, COALESCE(SUM(cost_usd),0) as total_cost, COUNT(*) as requests FROM usage_log WHERE user_id=? AND created_at>=?",
            (user_id, start_of_day),
        ).fetchone()
        return dict(row)


def count_user_messages_today(user_id: str) -> int:
    """Conta mensagens enviadas pelo usuario hoje (role='user' nas conversas dele)."""
    start = time.time() - (time.time() % 86400)
    with get_db() as db:
        row = db.execute(
            """SELECT COUNT(*) FROM messages m
               JOIN conversations c ON m.conversation_id = c.id
               WHERE c.user_id=? AND m.role='user' AND m.created_at>=?""",
            (user_id, start),
        ).fetchone()
    return row[0] if row else 0


def count_user_messages_week(user_id: str) -> int:
    """Conta mensagens enviadas pelo usuario nos ultimos 7 dias."""
    start = time.time() - 7 * 86400
    with get_db() as db:
        row = db.execute(
            """SELECT COUNT(*) FROM messages m
               JOIN conversations c ON m.conversation_id = c.id
               WHERE c.user_id=? AND m.role='user' AND m.created_at>=?""",
            (user_id, start),
        ).fetchone()
    return row[0] if row else 0


# Ensure payment_status column exists
def _ensure_payment_status():
    try:
        with get_db() as db:
            db.execute("ALTER TABLE users ADD COLUMN payment_status TEXT DEFAULT 'ok'")
    except Exception:
        pass

_ensure_payment_status()


def check_message_limit(user_id: str) -> tuple[bool, str]:
    """Verifica limite diario e semanal de mensagens por usuario.

    Retorna (permitido, motivo). Limites configurados via CLOW_DAILY_LIMIT
    e CLOW_WEEKLY_LIMIT no .env. Valor 0 significa sem limite.
    """
    from . import config
    daily_limit = config.CLOW_DAILY_LIMIT
    weekly_limit = config.CLOW_WEEKLY_LIMIT

    if daily_limit <= 0 and weekly_limit <= 0:
        return True, ""

    if daily_limit > 0:
        daily_used = count_user_messages_today(user_id)
        if daily_used >= daily_limit:
            return False, (
                f"Voce atingiu seu limite de {daily_limit} mensagens hoje. "
                "Volte amanha para continuar!"
            )

    if weekly_limit > 0:
        weekly_used = count_user_messages_week(user_id)
        if weekly_used >= weekly_limit:
            return False, (
                f"Voce atingiu seu limite de {weekly_limit} mensagens esta semana. "
                "Volte na proxima semana!"
            )

    return True, ""


def check_limit(user_id: str) -> tuple[bool, float]:
    """Retorna (allowed, pct_used)."""
    user = get_user_by_id(user_id)
    if not user:
        return False, 1.0
    plan = PLANS.get(user.get("plan", "lite"), PLANS.get("lite", {"daily_tokens": 500000}))
    limit = plan["daily_tokens"]
    if limit == 0:
        return True, 0.0
    usage = get_user_usage_today(user_id)
    used = usage["total_tokens"]
    pct = used / limit if limit > 0 else 0
    return pct < 1.0, pct


def get_admin_stats() -> dict:
    now = time.time()
    day_start = now - (now % 86400)
    week_start = now - 7 * 86400
    month_start = now - 30 * 86400

    with get_db() as db:
        total_users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        active_users = db.execute("SELECT COUNT(*) FROM users WHERE active=1").fetchone()[0]

        day_cost = db.execute("SELECT COALESCE(SUM(cost_usd),0) FROM usage_log WHERE created_at>=?", (day_start,)).fetchone()[0]
        week_cost = db.execute("SELECT COALESCE(SUM(cost_usd),0) FROM usage_log WHERE created_at>=?", (week_start,)).fetchone()[0]
        month_cost = db.execute("SELECT COALESCE(SUM(cost_usd),0) FROM usage_log WHERE created_at>=?", (month_start,)).fetchone()[0]

        day_tokens = db.execute("SELECT COALESCE(SUM(input_tokens+output_tokens),0) FROM usage_log WHERE created_at>=?", (day_start,)).fetchone()[0]

        top_users = db.execute("""
            SELECT u.email, u.plan, SUM(l.input_tokens+l.output_tokens) as tokens, SUM(l.cost_usd) as cost
            FROM usage_log l JOIN users u ON l.user_id=u.id
            WHERE l.created_at>=?
            GROUP BY l.user_id ORDER BY tokens DESC LIMIT 10
        """, (day_start,)).fetchall()

    return {
        "total_users": total_users,
        "active_users": active_users,
        "cost_today": day_cost,
        "cost_week": week_cost,
        "cost_month": month_cost,
        "tokens_today": day_tokens,
        "top_users_today": [dict(r) for r in top_users],
    }


# ── Conversations ────────────────────────────────────────────────

def create_conversation(user_id: str, title: str = "Nova conversa") -> str:
    cid = str(uuid.uuid4())[:12]
    now = time.time()
    with get_db() as db:
        db.execute("INSERT INTO conversations (id, user_id, title, created_at, updated_at) VALUES (?,?,?,?,?)",
            (cid, user_id, title[:100], now, now))
    return cid


def list_conversations(user_id: str, limit: int = 30) -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT id, title, created_at, updated_at FROM conversations WHERE user_id=? ORDER BY updated_at DESC LIMIT ?",
            (user_id, limit)).fetchall()
    return [dict(r) for r in rows]


def delete_conversation(user_id: str, conv_id: str) -> bool:
    with get_db() as db:
        db.execute("DELETE FROM messages WHERE conversation_id=?", (conv_id,))
        r = db.execute("DELETE FROM conversations WHERE id=? AND user_id=?", (conv_id, user_id))
    return r.rowcount > 0


def save_message(conv_id: str, role: str, content: str, file_data: dict = None):
    with get_db() as db:
        db.execute("INSERT INTO messages (conversation_id, role, content, file_data, created_at) VALUES (?,?,?,?,?)",
            (conv_id, role, content, json.dumps(file_data) if file_data else None, time.time()))
        db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (time.time(), conv_id))


def get_messages(conv_id: str, limit: int = 100) -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT role, content, file_data, created_at FROM messages WHERE conversation_id=? ORDER BY created_at ASC LIMIT ?",
            (conv_id, limit)).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        if d["file_data"]:
            d["file_data"] = json.loads(d["file_data"])
        result.append(d)
    return result


def update_conversation_title(conv_id: str, title: str):
    with get_db() as db:
        db.execute("UPDATE conversations SET title=? WHERE id=?", (title[:100], conv_id))


# ── Missions ─────────────────────────────────────────────────────

def create_mission(user_id: str, title: str, description: str, plan: list[dict]) -> str:
    mid = str(uuid.uuid4())[:12]
    now = time.time()
    with get_db() as db:
        db.execute(
            "INSERT INTO missions (id, user_id, title, description, status, plan_json, total_steps, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (mid, user_id, title, description, "planning", json.dumps(plan), len(plan), now, now),
        )
        for i, step in enumerate(plan):
            db.execute(
                "INSERT INTO mission_steps (mission_id, step_number, title, description, model) VALUES (?,?,?,?,?)",
                (mid, i, step.get("title", f"Etapa {i+1}"), step.get("description", ""), step.get("model", "haiku")),
            )
    return mid


def get_mission(mission_id: str) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM missions WHERE id=?", (mission_id,)).fetchone()
        if not row:
            return None
        m = dict(row)
        m["plan"] = json.loads(m["plan_json"] or "[]")
        m["context"] = json.loads(m["context_json"] or "{}")
        steps = db.execute("SELECT * FROM mission_steps WHERE mission_id=? ORDER BY step_number", (mission_id,)).fetchall()
        m["steps"] = [dict(s) for s in steps]
        return m


def update_mission(mission_id: str, **kwargs):
    _ALLOWED = {"status", "current_step", "error_count", "context_json", "completed_at", "updated_at"}
    fields = {k: v for k, v in kwargs.items() if k in _ALLOWED}
    if not fields:
        return
    fields["updated_at"] = time.time()
    set_parts = []
    vals = []
    for field_name in sorted(fields):
        set_parts.append(f"{field_name}=?")
        vals.append(fields[field_name])
    vals.append(mission_id)
    sql = "UPDATE missions SET " + ", ".join(set_parts) + " WHERE id=?"
    with get_db() as db:
        db.execute(sql, vals)


def update_mission_step(mission_id: str, step_number: int, **kwargs):
    _ALLOWED = {"status", "result_json", "error", "attempts", "started_at", "completed_at"}
    fields = {k: v for k, v in kwargs.items() if k in _ALLOWED}
    if not fields:
        return
    set_parts = []
    vals = []
    for field_name in sorted(fields):
        set_parts.append(f"{field_name}=?")
        vals.append(fields[field_name])
    vals.extend([mission_id, step_number])
    sql = "UPDATE mission_steps SET " + ", ".join(set_parts) + " WHERE mission_id=? AND step_number=?"
    with get_db() as db:
        db.execute(sql, vals)


def list_missions(user_id: str, limit: int = 20) -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT id, title, status, current_step, total_steps, created_at, completed_at FROM missions WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit)).fetchall()
    return [dict(r) for r in rows]


# ── Chatwoot multi-tenant connections ─────────────────────────────

def get_chatwoot_connection_by_user(user_id: str) -> dict | None:
    """Return the active Chatwoot connection for a given Clow user, or None."""
    if not user_id:
        return None
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM chatwoot_connections WHERE user_id=? AND active=1 ORDER BY connected_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None


def get_chatwoot_connection_by_webhook(webhook_token: str) -> dict | None:
    """Lookup a connection by webhook_token (used by webhook handlers)."""
    if not webhook_token:
        return None
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM chatwoot_connections WHERE webhook_token=? AND active=1 LIMIT 1",
            (webhook_token,),
        ).fetchone()
        return dict(row) if row else None


def create_chatwoot_connection(*, user_id: str, chatwoot_url: str,
                                chatwoot_token: str, chatwoot_account_id: int,
                                webhook_token: str = "",
                                chatwoot_user_token: str = "",
                                chatwoot_user_id: int = 0,
                                chatwoot_password_temp: str = "") -> dict:
    """Create a Chatwoot connection row tied to a Clow user."""
    if not user_id:
        raise ValueError("user_id is required")
    if not chatwoot_account_id:
        raise ValueError("chatwoot_account_id is required and must be non-zero")
    cid = str(uuid.uuid4())[:12]
    now = time.time()
    wh = webhook_token or secrets_token_safe(24)
    with get_db() as db:
        db.execute(
            """INSERT INTO chatwoot_connections
                  (id, user_id, chatwoot_url, chatwoot_token, chatwoot_account_id,
                   webhook_token, webhook_id, active, connected_at,
                   chatwoot_user_token, chatwoot_user_id, chatwoot_password_temp)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (cid, user_id, chatwoot_url, chatwoot_token, int(chatwoot_account_id),
             wh, 0, 1, now,
             chatwoot_user_token or chatwoot_token, int(chatwoot_user_id), chatwoot_password_temp),
        )
    return get_chatwoot_connection_by_user(user_id)


def update_chatwoot_connection(user_id: str, **kwargs) -> bool:
    """Update mutable fields of a user's Chatwoot connection."""
    _ALLOWED = {
        "chatwoot_url", "chatwoot_token", "chatwoot_account_id",
        "chatwoot_user_token", "chatwoot_user_id", "chatwoot_password_temp",
        "webhook_id", "active", "evolution_instance",
        "password_delivered_at", "connection_mode", "is_remote",
    }
    fields = {k: v for k, v in kwargs.items() if k in _ALLOWED}
    if not fields:
        return False
    set_parts = []
    vals = []
    for fname in sorted(fields):
        set_parts.append(f"{fname}=?")
        vals.append(fields[fname])
    vals.append(user_id)
    sql = "UPDATE chatwoot_connections SET " + ", ".join(set_parts) + " WHERE user_id=?"
    with get_db() as db:
        db.execute(sql, vals)
    return True


def mark_chatwoot_password_delivered(user_id: str) -> bool:
    """Flag that the one-time login/password has been shown to the customer
    and clear the temporary password from storage."""
    with get_db() as db:
        db.execute(
            "UPDATE chatwoot_connections SET password_delivered_at=?, chatwoot_password_temp='' WHERE user_id=?",
            (time.time(), user_id),
        )
    return True


def secrets_token_safe(nbytes: int = 24) -> str:
    """Local helper to avoid importing secrets at module top (kept for clarity)."""
    import secrets as _s
    return _s.token_urlsafe(nbytes)


# ── WhatsApp credentials (per-user, per-channel) ──────────────────

def get_whatsapp_credentials(user_id: str) -> dict | None:
    """Return the most recently updated WhatsApp credentials row for the user."""
    if not user_id:
        return None
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM whatsapp_credentials WHERE user_id=? ORDER BY updated_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None


def save_whatsapp_credentials(user_id: str, ctype: str, data: dict) -> dict:
    """Upsert WhatsApp credentials for a user. ctype = 'zapi' | 'meta'."""
    if not user_id:
        raise ValueError("user_id is required")
    if ctype not in ("zapi", "meta"):
        raise ValueError("ctype must be 'zapi' or 'meta'")
    now = time.time()
    existing = get_whatsapp_credentials(user_id)
    payload = {
        "instance_id": data.get("instance_id", ""),
        "token": data.get("token", ""),
        "phone_number_id": data.get("phone_number_id", ""),
        "access_token": data.get("access_token", ""),
        "status": data.get("status", "pending"),
        "chatwoot_inbox_id": int(data.get("chatwoot_inbox_id", 0) or 0),
        "webhook_token": data.get("webhook_token", ""),
    }
    with get_db() as db:
        if existing:
            db.execute(
                """UPDATE whatsapp_credentials
                      SET type=?, instance_id=?, token=?, phone_number_id=?, access_token=?,
                          status=?, chatwoot_inbox_id=?, webhook_token=?, updated_at=?
                    WHERE user_id=?""",
                (ctype, payload["instance_id"], payload["token"], payload["phone_number_id"],
                 payload["access_token"], payload["status"], payload["chatwoot_inbox_id"],
                 payload["webhook_token"], now, user_id),
            )
        else:
            db.execute(
                """INSERT INTO whatsapp_credentials
                      (id, user_id, type, instance_id, token, phone_number_id, access_token,
                       status, created_at, updated_at, chatwoot_inbox_id, webhook_token)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (str(uuid.uuid4())[:12], user_id, ctype, payload["instance_id"], payload["token"],
                 payload["phone_number_id"], payload["access_token"], payload["status"],
                 now, now, payload["chatwoot_inbox_id"], payload["webhook_token"]),
            )
    return get_whatsapp_credentials(user_id)


# ── Chatwoot bot configs (per-inbox, owned by user) ───────────────

def list_chatwoot_bot_configs(user_id: str = "") -> list[dict]:
    """List bot configs. If user_id is provided, scope to that user only."""
    with get_db() as db:
        if user_id:
            rows = db.execute(
                "SELECT * FROM chatwoot_bot_configs WHERE user_id=? ORDER BY id DESC",
                (user_id,),
            ).fetchall()
        else:
            rows = db.execute("SELECT * FROM chatwoot_bot_configs ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


def get_chatwoot_bot_config(inbox_id: int, user_id: str = "") -> dict | None:
    """Get bot config for an inbox. If user_id given, enforce ownership."""
    with get_db() as db:
        if user_id:
            row = db.execute(
                "SELECT * FROM chatwoot_bot_configs WHERE inbox_id=? AND user_id=? LIMIT 1",
                (int(inbox_id), user_id),
            ).fetchone()
        else:
            row = db.execute(
                "SELECT * FROM chatwoot_bot_configs WHERE inbox_id=? LIMIT 1",
                (int(inbox_id),),
            ).fetchone()
        return dict(row) if row else None


def upsert_chatwoot_bot_config(*, inbox_id: int, inbox_name: str = "",
                                system_prompt: str = "", active: bool = True,
                                model: str = "deepseek-chat",
                                human_handoff: bool = True,
                                user_id: str = "",
                                max_tokens: int = 1024,
                                context_size: int = 20) -> dict:
    """Insert or update a per-inbox bot config row."""
    if not inbox_id:
        raise ValueError("inbox_id is required")
    now = time.time()
    with get_db() as db:
        existing = db.execute(
            "SELECT id FROM chatwoot_bot_configs WHERE inbox_id=? LIMIT 1",
            (int(inbox_id),),
        ).fetchone()
        if existing:
            db.execute(
                """UPDATE chatwoot_bot_configs
                      SET inbox_name=?, system_prompt=?, active=?, model=?,
                          max_tokens=?, context_size=?, human_handoff=?, user_id=?, updated_at=?
                    WHERE inbox_id=?""",
                (inbox_name, system_prompt, 1 if active else 0, model,
                 int(max_tokens), int(context_size), 1 if human_handoff else 0,
                 user_id, now, int(inbox_id)),
            )
        else:
            db.execute(
                """INSERT INTO chatwoot_bot_configs
                      (inbox_id, inbox_name, system_prompt, active, model,
                       max_tokens, context_size, created_at, updated_at, human_handoff, user_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (int(inbox_id), inbox_name, system_prompt, 1 if active else 0, model,
                 int(max_tokens), int(context_size), now, now,
                 1 if human_handoff else 0, user_id),
            )
    return get_chatwoot_bot_config(int(inbox_id))


# Init on import
init_db()

# Create admin from env vars on first run (no hardcoded credentials)
_admin_email = os.getenv("CLOW_ADMIN_EMAIL", "")
_admin_pass = os.getenv("CLOW_ADMIN_PASSWORD", "")
if _admin_email and _admin_pass and not get_user_by_email(_admin_email):
    create_user(_admin_email, _admin_pass, "Admin")
del _admin_email, _admin_pass


# ═══════════════════════════════════════════════════════════════════════════
# Delete user com cascade (descobre tabelas com user_id automaticamente)
# Tambem chama Chatwoot Platform API pra deletar a Account isolada se existir
# ═══════════════════════════════════════════════════════════════════════════

def delete_user_cascade(user_id: str) -> dict:
    """Deleta user + todos os dados relacionados em tabelas com coluna user_id.
    Tambem deleta a Account isolada no Chatwoot via Platform API.
    Retorna {ok, tables_cleaned, chatwoot_account_deleted}.
    """
    import os, urllib.request, urllib.error, json as _j, logging
    log = logging.getLogger("clow.database")
    if not user_id:
        return {"ok": False, "error": "user_id vazio"}

    cleaned = []
    cw_account_id = None
    cw_deleted = False

    with get_db() as db:
        # Captura chatwoot_account_id antes de deletar (pra limpar no Chatwoot)
        try:
            row = db.execute(
                "SELECT chatwoot_account_id FROM chatwoot_connections WHERE user_id=? LIMIT 1",
                (user_id,)
            ).fetchone()
            if row and row[0]:
                cw_account_id = int(row[0])
        except Exception as _e:
            log.warning("delete_user_cascade: lookup chatwoot_account failed: %s", _e)

        # Descobre todas as tabelas que tem coluna user_id
        try:
            tables = [r[0] for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()]
        except Exception as _e:
            return {"ok": False, "error": "list_tables_failed: " + str(_e)}

        for t in tables:
            if t == "users":
                continue
            try:
                cols = [c[1] for c in db.execute("PRAGMA table_info(" + t + ")").fetchall()]
            except Exception:
                continue
            if "user_id" in cols:
                try:
                    cur = db.execute("DELETE FROM " + t + " WHERE user_id=?", (user_id,))
                    if cur.rowcount > 0:
                        cleaned.append({"table": t, "rows": cur.rowcount})
                except Exception as _e:
                    log.warning("delete_user_cascade: failed to clean %s: %s", t, _e)

        # Deleta o user
        try:
            cur = db.execute("DELETE FROM users WHERE id=?", (user_id,))
            db.commit()
            if cur.rowcount == 0:
                return {"ok": False, "error": "user_not_found", "tables_cleaned": cleaned}
        except Exception as _e:
            return {"ok": False, "error": "delete_user_failed: " + str(_e), "tables_cleaned": cleaned}

    # Cleanup remoto: Chatwoot Platform API DELETE /platform/api/v1/accounts/{id}
    if cw_account_id and cw_account_id != 1:
        cw_url = os.getenv("CHATWOOT_URL", "").rstrip("/")
        token = os.getenv("CHATWOOT_PLATFORM_TOKEN", "")
        if cw_url and token:
            try:
                req = urllib.request.Request(
                    cw_url + "/platform/api/v1/accounts/" + str(cw_account_id),
                    method="DELETE",
                    headers={"api_access_token": token},
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    if resp.status in (200, 204):
                        cw_deleted = True
            except urllib.error.HTTPError as _e:
                log.warning("delete_user_cascade: chatwoot account DELETE %s -> %s", cw_account_id, _e.code)
            except Exception as _e:
                log.warning("delete_user_cascade: chatwoot account DELETE exception: %s", _e)

    return {
        "ok": True,
        "tables_cleaned": cleaned,
        "chatwoot_account_id": cw_account_id,
        "chatwoot_account_deleted": cw_deleted,
    }

