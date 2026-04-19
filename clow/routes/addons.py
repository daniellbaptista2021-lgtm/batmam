"""Addons Routes — gating de produtos premium opcionais (System Clow Sonnet 4)."""

from __future__ import annotations

import logging
import hmac
import hashlib
import time
import json
import base64
from fastapi import Request as _Req
from fastapi.responses import JSONResponse as _JR

logger = logging.getLogger("clow.addons")

SYSTEM_CLOW_URL = "https://system-clow.pvcorretor01.com.br/"


def register_addon_routes(app) -> None:
    from .auth import _get_user_session
    from .. import sonnet_credits
    from .. import config

    # ─── Status do System Clow (legado) ────────────────────────────────

    @app.get("/api/v1/addons/system-clow/status", tags=["addons"])
    async def system_clow_status(request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..database import get_db
        with get_db() as db:
            row = db.execute(
                "SELECT has_system_clow FROM users WHERE id=?",
                (sess["user_id"],),
            ).fetchone()
        active = bool(row[0]) if row and row[0] is not None else False
        return _JR({
            "active": active,
            "url": SYSTEM_CLOW_URL if active else None,
            "message": None if active else "Nao autorizado — contrate o System Clow",
        })

    # ─── Saldo e limites Sonnet ──────────────────────────────────────────

    @app.get("/api/v1/addons/sonnet/balance", tags=["addons"])
    async def sonnet_balance(request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        balance = sonnet_credits.get_balance(sess["user_id"])
        return _JR(balance)

    # ─── Check can use (antes de cada request Sonnet) ───────────────────

    @app.get("/api/v1/addons/sonnet/check", tags=["addons"])
    async def sonnet_check(request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"allowed": False, "reason": "not_authenticated"}, status_code=401)
        result = sonnet_credits.check_can_use(sess["user_id"])
        return _JR(result)

    # ─── Internal check (usado pelo System Clow middleware) ─────────────

    @app.get("/api/v1/internal/sonnet/check/{user_id}", tags=["internal"])
    async def sonnet_internal_check(request: _Req, user_id: str):
        # Validar shared secret
        secret = request.headers.get("x-clow-secret", "")
        expected = getattr(config, "SYSTEM_CLOW_INTERNAL_SECRET", "")
        if not expected or secret != expected:
            return _JR({"error": "forbidden"}, status_code=403)

        result = sonnet_credits.check_can_use(user_id)
        return _JR(result)

    @app.post("/api/v1/internal/sonnet/record", tags=["internal"])
    async def sonnet_internal_record(request: _Req):
        """System Clow chama isso depois de cada mensagem pra debitar saldo."""
        secret = request.headers.get("x-clow-secret", "")
        expected = getattr(config, "SYSTEM_CLOW_INTERNAL_SECRET", "")
        if not expected or secret != expected:
            return _JR({"error": "forbidden"}, status_code=403)

        try:
            body = await request.json()
        except Exception:
            return _JR({"error": "invalid_json"}, status_code=400)

        user_id = body.get("user_id")
        session_id = body.get("session_id", "")
        input_tokens = int(body.get("input_tokens") or 0)
        output_tokens = int(body.get("output_tokens") or 0)
        cache_hit_tokens = int(body.get("cache_hit_tokens") or 0)

        if not user_id:
            return _JR({"error": "missing_user_id"}, status_code=400)

        result = sonnet_credits.record_message_usage(
            user_id=user_id,
            session_id=session_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_hit_tokens=cache_hit_tokens,
        )
        return _JR({"ok": True, **result})

    # ─── Compra de pacote (Stripe Checkout) ─────────────────────────────

    @app.post("/api/v1/addons/sonnet/purchase", tags=["addons"])
    async def sonnet_purchase(request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)

        try:
            body = await request.json()
        except Exception:
            return _JR({"error": "invalid_json"}, status_code=400)

        package_id = body.get("package_id")
        if package_id not in sonnet_credits.PACKAGES:
            return _JR({"error": "invalid_package", "available": list(sonnet_credits.PACKAGES.keys())}, status_code=400)

        # URLs
        from ..database import get_db
        with get_db() as db:
            row = db.execute("SELECT email FROM users WHERE id=?", (sess["user_id"],)).fetchone()
        email = row[0] if row else sess.get("email", "")

        origin = request.headers.get("origin") or str(request.base_url).rstrip("/")
        success_url = f"{origin}/?sonnet_purchase=success"
        cancel_url = f"{origin}/?sonnet_purchase=cancelled"

        try:
            checkout = sonnet_credits.create_checkout_session(
                user_id=sess["user_id"],
                email=email,
                package_id=package_id,
                success_url=success_url,
                cancel_url=cancel_url,
            )
            return _JR({"checkout_url": checkout["url"], "session_id": checkout["id"]})
        except Exception as e:
            logger.exception("Sonnet checkout failed")
            return _JR({"error": "checkout_failed", "message": str(e)}, status_code=500)

    # ─── Lista pacotes disponíveis ──────────────────────────────────────

    @app.get("/api/v1/addons/sonnet/packages", tags=["addons"])
    async def sonnet_packages():
        return _JR({"packages": list(sonnet_credits.PACKAGES.values())})

    # ─── Token assinado para iframe System Clow ────────────────────────

    @app.get("/api/v1/addons/sonnet/token", tags=["addons"])
    async def sonnet_token(request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)

        secret = getattr(config, 'SYSTEM_CLOW_INTERNAL_SECRET', '')
        if not secret:
            return _JR({"error": "not_configured"}, status_code=500)

        # Detect admin
        from ..database import get_db
        with get_db() as db:
            row = db.execute("SELECT is_admin FROM users WHERE id=?", (sess["user_id"],)).fetchone()
        user_is_admin = bool(row and row[0])

        now = int(time.time())
        payload = {
            "user_id": sess["user_id"],
            "email": sess.get("email", ""),
            "iat": now,
            "exp": now + 10 * 365 * 24 * 60 * 60,  # vitalicio (10 anos)
            "src": "clow",
            "is_admin": user_is_admin,
        }
        payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        payload_b64 = base64.urlsafe_b64encode(payload_json.encode('utf-8')).rstrip(b'=').decode('ascii')
        sig = hmac.new(secret.encode('utf-8'), payload_b64.encode('ascii'), hashlib.sha256).digest()
        sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b'=').decode('ascii')
        token = f"clow_sonnet_{payload_b64}.{sig_b64}"

        system_clow_url = getattr(config, 'SYSTEM_CLOW_URL', SYSTEM_CLOW_URL.rstrip('/'))
        return _JR({
            "token": token,
            "expires_at": payload["exp"],
            "iframe_url": f"{system_clow_url}/?clow_token={token}",
            "is_admin": user_is_admin,
        })

    # ─── Histórico de compras ──────────────────────────────────────────

    @app.get("/api/v1/addons/sonnet/history", tags=["addons"])
    async def sonnet_history(request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)

        from ..database import get_db
        with get_db() as db:
            rows = db.execute(
                """SELECT package_id, price_paid_brl, credit_brl, purchased_at, expires_at, status
                   FROM sonnet_credits WHERE user_id=? ORDER BY purchased_at DESC LIMIT 50""",
                (sess["user_id"],)
            ).fetchall()

        history = [
            {
                "package_id": r[0],
                "price_paid_brl": r[1],
                "credit_brl": r[2],
                "purchased_at": r[3],
                "expires_at": r[4],
                "status": r[5],
            }
            for r in rows
        ]
        return _JR({"history": history})

    # ─── Webhook Stripe para Sonnet ─────────────────────────────────────

    @app.post("/webhooks/stripe/sonnet", tags=["webhooks"])
    async def stripe_sonnet_webhook(request: _Req):
        import stripe

        payload = await request.body()
        sig_header = request.headers.get("stripe-signature", "")

        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, config.STRIPE_WEBHOOK_SECRET
            )
        except Exception as e:
            logger.warning(f"[Sonnet webhook] invalid signature: {e}")
            return _JR({"error": "invalid_signature"}, status_code=400)

        event_type = event.get("type", "")
        data = event.get("data", {}).get("object", {})

        # Apenas checkout.session.completed com product_type=sonnet_credit
        if event_type == "checkout.session.completed":
            metadata = data.get("metadata", {})
            if metadata.get("product_type") == "sonnet_credit":
                try:
                    result = sonnet_credits.handle_stripe_payment_confirmed(data)
                    logger.info(f"[Sonnet webhook] processed: {result}")
                    return _JR({"ok": True, **result})
                except Exception as e:
                    logger.exception("Sonnet webhook processing failed")
                    return _JR({"error": "processing_failed", "message": str(e)}, status_code=500)

        return _JR({"ok": True, "ignored": event_type})
