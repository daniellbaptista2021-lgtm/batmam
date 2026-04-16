"""Clow Database — SQLite para users, usage e conversations."""
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

DB_PATH = Path(__file__).parent.parent / "data" / "clow.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# Planos pagos (sem plano gratuito). Planos reais em billing.py
PLANS = {
    "lite": {"label": "Lite — R$169", "daily_tokens": 1_800_000},
    "starter": {"label": "Starter — R$298", "daily_tokens": 2_150_000},
    "pro": {"label": "Pro — R$487", "daily_tokens": 3_000_000},
    "business": {"label": "Business — R$667", "daily_tokens": 4_800_000},
    "unlimited": {"label": "Admin", "daily_tokens": 0},
    "free": {"label": "Gratuito", "daily_tokens": 500_000},
    "byok_free": {"label": "Gratuito", "daily_tokens": 500_000},
    "basic": {"label": "Basico", "daily_tokens": 500_000},
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
def get_db():
    _init_pool()
    conn = None
    try:
        conn = _db_pool.get(timeout=10)
    except _queue.Empty:
        # Pool exhausted — create a temporary connection
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
                # Test if connection is still valid before returning to pool
                conn.execute("SELECT 1")
                _db_pool.put_nowait(conn)
            except (_queue.Full, Exception):
                try:
                    conn.close()
                except Exception:
                    pass


def init_db():
    """Inicializa o banco via migrations.py (schema centralizado)."""
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


# Init on import
init_db()

# Create admin from env vars on first run (no hardcoded credentials)
_admin_email = os.getenv("CLOW_ADMIN_EMAIL", "")
_admin_pass = os.getenv("CLOW_ADMIN_PASSWORD", "")
if _admin_email and _admin_pass and not get_user_by_email(_admin_email):
    create_user(_admin_email, _admin_pass, "Admin")
del _admin_email, _admin_pass
