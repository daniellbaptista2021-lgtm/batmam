"""Onboarding Routes — wizard de primeiro acesso."""

from __future__ import annotations
from pathlib import Path

from fastapi import Request as _Req
from fastapi.responses import JSONResponse as _JR, HTMLResponse as _HR, RedirectResponse

_TPL_DIR = Path(__file__).resolve().parent.parent / "templates"


def register_onboarding_routes(app) -> None:

    from .auth import _get_user_session

    def _auth(request: _Req):
        return _get_user_session(request)

    def _tenant(sess: dict) -> str:
        return sess["user_id"]

    @app.get("/app/onboarding", tags=["onboarding"])
    async def onboarding_page(request: _Req):
        sess = _auth(request)
        if not sess:
            return RedirectResponse("/login")
        # Use new wizard template
        tpl = _TPL_DIR / "onboarding_wizard.html"
        if tpl.exists():
            return _HR(tpl.read_text(encoding="utf-8"))
        tpl = _TPL_DIR / "onboarding.html"
        if tpl.exists():
            return _HR(tpl.read_text(encoding="utf-8"))
        return _HR("<h1>Onboarding em construcao</h1>")

    @app.get("/api/v1/onboarding/progress", tags=["onboarding"])
    async def onboarding_progress(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..onboarding import get_progress
        return _JR(get_progress(_tenant(sess)))

    @app.post("/api/v1/onboarding/complete-step", tags=["onboarding"])
    async def onboarding_complete_step(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        step_id = body.get("step_id", "")
        step_data = body.get("data", {})
        from ..onboarding import complete_step
        return _JR(complete_step(_tenant(sess), step_id, step_data))

    @app.post("/api/v1/onboarding/skip-step", tags=["onboarding"])
    async def onboarding_skip_step(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        from ..onboarding import skip_step
        return _JR(skip_step(_tenant(sess), body.get("step_id", "")))

    @app.post("/api/v1/onboarding/generate-prompt", tags=["onboarding"])
    async def onboarding_gen_prompt(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        from ..onboarding import generate_agent_prompt
        prompt = generate_agent_prompt(body)
        return _JR({"prompt": prompt})

    @app.post("/api/v1/onboarding/test-message", tags=["onboarding"])
    async def onboarding_test(request: _Req):
        """Simula conversa com o agente usando o prompt gerado."""
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        message = body.get("message", "").strip()
        prompt = body.get("prompt", "")
        if not message:
            return _JR({"error": "Mensagem obrigatoria"}, status_code=400)
        try:
            from openai import OpenAI
            from .. import config as _cfg
            client = OpenAI(**_cfg.get_deepseek_client_kwargs())
            response = client.chat.completions.create(
                model=_cfg.CLOW_MODEL,
                messages=[
                    {"role": "system", "content": prompt or "Voce e um atendente virtual. Seja simpatico e objetivo."},
                    {"role": "user", "content": message},
                ],
                max_tokens=300,
            )
            reply = (response.choices[0].message.content or "").strip() if response.choices else "Desculpe, nao consegui responder."
            return _JR({"reply": reply})
        except Exception as e:
            return _JR({"reply": f"Erro no teste: {str(e)[:100]}"})

    # ── Templates de agentes ──

    @app.get("/api/v1/templates", tags=["templates"])
    async def list_agent_templates(request: _Req):
        from ..agent_templates import list_templates
        return _JR({"templates": list_templates()})

    @app.get("/api/v1/templates/{tid}", tags=["templates"])
    async def get_agent_template(tid: str, request: _Req):
        from ..agent_templates import get_template
        t = get_template(tid)
        if not t:
            return _JR({"error": "Template nao encontrado"}, status_code=404)
        return _JR(t)

    @app.post("/api/v1/templates/{tid}/apply", tags=["templates"])
    async def apply_agent_template(tid: str, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        from ..agent_templates import apply_template
        result = apply_template(_tenant(sess), body.get("instance_id", ""), tid,
                                body.get("business_name", ""))
        return _JR(result)

    @app.post("/api/v1/onboarding/finish", tags=["onboarding"])
    async def onboarding_finish(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..onboarding import finish_onboarding
        return _JR(finish_onboarding(_tenant(sess)))

    # ── Multi-tenant Onboarding Routes ───────────────────────

    @app.get("/api/v1/onboarding/status", tags=["onboarding"])
    async def onboarding_status(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        uid = _tenant(sess)
        from ..database import get_chatwoot_connection_by_user, list_chatwoot_bot_configs, get_whatsapp_credentials, get_db
        conn = get_chatwoot_connection_by_user(uid)
        configs = list_chatwoot_bot_configs(uid)
        creds = get_whatsapp_credentials(uid)
        with get_db() as db:
            user = db.execute("SELECT onboarding_completed FROM users WHERE id=?", (uid,)).fetchone()
        return _JR({
            "chatwoot_connected": bool(conn and conn.get("chatwoot_account_id")),
            "whatsapp_connected": bool(creds and creds.get("status") == "connected"),
            "whatsapp_type": creds.get("type", "") if creds else "",
            "bot_configured": len(configs) > 0 and any(c.get("active") for c in configs),
            "onboarding_completed": bool(user and user["onboarding_completed"]),
        })

    @app.post("/api/v1/onboarding/chatwoot/setup", tags=["onboarding"])
    async def onboarding_chatwoot_setup(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        uid = _tenant(sess)
        from ..services.onboarding import provision_user
        result = provision_user(uid, sess["email"], sess.get("name", ""))
        if result.get("error"):
            return _JR(result, status_code=500)
        return _JR(result)

    @app.post("/api/v1/onboarding/whatsapp/test", tags=["onboarding"])
    async def onboarding_whatsapp_test(request: _Req):
        """Test Z-API or Meta credentials."""
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        ctype = body.get("type", "")
        if ctype == "zapi":
            from ..services.onboarding import test_zapi_connection
            return _JR(test_zapi_connection(
                body.get("instance_id", ""),
                body.get("token", ""),
                body.get("client_token", ""),
            ))
        elif ctype == "meta":
            from ..services.onboarding import test_meta_connection
            return _JR(test_meta_connection(body.get("phone_number_id", ""), body.get("access_token", "")))
        return _JR({"error": "Tipo invalido. Use 'zapi' ou 'meta'."}, status_code=400)

    @app.post("/api/v1/onboarding/whatsapp/save", tags=["onboarding"])
    async def onboarding_whatsapp_save(request: _Req):
        """Save WhatsApp credentials, create Chatwoot inbox, register webhook, create bot config."""
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        uid = _tenant(sess)
        body = await request.json()
        ctype = body.get("type", "")
        if ctype not in ("zapi", "meta"):
            return _JR({"error": "Tipo invalido"}, status_code=400)

        from ..database import get_chatwoot_connection_by_user, save_whatsapp_credentials, upsert_chatwoot_bot_config
        from ..services.onboarding import create_chatwoot_inbox, register_chatwoot_webhook

        conn = get_chatwoot_connection_by_user(uid)
        inbox_id = 0
        webhook_url_info = ""

        # Create inbox in user's Chatwoot account
        if conn and conn.get("chatwoot_account_id"):
            cw_url = conn["chatwoot_url"]
            cw_token = conn.get("chatwoot_user_token") or conn["chatwoot_token"]
            acc_id = conn["chatwoot_account_id"]
            wh_token = conn["webhook_token"]

            # Inbox name
            if ctype == "zapi":
                masked = body.get("instance_id", "")[-8:]
                inbox_name = f"WhatsApp Z-API ...{masked}"
            else:
                masked = body.get("phone_number_id", "")[-6:]
                inbox_name = f"WhatsApp Meta ...{masked}"

            inbox = create_chatwoot_inbox(cw_url, cw_token, acc_id, inbox_name, wh_token)
            if inbox and inbox.get("id"):
                inbox_id = inbox["id"]

            # Register webhook for bot
            register_chatwoot_webhook(cw_url, cw_token, acc_id, wh_token)

            # Build webhook URLs for user instruction
            clow_url = "https://clow.pvcorretor01.com.br"
            if ctype == "zapi":
                webhook_url_info = f"{clow_url}/api/v1/zapi/webhook/{wh_token}"
            else:
                webhook_url_info = f"{clow_url}/api/v1/meta/webhook/{wh_token}"

        # Save credentials (inclui client_token p/ Z-API)
        creds = save_whatsapp_credentials(uid, ctype, {
            "instance_id": body.get("instance_id", ""),
            "token": body.get("token", ""),
            "client_token": body.get("client_token", ""),
            "phone_number_id": body.get("phone_number_id", ""),
            "access_token": body.get("access_token", ""),
            "status": "connected",
            "chatwoot_inbox_id": inbox_id,
            "webhook_token": conn["webhook_token"] if conn else "",
        })

        # Cria tambem WhatsAppInstance (filesystem) pra aparecer em /app/whatsapp
        try:
            import time as _t
            from ..whatsapp_agent import get_wa_manager as _wa
            _wa().create_instance(
                tenant_id=uid,
                name=("WhatsApp Z-API" if ctype == "zapi" else "WhatsApp Meta"),
                zapi_instance_id=(body.get("instance_id", "") if ctype == "zapi" else ("meta-" + body.get("phone_number_id", ""))),
                zapi_token=(body.get("token", "") if ctype == "zapi" else "meta"),
                system_prompt="",
                provider=ctype,
                meta_phone_number_id=body.get("phone_number_id", ""),
                meta_access_token=body.get("access_token", ""),
                meta_verify_token=("clow_" + str(int(_t.time()))),
                zapi_client_token=body.get("client_token", ""),
            )
        except Exception as _e:
            import logging as _lg
            _lg.getLogger("clow.onboarding").warning("wa_manager.create_instance failed in onboarding: %s", _e)

        # Auto-registra webhook na Z-API (cliente nao precisa configurar manualmente)
        if ctype == "zapi" and webhook_url_info and body.get("client_token"):
            try:
                from ..services.onboarding import register_zapi_webhook
                register_zapi_webhook(
                    body.get("instance_id", ""),
                    body.get("token", ""),
                    body.get("client_token", ""),
                    webhook_url_info,
                )
            except Exception:
                pass  # nao bloqueia save

        # Create bot config (inactive, prompt empty — will be filled in step 3)
        if inbox_id:
            upsert_chatwoot_bot_config(
                inbox_id=inbox_id,
                inbox_name=inbox_name if inbox_id else "",
                system_prompt="",
                active=False,
                human_handoff=True,
                user_id=uid,
            )

        return _JR({
            "ok": True,
            "credentials": creds,
            "inbox_id": inbox_id,
            "webhook_url": webhook_url_info,
            "type": ctype,
        })


    @app.get("/api/v1/onboarding/webhook-info", tags=["onboarding"])
    async def onboarding_webhook_info(request: _Req):
        """Retorna as webhook URLs do usuario para Z-API e Meta. Cliente precisa
        configurar isso no painel respectivo (auto-config tambem ocorre no save)."""
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..database import get_chatwoot_connection_by_user
        conn = get_chatwoot_connection_by_user(_tenant(sess))
        wh_token = (conn or {}).get("webhook_token") or ""
        base = "https://clow.pvcorretor01.com.br"
        return _JR({
            "ok": bool(wh_token),
            "webhook_token": wh_token,
            "zapi_webhook": f"{base}/api/v1/zapi/webhook/{wh_token}" if wh_token else "",
            "meta_webhook": f"{base}/api/v1/meta/webhook/{wh_token}" if wh_token else "",
        })

    @app.get("/api/v1/onboarding/whatsapp/credentials", tags=["onboarding"])
    async def onboarding_whatsapp_get(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..database import get_whatsapp_credentials
        creds = get_whatsapp_credentials(_tenant(sess))
        if creds:
            safe = {k: v for k, v in creds.items() if k not in ("token", "access_token")}
            if creds.get("token"):
                safe["token_masked"] = creds["token"][:8] + "..."
            if creds.get("access_token"):
                safe["access_token_masked"] = creds["access_token"][:8] + "..."
            return _JR({"connected": True, "credentials": safe})
        return _JR({"connected": False})

    @app.post("/api/v1/onboarding/bot/configure", tags=["onboarding"])
    async def onboarding_bot_configure(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        uid = _tenant(sess)
        body = await request.json()
        system_prompt = body.get("system_prompt", "")
        human_handoff = body.get("human_handoff", True)
        model = "deepseek-chat"
        # Find the inbox created by Evolution in the user's Chatwoot account
        from ..database import get_chatwoot_connection_by_user, upsert_chatwoot_bot_config
        conn = get_chatwoot_connection_by_user(uid)
        if not conn:
            return _JR({"error": "Chatwoot nao configurado"}, status_code=400)
        # Get inboxes from user's Chatwoot
        from ..chatwoot_integration import ChatwootClient
        client = ChatwootClient(conn["chatwoot_url"], conn["chatwoot_account_id"], conn.get("chatwoot_user_token") or conn["chatwoot_token"])
        inboxes = client.get_inboxes()
        if not inboxes:
            return _JR({"error": "Nenhuma inbox encontrada"}, status_code=400)
        # Configure bot for all inboxes (or first one)
        configured = []
        for ib in inboxes:
            cfg = upsert_chatwoot_bot_config(
                inbox_id=ib["id"],
                inbox_name=ib.get("name", ""),
                system_prompt=system_prompt,
                active=True,
                model=model,
                human_handoff=human_handoff,
                user_id=uid,
            )
            configured.append(cfg)
        # Register webhook
        from ..services.onboarding import register_bot_webhook
        wh_result = register_bot_webhook(
            conn["chatwoot_url"],
            conn.get("chatwoot_user_token") or conn["chatwoot_token"],
            conn["chatwoot_account_id"],
            conn["webhook_token"],
        )
        return _JR({"ok": True, "configs": configured, "webhook": wh_result})

    @app.post("/api/v1/onboarding/complete", tags=["onboarding"])
    async def onboarding_complete_all(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        uid = _tenant(sess)
        from ..database import get_db
        with get_db() as db:
            db.execute("UPDATE users SET onboarding_completed=1, first_login=0 WHERE id=?", (uid,))
        return _JR({"ok": True})
