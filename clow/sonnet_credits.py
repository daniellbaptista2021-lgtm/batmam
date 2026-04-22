"""
sonnet_credits.py — Sistema de créditos pré-pagos para acesso Sonnet 4 (System Clow)

Modelo:
- 3 pacotes (starter/pro/business) com preço e limites diário/semanal
- Créditos expiram em 90 dias
- Cobrança por mensagem real (custo calculado por input/output tokens)
- Janelas daily/weekly rolantes
"""

from __future__ import annotations
import time
import logging
from typing import Any, Optional
from .database import get_db
from . import config

logger = logging.getLogger("clow.sonnet")

# ===========================================================================
# Admin bypass — admins always have unlimited access
# ===========================================================================

def is_admin(user_id: str) -> bool:
    """Return True if the user is flagged is_admin=1 in users table."""
    try:
        with get_db() as db:
            row = db.execute("SELECT is_admin FROM users WHERE id=?", (user_id,)).fetchone()
        return bool(row and row[0])
    except Exception:
        return False


def _admin_balance() -> dict:
    return {
        "active": True,
        "has_credit": True,
        "package_id": "admin",
        "package_name": "Admin (ilimitado)",
        "balance_brl": 999999.0,
        "daily": {"used": 0, "limit": 999999, "remaining": 999999, "reset_in_seconds": 0},
        "weekly": {"used": 0, "limit": 999999, "remaining": 999999, "reset_in_seconds": 0},
        "expires_at": None,
        "days_until_expiry": 365000,
        "expiry_warning": False,
        "is_admin": True,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Pacotes disponíveis
# ═══════════════════════════════════════════════════════════════════════════

PACKAGES = {
    "basico": {
        "id": "basico",
        "name": "Sonnet Básico",
        "price_brl": 150.00,
        "credit_brl": 80.00,
        "daily_msgs": 80,
        "weekly_msgs": 400,
        "stripe_price_id": (config.STRIPE_PRICE_SONNET_BASICO or "price_1TNxlWD0ns2mNERrohLc9LKT"),
        "description": "R$80 em tokens GLM-5.1 — 80 msgs/dia, 400/semana — 90 dias",
    },
    "medio": {
        "id": "medio",
        "name": "Sonnet Médio",
        "price_brl": 250.00,
        "credit_brl": 180.00,
        "daily_msgs": 200,
        "weekly_msgs": 1000,
        "stripe_price_id": (config.STRIPE_PRICE_SONNET_MEDIO or "price_1TNxlXD0ns2mNERrCmbZypMl"),
        "description": "R$180 em tokens GLM-5.1 — 200 msgs/dia, 1000/semana — 90 dias",
    },
    "pro": {
        "id": "pro",
        "name": "Sonnet Pro",
        "price_brl": 350.00,
        "credit_brl": 280.00,
        "daily_msgs": 350,
        "weekly_msgs": 1750,
        "stripe_price_id": (config.STRIPE_PRICE_SONNET_PRO_PACK or "price_1TNxlYD0ns2mNERrwVYckz1t"),
        "description": "R$280 em tokens GLM-5.1 — 350 msgs/dia, 1750/semana — 90 dias",
    },
}

CREDIT_EXPIRY_DAYS = 90
WARNING_EXPIRY_DAYS = 15

# Pricing GLM-5.1 via OpenRouter em USD por 1M tokens (substituiu Sonnet)
# Ref: https://openrouter.ai/z-ai/glm-5.1
# Valores reais confirmados em 2026-04-19 (nao confundir com preco Sonnet)
SONNET_PRICING = {
    "input_miss_usd_per_1m": 0.95,   # input uncached (real GLM-5.1)
    "input_hit_usd_per_1m": 0.95,    # GLM nao tem prompt cache com desconto
    "output_usd_per_1m": 3.15,       # output (real GLM-5.1)
}
USD_TO_BRL = 6.0


# ═══════════════════════════════════════════════════════════════════════════
# Helpers de janelas temporais
# ═══════════════════════════════════════════════════════════════════════════

def _daily_window_start(ts: float = None) -> float:
    """Retorna início do dia atual (00:00 UTC)."""
    ts = ts or time.time()
    return int(ts - (ts % 86400))


def _weekly_window_start(ts: float = None) -> float:
    """Retorna início da semana rolante (7 dias incluindo hoje)."""
    ts = ts or time.time()
    today = _daily_window_start(ts)
    return today - (6 * 86400)


# ═══════════════════════════════════════════════════════════════════════════
# Cálculo de custo real
# ═══════════════════════════════════════════════════════════════════════════

def calculate_message_cost_brl(input_tokens: int, output_tokens: int, cache_hit_tokens: int = 0) -> float:
    input_miss = max(0, input_tokens - cache_hit_tokens)
    cost_usd = (
        input_miss * SONNET_PRICING["input_miss_usd_per_1m"] / 1_000_000
        + cache_hit_tokens * SONNET_PRICING["input_hit_usd_per_1m"] / 1_000_000
        + output_tokens * SONNET_PRICING["output_usd_per_1m"] / 1_000_000
    )
    return round(cost_usd * USD_TO_BRL, 4)


# ═══════════════════════════════════════════════════════════════════════════
# Saldo e limites
# ═══════════════════════════════════════════════════════════════════════════

def get_active_credit(user_id: str) -> Optional[dict]:
    now = time.time()
    with get_db() as db:
        row = db.execute(
            """SELECT id, package_id, credit_brl, daily_msgs_limit, weekly_msgs_limit,
                      purchased_at, expires_at, status
               FROM sonnet_credits
               WHERE user_id=? AND status='active' AND expires_at > ? AND credit_brl > 0
               ORDER BY purchased_at DESC LIMIT 1""",
            (user_id, now)
        ).fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "package_id": row[1],
        "balance_brl": round(row[2], 2),
        "daily_msgs_limit": row[3],
        "weekly_msgs_limit": row[4],
        "purchased_at": row[5],
        "expires_at": row[6],
        "days_until_expiry": int((row[6] - now) / 86400),
    }


def get_window_usage(user_id: str, window_type: str) -> dict:
    if window_type == "daily":
        start = _daily_window_start()
        duration_s = 86400
    elif window_type == "weekly":
        start = _weekly_window_start()
        duration_s = 7 * 86400
    else:
        raise ValueError(f"Invalid window_type: {window_type}")

    with get_db() as db:
        if window_type == "daily":
            row = db.execute(
                "SELECT messages_used, cost_brl FROM sonnet_usage_windows WHERE user_id=? AND window_type=? AND window_start=?",
                (user_id, window_type, start)
            ).fetchone()
            messages = row[0] if row else 0
            cost = row[1] if row else 0.0
        else:
            rows = db.execute(
                "SELECT SUM(messages_used), SUM(cost_brl) FROM sonnet_usage_windows WHERE user_id=? AND window_type=? AND window_start >= ?",
                (user_id, "daily", start)
            ).fetchone()
            messages = rows[0] or 0
            cost = rows[1] or 0.0

    return {
        "messages_used": int(messages),
        "cost_brl": round(float(cost), 4),
        "window_start": start,
        "window_end": start + duration_s,
        "seconds_until_reset": int(start + duration_s - time.time()),
    }


def get_balance(user_id: str) -> dict:
    if is_admin(user_id):
        return _admin_balance()
    credit = get_active_credit(user_id)
    if not credit:
        return {
            "active": False,
            "has_credit": False,
            "balance_brl": 0,
            "packages_available": list(PACKAGES.values()),
        }

    daily = get_window_usage(user_id, "daily")
    weekly = get_window_usage(user_id, "weekly")

    daily_remaining = max(0, credit["daily_msgs_limit"] - daily["messages_used"])
    weekly_remaining = max(0, credit["weekly_msgs_limit"] - weekly["messages_used"])

    return {
        "active": True,
        "has_credit": True,
        "package_id": credit["package_id"],
        "package_name": PACKAGES.get(credit["package_id"], {}).get("name", "Sonnet"),
        "balance_brl": credit["balance_brl"],
        "daily": {
            "used": daily["messages_used"],
            "limit": credit["daily_msgs_limit"],
            "remaining": daily_remaining,
            "reset_in_seconds": daily["seconds_until_reset"],
        },
        "weekly": {
            "used": weekly["messages_used"],
            "limit": credit["weekly_msgs_limit"],
            "remaining": weekly_remaining,
            "reset_in_seconds": weekly["seconds_until_reset"],
        },
        "expires_at": credit["expires_at"],
        "days_until_expiry": credit["days_until_expiry"],
        "expiry_warning": credit["days_until_expiry"] <= WARNING_EXPIRY_DAYS,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Validação antes de usar
# ═══════════════════════════════════════════════════════════════════════════

def check_can_use(user_id: str) -> dict:
    if is_admin(user_id):
        return {"allowed": True, "balance": _admin_balance(), "is_admin": True}
    balance = get_balance(user_id)

    if not balance["has_credit"]:
        return {
            "allowed": False,
            "reason": "no_credit",
            "message": "Voce nao tem creditos Sonnet 4. Compre um pacote para usar este modelo.",
            "packages": list(PACKAGES.values()),
        }

    if balance["daily"]["remaining"] <= 0:
        hours = balance["daily"]["reset_in_seconds"] // 3600
        return {
            "allowed": False,
            "reason": "daily_limit",
            "message": f"Limite diario atingido ({balance['daily']['limit']} mensagens). Reseta em {hours}h.",
            "reset_in_seconds": balance["daily"]["reset_in_seconds"],
        }

    if balance["weekly"]["remaining"] <= 0:
        days = balance["weekly"]["reset_in_seconds"] // 86400
        return {
            "allowed": False,
            "reason": "weekly_limit",
            "message": f"Limite semanal atingido ({balance['weekly']['limit']} mensagens). Reseta em {days} dias.",
            "reset_in_seconds": balance["weekly"]["reset_in_seconds"],
        }

    if balance["balance_brl"] <= 0:
        return {
            "allowed": False,
            "reason": "balance_zero",
            "message": "Seu saldo Sonnet 4 zerou. Compre um novo pacote.",
        }

    return {"allowed": True, "balance": balance}


# ═══════════════════════════════════════════════════════════════════════════
# Consumo após mensagem
# ═══════════════════════════════════════════════════════════════════════════

def record_message_usage(
    user_id: str,
    session_id: str,
    input_tokens: int,
    output_tokens: int,
    cache_hit_tokens: int = 0,
    model: str = "claude-sonnet-4",
) -> dict:
    if is_admin(user_id):
        return {"skipped": True, "reason": "admin", "cost_brl": 0.0, "balance_brl": 999999.0}
    cost_brl = calculate_message_cost_brl(input_tokens, output_tokens, cache_hit_tokens)
    now = time.time()
    daily_start = _daily_window_start(now)

    with get_db() as db:
        credit = db.execute(
            """SELECT id, credit_brl FROM sonnet_credits
               WHERE user_id=? AND status='active' AND expires_at > ? AND credit_brl > 0
               ORDER BY purchased_at DESC LIMIT 1""",
            (user_id, now)
        ).fetchone()

        if credit:
            new_balance = max(0, credit[1] - cost_brl)
            new_status = "exhausted" if new_balance <= 0 else "active"
            db.execute(
                "UPDATE sonnet_credits SET credit_brl=?, status=? WHERE id=?",
                (new_balance, new_status, credit[0])
            )

        db.execute(
            """INSERT INTO sonnet_usage_windows (user_id, window_type, window_start, messages_used, cost_brl)
               VALUES (?, 'daily', ?, 1, ?)
               ON CONFLICT(user_id, window_type, window_start)
               DO UPDATE SET messages_used=messages_used+1, cost_brl=cost_brl+?""",
            (user_id, daily_start, cost_brl, cost_brl)
        )

        db.execute(
            """INSERT INTO sonnet_message_log (user_id, session_id, timestamp, input_tokens, output_tokens, cost_brl, model)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, session_id, now, input_tokens, output_tokens, cost_brl, model)
        )
        db.commit()

    logger.info(f"[Sonnet] user={user_id} cost=R${cost_brl:.4f} tokens={input_tokens}/{output_tokens}")
    return {"cost_brl": cost_brl, "recorded_at": now}


# ═══════════════════════════════════════════════════════════════════════════
# Compra de pacote
# ═══════════════════════════════════════════════════════════════════════════

def create_checkout_session(user_id: str, email: str, package_id: str, success_url: str, cancel_url: str) -> dict:
    import stripe
    stripe.api_key = config.STRIPE_SECRET_KEY

    pkg = PACKAGES.get(package_id)
    if not pkg:
        raise ValueError(f"Invalid package: {package_id}")

    session = stripe.checkout.Session.create(
        mode="payment",
        payment_method_types=["card"],
        customer_email=email,
        line_items=[{"price": pkg["stripe_price_id"], "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={
            "user_id": user_id,
            "package_id": package_id,
            "product_type": "sonnet_credit",
        },
    )
    return {"id": session.id, "url": session.url}


def handle_stripe_payment_confirmed(session: dict) -> dict:
    metadata = session.get("metadata", {})
    user_id = metadata.get("user_id")
    package_id = metadata.get("package_id")
    product_type = metadata.get("product_type")

    if product_type != "sonnet_credit":
        return {"handled": False, "reason": "not a sonnet credit purchase"}

    pkg = PACKAGES.get(package_id)
    if not pkg or not user_id:
        return {"error": "invalid metadata"}

    now = time.time()
    expires_at = now + (CREDIT_EXPIRY_DAYS * 86400)

    with get_db() as db:
        db.execute(
            """INSERT INTO sonnet_credits
               (user_id, package_id, price_paid_brl, credit_brl, daily_msgs_limit, weekly_msgs_limit,
                purchased_at, expires_at, stripe_session_id, stripe_payment_intent, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')""",
            (
                user_id, package_id, pkg["price_brl"], pkg["credit_brl"],
                pkg["daily_msgs"], pkg["weekly_msgs"],
                now, expires_at,
                session.get("id"), session.get("payment_intent")
            )
        )
        db.execute("UPDATE users SET has_system_clow=1 WHERE id=?", (user_id,))
        db.commit()

    logger.info(f"[Sonnet] Credit purchased: user={user_id} package={package_id} credit=R${pkg['credit_brl']}")
    return {"handled": True, "user_id": user_id, "package_id": package_id, "credit_brl": pkg["credit_brl"]}
