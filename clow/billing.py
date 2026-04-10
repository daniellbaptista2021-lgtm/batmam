"""Stripe Billing — planos, checkout, portal, webhook, franquia.

Planos (DeepSeek V3.2):
- ONE (lite):          R$139,90/mes — 1M tok/dia (30M/mes), 1 WhatsApp
- SMART (starter):     R$177,90/mes — 1.8M tok/dia (54M/mes), 2 WhatsApp, CRM
- PROFISSIONAL (pro):  R$289,90/mes — 2.5M tok/dia (75M/mes), 3 WhatsApp, 5 usuarios
- BUSINESS (business): R$367,90/mes — 3M tok/dia (90M/mes), 5 WhatsApp, 10 usuarios

Pagamento: cartao, boleto, PIX (pagamento unico 30 dias).
"""

from __future__ import annotations
import json
import logging
import os
import sqlite3
import time
from typing import Any

from . import config
from .logging import log_action

logger = logging.getLogger(__name__)

# IPs conhecidos do Stripe para validacao de webhooks
STRIPE_WEBHOOK_IPS = frozenset({
    "3.18.12.63",
    "3.130.192.163",
    "13.235.26.127",
    "18.211.135.69",
    "35.154.171.200",
    "54.187.174.169",
    "54.187.205.235",
    "54.187.216.72",
})

# ── Plan Definitions ──────────────────────────────────────────

PLANS = {
    # ONE — R$139,90/mes — 1M tokens/dia = 30M/mes
    "lite": {
        "name": "ONE",
        "price_brl": 139.90,
        "model": "deepseek-chat",
        "uses_server_key": True,
        "daily_input_tokens": 1_000_000,
        "daily_output_tokens": 200_000,
        "weekly_input_tokens": 7_000_000,
        "weekly_output_tokens": 1_400_000,
        "n8n_flows": 0,
        "stripe_price_id": config.STRIPE_PRICE_ONE,
        "wa_model": "deepseek-chat",
        "wa_daily_tokens": 500_000,
        "wa_included_instances": 1,
        "crm_enabled": False,
        "max_users": 1,
    },
    # SMART — R$177,90/mes — 1,8M tokens/dia = 54M/mes
    "starter": {
        "name": "SMART",
        "price_brl": 177.90,
        "model": "deepseek-chat",
        "uses_server_key": True,
        "daily_input_tokens": 1_800_000,
        "daily_output_tokens": 360_000,
        "weekly_input_tokens": 12_600_000,
        "weekly_output_tokens": 2_520_000,
        "n8n_flows": 8,
        "stripe_price_id": config.STRIPE_PRICE_SMART,
        "wa_model": "deepseek-chat",
        "wa_daily_tokens": 750_000,
        "wa_included_instances": 2,
        "crm_enabled": True,
        "max_users": 3,
    },
    # PROFISSIONAL — R$289,90/mes — 2,5M tokens/dia = 75M/mes
    "pro": {
        "name": "PROFISSIONAL",
        "price_brl": 289.90,
        "model": "deepseek-chat",
        "uses_server_key": True,
        "daily_input_tokens": 2_500_000,
        "daily_output_tokens": 500_000,
        "weekly_input_tokens": 17_500_000,
        "weekly_output_tokens": 3_500_000,
        "n8n_flows": 2000,
        "stripe_price_id": config.STRIPE_PRICE_PROFISSIONAL,
        "wa_model": "deepseek-chat",
        "wa_daily_tokens": 1_000_000,
        "wa_included_instances": 3,
        "crm_enabled": True,
        "max_users": 5,
    },
    # BUSINESS — R$367,90/mes — 3M tokens/dia = 90M/mes
    "business": {
        "name": "BUSINESS",
        "price_brl": 367.90,
        "model": "deepseek-chat",
        "uses_server_key": True,
        "daily_input_tokens": 3_000_000,
        "daily_output_tokens": 600_000,
        "weekly_input_tokens": 21_000_000,
        "weekly_output_tokens": 4_200_000,
        "n8n_flows": 3000,
        "stripe_price_id": config.STRIPE_PRICE_BUSINESS,
        "wa_model": "deepseek-chat",
        "wa_daily_tokens": 1_500_000,
        "wa_included_instances": 5,
        "crm_enabled": True,
        "max_users": 10,
    },
}

PRICE_ID_TO_PLAN = {v["stripe_price_id"]: k for k, v in PLANS.items() if v["stripe_price_id"]}


def get_plan(plan_id: str) -> dict:
    """Retorna config do plano. Default: lite."""
    return PLANS.get(plan_id, PLANS["lite"])


def get_model_for_plan(plan_id: str) -> str:
    """Retorna model ID correto para o plano."""
    return get_plan(plan_id)["model"]


def plan_uses_server_key(plan_id: str) -> bool:
    """Retorna se o plano usa a API key do servidor."""
    return get_plan(plan_id)["uses_server_key"]


# ── Quota Checking ────────────────────────────────────────────

def check_plan_expiration(user_id: str) -> bool:
    """Verifica se plano PIX expirou. Retorna True se expirado e bloqueia."""
    from .database import get_db
    try:
        with get_db() as db:
            row = db.execute(
                "SELECT plan_expires_at, payment_mode FROM users WHERE id=?", (user_id,)
            ).fetchone()
            if not row:
                return False
            expires_at = int(row[0] or 0)
            mode = row[1] or ""
            if mode == "pix" and expires_at > 0 and time.time() > expires_at:
                db.execute("UPDATE users SET plan='byok_free', payment_status='expired' WHERE id=?",
                            (user_id,))
                log_action("billing_pix_expired", f"user={user_id}", level="warning")
                return True
    except Exception:
        pass
    return False


def check_quota(user_id: str, plan_id: str, source: str = "chat") -> dict[str, Any]:
    """Verifica se o user ainda tem franquia disponivel.

    source: "chat" ou "whatsapp" — franquias separadas.
    Returns dict com allowed=True/False e detalhes.
    """
    # Verifica expiracao de plano PIX
    if check_plan_expiration(user_id):
        return {"allowed": False, "reason": "Seu plano PIX expirou. Renove para continuar.", "plan": plan_id}

    plan = get_plan(plan_id)

    # WhatsApp: franquia separada (verifica ANTES do BYOK check)
    if source == "whatsapp":
        wa_daily = plan.get("wa_daily_tokens", 0)
        if wa_daily <= 0:
            return {"allowed": False, "reason": "WhatsApp nao incluso neste plano.", "plan": plan_id}

        from .database import get_db
        now = time.time()
        today_start = now - (now % 86400)
        with get_db() as db:
            try:
                row = db.execute(
                    "SELECT COALESCE(SUM(input_tokens + output_tokens),0) FROM usage_log WHERE user_id=? AND created_at>=? AND action='whatsapp'",
                    (user_id, today_start),
                ).fetchone()
                wa_used = row[0] if row else 0
            except sqlite3.OperationalError as e:
                logger.warning("Erro ao consultar uso WhatsApp: %s", e)
                wa_used = 0

        if wa_used >= wa_daily:
            return {"allowed": False, "reason": "Franquia diaria do WhatsApp atingida.", "plan": plan_id}
        return {"allowed": True, "plan": plan_id, "wa_remaining": wa_daily - wa_used}

    # Plano sem key do servidor — acesso bloqueado
    if not plan["uses_server_key"]:
        return {"allowed": False, "reason": "Assine um plano para acessar o Clow.", "plan": plan_id}

    from .database import get_db

    now = time.time()
    today_start = now - (now % 86400)
    week_start = now - (7 * 86400)

    with get_db() as db:
        # Uso hoje (apenas chat)
        today = db.execute(
            "SELECT COALESCE(SUM(input_tokens),0) as inp, COALESCE(SUM(output_tokens),0) as out FROM usage_log WHERE user_id=? AND created_at>=? AND (action='chat' OR action IS NULL)",
            (user_id, today_start),
        ).fetchone()

        # Uso semanal (apenas chat)
        week = db.execute(
            "SELECT COALESCE(SUM(input_tokens),0) as inp, COALESCE(SUM(output_tokens),0) as out FROM usage_log WHERE user_id=? AND created_at>=? AND (action='chat' OR action IS NULL)",
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



def create_public_checkout(plan_id: str, success_url: str = "", cancel_url: str = "",
                           payment_mode: str = "subscription") -> dict:
    """Cria Stripe Checkout Session sem usuario logado.

    payment_mode:
      - "subscription": assinatura recorrente (cartao + boleto)
      - "pix": pagamento unico via PIX (ativa plano por 30 dias)
    """
    stripe = _get_stripe()
    if not stripe:
        return {"error": "Stripe nao configurado"}

    plan = get_plan(plan_id)
    price_id = plan.get("stripe_price_id", "")
    if not price_id:
        return {"error": f"Plano {plan_id} sem price_id configurado"}

    base_success = success_url or "https://clow.pvcorretor01.com.br/login"
    base_cancel = cancel_url or "https://clow.pvcorretor01.com.br/landing"

    try:
        if payment_mode == "pix":
            # PIX: pagamento unico — ativa plano por 30 dias
            amount = int(plan["price_brl"] * 100)
            session = stripe.checkout.Session.create(
                mode="payment",
                payment_method_types=["pix"],
                line_items=[{
                    "price_data": {
                        "currency": "brl",
                        "product": _get_product_for_plan(stripe, plan_id),
                        "unit_amount": amount,
                    },
                    "quantity": 1,
                }],
                success_url=base_success,
                cancel_url=base_cancel,
                metadata={"plan_id": plan_id, "payment_mode": "pix"},
                locale="pt-BR",
                expires_at=int(time.time()) + 3600,  # PIX expira em 1h
            )
        else:
            # Assinatura recorrente: cartao + boleto
            session = stripe.checkout.Session.create(
                mode="subscription",
                payment_method_types=["card", "boleto"],
                line_items=[{"price": price_id, "quantity": 1}],
                success_url=base_success,
                cancel_url=base_cancel,
                metadata={"plan_id": plan_id, "payment_mode": "subscription"},
                allow_promotion_codes=True,
                locale="pt-BR",
                payment_method_options={
                    "boleto": {"expires_after_days": 3},
                },
            )
        return {"url": session.url, "session_id": session.id}
    except Exception as e:
        return {"error": str(e)}


def _get_product_for_plan(stripe, plan_id: str) -> str:
    """Retorna product ID do Stripe para um plano (para checkout PIX avulso)."""
    # Busca o product do price existente
    plan = get_plan(plan_id)
    price_id = plan.get("stripe_price_id", "")
    if price_id:
        try:
            price = stripe.Price.retrieve(price_id)
            return price.product
        except Exception:
            pass
    # Fallback: cria product generico
    return "prod_UIhpTB9J0DSOGM"

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
            payment_method_types=["card", "boleto"],
            line_items=[{"price": plan["stripe_price_id"], "quantity": 1}],
            customer_email=email,
            success_url=success_url or "https://clow.pvcorretor01.com.br/app/settings?payment=success",
            cancel_url=cancel_url or "https://clow.pvcorretor01.com.br/app/settings?payment=cancelled",
            metadata={"user_id": user_id, "plan_id": plan_id},
            locale="pt-BR",
            allow_promotion_codes=True,
            payment_method_options={
                "boleto": {"expires_after_days": 3},
            },
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


def handle_webhook(payload: bytes, sig_header: str, source_ip: str = "") -> dict[str, Any]:
    """Processa webhook do Stripe. Retorna resultado."""
    # Valida IP de origem — apenas IPs conhecidos da Stripe
    if source_ip and source_ip not in STRIPE_WEBHOOK_IPS:
        logger.warning("Webhook rejeitado: IP %s nao autorizado", source_ip)
        return {"error": "Forbidden", "status_code": 403}

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
    """Checkout concluido — ativa plano do user AUTOMATICAMENTE + envia email.

    Suporta:
    - subscription (cartao/boleto): plano ativo enquanto assinatura existir
    - payment/pix: plano ativo por 30 dias (plan_expires_at)
    """
    from .database import get_db, get_user_by_id

    user_id = session.get("metadata", {}).get("user_id", "")
    plan_id = session.get("metadata", {}).get("plan_id", "")
    payment_mode = session.get("metadata", {}).get("payment_mode", "subscription")
    customer_id = session.get("customer", "")
    subscription_id = session.get("subscription", "")

    if user_id and plan_id:
        with get_db() as db:
            # Garante colunas existem
            for col, default in [
                ("stripe_customer_id", "''"),
                ("stripe_subscription_id", "''"),
                ("plan_expires_at", "0"),
                ("payment_mode", "''"),
            ]:
                try:
                    db.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT DEFAULT {default}")
                except sqlite3.OperationalError:
                    pass

            # Ativa plano
            db.execute("UPDATE users SET plan=?, payment_mode=? WHERE id=?",
                        (plan_id, payment_mode, user_id))
            db.execute(
                "UPDATE users SET stripe_customer_id=?, stripe_subscription_id=? WHERE id=?",
                (customer_id, subscription_id or "", user_id),
            )

            # PIX: define expiracao em 30 dias
            if payment_mode == "pix":
                expires_at = int(time.time()) + (30 * 86400)
                db.execute("UPDATE users SET plan_expires_at=? WHERE id=?",
                            (str(expires_at), user_id))
                log_action("billing_pix_activated",
                            f"user={user_id} plan={plan_id} expires={expires_at}")

        user = get_user_by_id(user_id)
        if user:
            _send_welcome_email(user.get("email", ""), plan_id)

        log_action("billing_activated", f"user={user_id} plan={plan_id} mode={payment_mode}")
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
    except OSError as e:
        logger.warning("Erro ao enviar email de boas-vindas: %s", e)


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
    """Subscription cancelada — bloqueia acesso e notifica admin."""
    from .database import get_db

    customer_id = sub.get("customer", "")
    if customer_id:
        with get_db() as db:
            # Get user info before downgrade
            row = db.execute("SELECT email, name, plan FROM users WHERE stripe_customer_id=?", (customer_id,)).fetchone()
            user_email = row[0] if row else "desconhecido"
            user_name = row[1] if row else ""
            old_plan = row[2] if row else ""

            # Downgrade to blocked
            db.execute("UPDATE users SET plan='byok_free', payment_status='cancelled' WHERE stripe_customer_id=?", (customer_id,))

        log_action("billing_cancelled", f"customer={customer_id} email={user_email}")

        # Notify admin via WhatsApp
        try:
            import urllib.request, json as _json
            zapi_url = f"https://api.z-api.io/instances/{os.getenv('ZAPI_INSTANCE_ID', '')}/token/{os.getenv('ZAPI_TOKEN', '')}/send-text"
            msg = f"CLOW CANCELAMENTO - {user_name} ({user_email}) - Plano {old_plan} cancelado. Acesso bloqueado."
            data = _json.dumps({"phone": os.getenv("ALERT_PHONE", ""), "message": msg}).encode()
            req = urllib.request.Request(zapi_url, data=data, headers={"Content-Type": "application/json", "Client-Token": os.getenv("ZAPI_CLIENT_TOKEN", "")})
            urllib.request.urlopen(req, timeout=10)
        except Exception:
            pass

    return {"status": "cancelled"}


def _handle_payment_failed(invoice: dict) -> dict:
    """Pagamento falhou — marca usuario como inadimplente e notifica admin."""
    from .database import get_db
    import subprocess

    customer_id = invoice.get("customer", "")
    attempt = invoice.get("attempt_count", 1)

    if customer_id:
        with get_db() as db:
            # Add payment_status column if not exists
            try:
                db.execute("ALTER TABLE users ADD COLUMN payment_status TEXT DEFAULT 'ok'")
            except Exception:
                pass
            # Mark as overdue
            db.execute("UPDATE users SET payment_status='overdue' WHERE stripe_customer_id=?", (customer_id,))
            # Get user info for alert
            row = db.execute("SELECT email, name, plan FROM users WHERE stripe_customer_id=?", (customer_id,)).fetchone()
            user_email = row[0] if row else "desconhecido"
            user_name = row[1] if row else ""
            user_plan = row[2] if row else ""

    log_action("billing_payment_failed", f"customer={customer_id} attempt={attempt} email={user_email}", level="warning")

    # Send WhatsApp alert to admin
    try:
        import urllib.request, json as _json
        zapi_url = f"https://api.z-api.io/instances/{os.getenv('ZAPI_INSTANCE_ID', '')}/token/{os.getenv('ZAPI_TOKEN', '')}/send-text"
        msg = f"CLOW BILLING - Pagamento falhou! Cliente: {user_name} ({user_email}) Plano: {user_plan} Tentativa: {attempt}"
        data = _json.dumps({"phone": os.getenv("ALERT_PHONE", ""), "message": msg}).encode()
        req = urllib.request.Request(zapi_url, data=data, headers={"Content-Type": "application/json", "Client-Token": os.getenv("ZAPI_CLIENT_TOKEN", "")})
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass

    return {"status": "payment_failed", "customer": customer_id, "attempt": attempt}


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
