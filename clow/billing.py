"""Stripe Billing — planos, checkout, portal, webhook, franquia.

Planos:
- BYOK_FREE: R$0, user usa propria API key
- LITE: R$89/mes, Haiku 4.5, franquia diaria 200K in + 50K out
- STARTER: R$115/mes, Sonnet 4, franquia diaria 500K in + 100K out, 8 fluxos n8n
- PRO: R$189/mes, Sonnet 4, franquia diaria 1M in + 200K out, 2000 fluxos
- BUSINESS: R$229/mes, Sonnet 4, franquia diaria 2M in + 400K out, 3000 fluxos
"""

from __future__ import annotations
import json
import os
import time
from typing import Any

from . import config
from .logging import log_action

# ── Plan Definitions ──────────────────────────────────────────

PLANS = {
    "byok_free": {
        "name": "Traga sua Key",
        "price_brl": 0,
        "model": "claude-sonnet-4-20250514",
        "uses_server_key": False,
        "daily_input_tokens": 0,   # 0 = sem limite nosso
        "daily_output_tokens": 0,
        "weekly_input_tokens": 0,
        "weekly_output_tokens": 0,
        "n8n_flows": 0,
        "stripe_price_id": "",
    },
    "lite": {
        "name": "Lite",
        "price_brl": 89,
        "model": "claude-haiku-4-5-20251001",
        "uses_server_key": True,
        "daily_input_tokens": 200_000,
        "daily_output_tokens": 50_000,
        "weekly_input_tokens": 1_000_000,
        "weekly_output_tokens": 250_000,
        "n8n_flows": 0,
        "stripe_price_id": config.STRIPE_LITE_PRICE_ID,
    },
    "starter": {
        "name": "Starter",
        "price_brl": 115,
        "model": "claude-sonnet-4-20250514",
        "uses_server_key": True,
        "daily_input_tokens": 500_000,
        "daily_output_tokens": 100_000,
        "weekly_input_tokens": 2_500_000,
        "weekly_output_tokens": 500_000,
        "n8n_flows": 8,
        "stripe_price_id": config.STRIPE_STARTER_PRICE_ID,
    },
    "pro": {
        "name": "Pro",
        "price_brl": 189,
        "model": "claude-sonnet-4-20250514",
        "uses_server_key": True,
        "daily_input_tokens": 1_000_000,
        "daily_output_tokens": 200_000,
        "weekly_input_tokens": 5_000_000,
        "weekly_output_tokens": 1_000_000,
        "n8n_flows": 2000,
        "stripe_price_id": config.STRIPE_PRO_PRICE_ID,
    },
    "business": {
        "name": "Business",
        "price_brl": 229,
        "model": "claude-sonnet-4-20250514",
        "uses_server_key": True,
        "daily_input_tokens": 2_000_000,
        "daily_output_tokens": 400_000,
        "weekly_input_tokens": 10_000_000,
        "weekly_output_tokens": 2_000_000,
        "n8n_flows": 3000,
        "stripe_price_id": config.STRIPE_BUSINESS_PRICE_ID,
    },
}

PRICE_ID_TO_PLAN = {v["stripe_price_id"]: k for k, v in PLANS.items() if v["stripe_price_id"]}


def get_plan(plan_id: str) -> dict:
    """Retorna config do plano. Default: byok_free."""
    return PLANS.get(plan_id, PLANS["byok_free"])


def get_model_for_plan(plan_id: str) -> str:
    """Retorna model ID correto para o plano."""
    return get_plan(plan_id)["model"]


def plan_uses_server_key(plan_id: str) -> bool:
    """Retorna se o plano usa a API key do servidor."""
    return get_plan(plan_id)["uses_server_key"]


# ── Quota Checking ────────────────────────────────────────────

def check_quota(user_id: str, plan_id: str) -> dict[str, Any]:
    """Verifica se o user ainda tem franquia disponivel.

    Returns dict com allowed=True/False e detalhes.
    """
    plan = get_plan(plan_id)

    # BYOK nao tem limite nosso
    if not plan["uses_server_key"]:
        return {"allowed": True, "plan": plan_id}

    from .database import get_db

    now = time.time()
    today_start = now - (now % 86400)
    week_start = now - (7 * 86400)

    with get_db() as db:
        # Uso hoje
        today = db.execute(
            "SELECT COALESCE(SUM(input_tokens),0) as inp, COALESCE(SUM(output_tokens),0) as out FROM usage_log WHERE user_id=? AND created_at>=?",
            (user_id, today_start),
        ).fetchone()

        # Uso semanal
        week = db.execute(
            "SELECT COALESCE(SUM(input_tokens),0) as inp, COALESCE(SUM(output_tokens),0) as out FROM usage_log WHERE user_id=? AND created_at>=?",
            (user_id, week_start),
        ).fetchone()

    today_inp, today_out = today["inp"], today["out"]
    week_inp, week_out = week["inp"], week["out"]

    # Check diario
    if plan["daily_input_tokens"] > 0 and today_inp >= plan["daily_input_tokens"]:
        hours_left = int((today_start + 86400 - now) / 3600)
        return {
            "allowed": False,
            "reason": f"Franquia diaria de tokens de entrada atingida. Renova em {hours_left}h.",
            "plan": plan_id,
        }
    if plan["daily_output_tokens"] > 0 and today_out >= plan["daily_output_tokens"]:
        hours_left = int((today_start + 86400 - now) / 3600)
        return {
            "allowed": False,
            "reason": f"Franquia diaria de tokens de saida atingida. Renova em {hours_left}h.",
            "plan": plan_id,
        }

    # Check semanal
    if plan["weekly_input_tokens"] > 0 and week_inp >= plan["weekly_input_tokens"]:
        return {"allowed": False, "reason": "Franquia semanal de tokens atingida.", "plan": plan_id}
    if plan["weekly_output_tokens"] > 0 and week_out >= plan["weekly_output_tokens"]:
        return {"allowed": False, "reason": "Franquia semanal de tokens atingida.", "plan": plan_id}

    return {
        "allowed": True,
        "plan": plan_id,
        "daily_input_remaining": max(0, plan["daily_input_tokens"] - today_inp) if plan["daily_input_tokens"] else -1,
        "daily_output_remaining": max(0, plan["daily_output_tokens"] - today_out) if plan["daily_output_tokens"] else -1,
    }


# ── Stripe Manager ────────────────────────────────────────────

def _get_stripe():
    """Import e configura stripe. Retorna None se nao instalado/configurado."""
    if not config.STRIPE_SECRET_KEY:
        return None
    try:
        import stripe
        stripe.api_key = config.STRIPE_SECRET_KEY
        return stripe
    except ImportError:
        return None


def create_checkout_session(user_id: str, email: str, plan_id: str, success_url: str, cancel_url: str) -> dict[str, Any]:
    """Cria Stripe Checkout Session. Retorna URL."""
    stripe = _get_stripe()
    if not stripe:
        return {"error": "Stripe nao configurado"}

    plan = get_plan(plan_id)
    if not plan["stripe_price_id"]:
        return {"error": f"Plano '{plan_id}' nao tem preco Stripe configurado"}

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": plan["stripe_price_id"], "quantity": 1}],
            customer_email=email,
            success_url=success_url or "https://clow.pvcorretor01.com.br/app/settings?payment=success",
            cancel_url=cancel_url or "https://clow.pvcorretor01.com.br/app/settings?payment=cancelled",
            metadata={"user_id": user_id, "plan_id": plan_id},
            locale="pt-BR",
            allow_promotion_codes=True,
            subscription_data={"trial_period_days": 7} if plan_id == "lite" else {},
        )
        log_action("billing_checkout", f"plan={plan_id} user={user_id}")
        return {"url": session.url, "session_id": session.id}
    except Exception as e:
        return {"error": str(e)[:200]}


def create_portal_session(customer_id: str, return_url: str = "") -> dict[str, Any]:
    """Cria Stripe Customer Portal session."""
    stripe = _get_stripe()
    if not stripe:
        return {"error": "Stripe nao configurado"}

    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url or "https://clow.pvcorretor01.com.br/",
        )
        return {"url": session.url}
    except Exception as e:
        return {"error": str(e)[:200]}


def handle_webhook(payload: bytes, sig_header: str) -> dict[str, Any]:
    """Processa webhook do Stripe. Retorna resultado."""
    stripe = _get_stripe()
    if not stripe:
        return {"error": "Stripe nao configurado"}

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, config.STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        return {"error": f"Webhook signature invalida: {e}"}

    event_type = event["type"]
    data = event["data"]["object"]

    if event_type == "checkout.session.completed":
        return _handle_checkout_completed(data)
    elif event_type == "checkout.session.async_payment_succeeded":
        # PIX confirmado (pode levar ate 30min)
        return _handle_checkout_completed(data)
    elif event_type == "checkout.session.async_payment_failed":
        # PIX expirado/falhou
        log_action("billing_pix_failed", f"session={data.get('id','')}", level="warning")
        return {"status": "pix_failed"}
    elif event_type == "customer.subscription.updated":
        return _handle_subscription_updated(data)
    elif event_type == "customer.subscription.deleted":
        return _handle_subscription_deleted(data)
    elif event_type == "invoice.payment_failed":
        return _handle_payment_failed(data)

    return {"status": "ignored", "event": event_type}


def _handle_checkout_completed(session: dict) -> dict:
    """Checkout concluido — ativa plano do user AUTOMATICAMENTE + envia email."""
    from .database import get_db, get_user_by_id

    user_id = session.get("metadata", {}).get("user_id", "")
    plan_id = session.get("metadata", {}).get("plan_id", "")
    customer_id = session.get("customer", "")
    subscription_id = session.get("subscription", "")

    if user_id and plan_id:
        with get_db() as db:
            # Ativa plano IMEDIATAMENTE
            db.execute("UPDATE users SET plan=? WHERE id=?", (plan_id, user_id))
            try:
                db.execute("ALTER TABLE users ADD COLUMN stripe_customer_id TEXT DEFAULT ''")
            except Exception:
                pass
            try:
                db.execute("ALTER TABLE users ADD COLUMN stripe_subscription_id TEXT DEFAULT ''")
            except Exception:
                pass
            db.execute(
                "UPDATE users SET stripe_customer_id=?, stripe_subscription_id=? WHERE id=?",
                (customer_id, subscription_id, user_id),
            )

        # Envia email de confirmacao via Stripe (receipt automatico)
        # O Stripe ja envia receipt se configurado no Dashboard
        # Tambem enviamos notificacao customizada
        user = get_user_by_id(user_id)
        if user:
            _send_welcome_email(user.get("email", ""), plan_id)

        log_action("billing_activated", f"user={user_id} plan={plan_id}")
        return {"status": "activated", "user_id": user_id, "plan": plan_id}

    return {"status": "no_metadata"}


def _send_welcome_email(email: str, plan_id: str) -> None:
    """Envia email de boas-vindas com detalhes da assinatura."""
    stripe = _get_stripe()
    if not stripe or not email:
        return

    plan = get_plan(plan_id)

    try:
        # Usa Stripe para enviar email (configura no Dashboard: Settings > Emails)
        # Stripe envia automaticamente: receipt, invoice, payment failed
        # Aqui registramos que o email deve ser enviado
        log_action("billing_welcome_email", f"email={email} plan={plan_id}")

        # Se quiser email customizado, pode usar httpx para API de email
        # Por agora, o Stripe cuida dos emails automaticos:
        # - Receipt de pagamento
        # - Invoice mensal
        # - Aviso de falha de pagamento
        # - Aviso de cancelamento
        # Basta ativar em: dashboard.stripe.com/settings/emails
    except Exception:
        pass


def _handle_subscription_updated(sub: dict) -> dict:
    """Subscription atualizada (upgrade/downgrade)."""
    from .database import get_db

    customer_id = sub.get("customer", "")
    price_id = ""
    if sub.get("items", {}).get("data"):
        price_id = sub["items"]["data"][0].get("price", {}).get("id", "")

    plan_id = PRICE_ID_TO_PLAN.get(price_id, "")
    if customer_id and plan_id:
        with get_db() as db:
            db.execute("UPDATE users SET plan=? WHERE stripe_customer_id=?", (plan_id, customer_id))
        log_action("billing_updated", f"customer={customer_id} plan={plan_id}")

    return {"status": "updated", "plan": plan_id}


def _handle_subscription_deleted(sub: dict) -> dict:
    """Subscription cancelada — volta pra byok_free."""
    from .database import get_db

    customer_id = sub.get("customer", "")
    if customer_id:
        with get_db() as db:
            db.execute("UPDATE users SET plan='byok_free' WHERE stripe_customer_id=?", (customer_id,))
        log_action("billing_cancelled", f"customer={customer_id}")

    return {"status": "cancelled"}


def _handle_payment_failed(invoice: dict) -> dict:
    """Pagamento falhou."""
    customer_id = invoice.get("customer", "")
    log_action("billing_payment_failed", f"customer={customer_id}", level="warning")
    return {"status": "payment_failed", "customer": customer_id}


def get_billing_status(user_id: str) -> dict[str, Any]:
    """Retorna status de billing do user."""
    from .database import get_user_by_id

    user = get_user_by_id(user_id)
    if not user:
        return {"error": "User nao encontrado"}

    plan_id = user.get("plan", "byok_free")
    is_admin = bool(user.get("is_admin"))
    # Mapeia planos antigos
    if plan_id in ("free", "basic"):
        plan_id = "byok_free"
    elif plan_id == "unlimited":
        plan_id = "business" if is_admin else "byok_free"

    plan = get_plan(plan_id)
    quota = check_quota(user_id, plan_id)

    return {
        "plan_id": plan_id,
        "plan_name": plan["name"],
        "price_brl": plan["price_brl"],
        "model": plan["model"],
        "uses_server_key": plan["uses_server_key"],
        "n8n_flows": plan["n8n_flows"],
        "quota": quota,
        "stripe_customer_id": user.get("stripe_customer_id", ""),
    }
