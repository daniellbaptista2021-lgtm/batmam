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

    # ─── CRM Status: bloqueia cliente sem conexao propria ─────────────
    @app.get("/api/v1/addons/crm/status", tags=["addons"])
    async def crm_status(request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado", "allow": False}, status_code=401)
        is_admin = bool(sess.get("is_admin"))
        from ..database import get_db
        with get_db() as db:
            row = db.execute(
                "SELECT chatwoot_account_id, active FROM chatwoot_connections WHERE user_id=? AND active=1 ORDER BY connected_at DESC LIMIT 1",
                (sess["user_id"],),
            ).fetchone()
        configured = bool(row)
        # Busca dados completos pra determinar se remoto ou subconta local
        chatwoot_url = None
        connection_mode = None
        is_remote = False
        if configured:
            with get_db() as db:
                full = db.execute(
                    "SELECT chatwoot_account_id, chatwoot_url, connection_mode, is_remote FROM chatwoot_connections WHERE user_id=? AND active=1 ORDER BY connected_at DESC LIMIT 1",
                    (sess["user_id"],),
                ).fetchone()
            if full:
                chatwoot_url = full[1] or ""
                connection_mode = full[2] or "subconta_pv"
                is_remote = bool(full[3])
        allow = is_admin or configured
        return _JR({
            "allow": allow,
            "configured": configured,
            "is_admin": is_admin,
            "account_id": row[0] if row else None,
            "chatwoot_url": chatwoot_url,
            "connection_mode": connection_mode,
            "is_remote": is_remote,
            "reason": None if allow else "crm_not_configured",
            "message": None if allow else "Voce ainda nao configurou seu CRM. Complete o onboarding para liberar o Chatwoot com sua propria instancia WhatsApp.",
        })


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

    # ─── SSO: gerar URL de login automatico no Chatwoot ──────────────
    @app.get("/api/v1/addons/crm/sso-url", tags=["addons"])
    async def crm_sso_url(request: _Req):
        """Usa Platform API do Chatwoot pra gerar sso_auth_token do user.
        Retorna URL completa que loga direto: /app/login?sso_auth_token=...
        """
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)

        from ..database import get_db
        import os as _os, urllib.request, urllib.error, json as _j

        with get_db() as db:
            row = db.execute(
                "SELECT chatwoot_url, chatwoot_account_id, chatwoot_user_id FROM chatwoot_connections WHERE user_id=? AND active=1 ORDER BY connected_at DESC LIMIT 1",
                (sess["user_id"],),
            ).fetchone()

        if not row:
            # ─── Fallback just-in-time: provisiona Chatwoot pra users antigos / signup que falhou ───
            try:
                from ..services.onboarding import provision_user
                prov = provision_user(sess["user_id"], sess.get("email", ""), sess.get("name", ""))
                if prov.get("error"):
                    return _JR({"error": f"Falha ao provisionar CRM: {prov.get('error')}"}, status_code=500)
                with get_db() as db:
                    row = db.execute(
                        "SELECT chatwoot_url, chatwoot_account_id, chatwoot_user_id FROM chatwoot_connections WHERE user_id=? AND active=1 ORDER BY connected_at DESC LIMIT 1",
                        (sess["user_id"],),
                    ).fetchone()
                if not row:
                    return _JR({"error": "CRM provisionado mas connection nao gravada"}, status_code=500)
            except Exception as _e:
                return _JR({"error": f"Erro no provision just-in-time: {_e}"}, status_code=500)

        cw_url, account_id, cw_user_id = row[0], row[1], row[2]
        if not cw_user_id:
            return _JR({"error": "chatwoot_user_id nao mapeado. Re-faca onboarding."}, status_code=500)

        platform_token = getattr(config, "CHATWOOT_PLATFORM_TOKEN", "") or _os.getenv("CHATWOOT_PLATFORM_TOKEN", "")
        if not platform_token:
            return _JR({"error": "CHATWOOT_PLATFORM_TOKEN nao configurado no servidor"}, status_code=500)

        # Chatwoot Platform API: GET /platform/api/v1/users/{id}/login retorna URL de SSO
        try:
            req = urllib.request.Request(
                f"{cw_url.rstrip('/')}/platform/api/v1/users/{cw_user_id}/login",
                headers={"api_access_token": platform_token},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = _j.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            return _JR({"error": f"Platform API: {e.code}", "detail": e.read().decode()[:200]}, status_code=500)
        except Exception as e:
            return _JR({"error": f"Falha ao gerar SSO: {e}"}, status_code=500)

        sso_url = data.get("url") or ""
        if not sso_url:
            return _JR({"error": "Platform API nao retornou URL", "raw": data}, status_code=500)

        # Se SSO URL aponta pro dominio Chatwoot interno (ads.pvcorretor01),
        # reescreve pra /cw/ (same-origin via nginx) — evita CSP/cookie issues.
        import re as _re
        rewritten = _re.sub(
            r"https?://ads\.pvcorretor01\.com\.br",
            "https://clow.pvcorretor01.com.br/cw",
            sso_url,
        )
        # Ou se URL ja bate com cw_url, mantem
        return _JR({
            "ok": True,
            "sso_url": rewritten,
            "account_id": account_id,
            "chatwoot_user_id": cw_user_id,
        })


    # ─── Internal: authz pra nginx auth_request (bloqueio server-side) ───
    # NAO e exposto diretamente — so chamado via subrequest do nginx em /cw/*.
    # Retorna 200 se autorizado, 403 + cookies de logout do Chatwoot se nao.
    @app.get("/api/v1/internal/crm/authz", tags=["internal"])
    async def crm_authz(request: _Req):
        import time as _t
        sess = _get_user_session(request)
        ip = request.headers.get("x-real-ip") or request.client.host if request.client else ""
        ua = request.headers.get("user-agent", "")[:180]
        orig = request.headers.get("x-original-uri", "")[:300]

        if not sess:
            _log_crm_access(None, 0, None, False, "not_authenticated", ip, ua, orig)
            return _nuke_chatwoot_cookies(_JR({"error": "unauthenticated"}, status_code=403))

        user_id = sess["user_id"]
        is_admin = bool(sess.get("is_admin"))

        from ..database import get_db
        with get_db() as db:
            row = db.execute(
                "SELECT chatwoot_account_id FROM chatwoot_connections WHERE user_id=? AND active=1 ORDER BY connected_at DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        account_id = row[0] if row else None
        has_conn = row is not None

        # Defense in depth: se path tem /accounts/N/, validar que N bate com account_id do user
        # (admin pode ver qualquer account, cliente so o proprio)
        if not is_admin and orig:
            import re as _re
            m = _re.search(r"/accounts/(\d+)/", orig)
            if m:
                path_account_id = int(m.group(1))
                if account_id is not None and path_account_id != account_id:
                    _log_crm_access(user_id, 0, account_id, False, f"cross_account_access:requested={path_account_id}", ip, ua, orig)
                    return _nuke_chatwoot_cookies(_JR({"error": "cross_account_access_denied", "your_account": account_id, "requested": path_account_id}, status_code=403))

        if is_admin or has_conn:
            _log_crm_access(user_id, int(is_admin), account_id, True, None, ip, ua, orig)
            # Em headers pro nginx: ecoa quem autorizou (util pra debug/auditoria)
            resp = _JR({"allow": True, "user_id": user_id, "account_id": account_id, "is_admin": is_admin})
            resp.headers["X-Clow-User"] = user_id
            resp.headers["X-Clow-Account"] = str(account_id or 0)
            return resp

        # Cliente sem conexao: bloqueia + limpa cookies Chatwoot do browser
        _log_crm_access(user_id, 0, None, False, "no_chatwoot_connection", ip, ua, orig)
        return _nuke_chatwoot_cookies(_JR({"error": "crm_not_configured"}, status_code=403))


    def _log_crm_access(user_id, is_admin, account_id, allowed, reason, ip, ua, path):
        import time as _t
        try:
            from ..database import get_db
            with get_db() as db:
                db.execute(
                    """INSERT INTO crm_access_log (ts, user_id, is_admin, account_id, allowed, reason, ip, user_agent, path)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (_t.time(), user_id, is_admin, account_id, 1 if allowed else 0, reason, ip, ua, path),
                )
                db.commit()
        except Exception as e:
            logger.error(f"crm_audit log failed: {e}")


    def _nuke_chatwoot_cookies(resp):
        """Limpa todos os cookies possivelmente deixados pelo Chatwoot no browser."""
        expires = "Thu, 01 Jan 1970 00:00:00 GMT"
        cookies_to_clear = [
            "cw_d_DPXC1ucnY2xJcr4KHtfHLqQW",  # Chatwoot session cookie pattern
            "_chatwoot_session",
            "access_token",
            "cw_user_id",
        ]
        # Ataca padrao generico (cw_d_*, cw_*)
        nuke_headers = []
        for name in cookies_to_clear:
            nuke_headers.append(f"{name}=; Path=/; Expires={expires}; HttpOnly; Secure; SameSite=Lax")
            nuke_headers.append(f"{name}=; Path=/cw/; Expires={expires}; HttpOnly; Secure; SameSite=Lax")
        # Set-Cookie multiplos (append, nao sobrescreve)
        existing = resp.headers.get("set-cookie", "")
        for h in nuke_headers:
            resp.raw_headers.append((b"set-cookie", h.encode()))
        return resp


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
