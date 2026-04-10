"""WhatsApp Agent routes — CRUD instances, webhook, conversations."""

from __future__ import annotations
import os
import time
import threading
import logging
from pathlib import Path

from fastapi import Request as _Req
from fastapi.responses import JSONResponse as _JR, HTMLResponse as _HR, RedirectResponse

logger = logging.getLogger("clow.routes.whatsapp_agent")

# Debounce buffers: {instance_id:phone -> [messages]}
_debounce_buffers: dict[str, list[str]] = {}
_debounce_timers: dict[str, threading.Timer] = {}
_debounce_lock = threading.Lock()
DEBOUNCE_SECONDS = 8



import os as _os_meta

_meta_contact_names = {}

def _process_meta_carol(instance_id, phone, message):
    import json as _j, logging
    _log = logging.getLogger("clow.meta")
    name = _meta_contact_names.get(phone, "")
    try:
        from .._carol_nio_agent_module import process_daniel_message
        reply = process_daniel_message(phone, message, customer_name=name)
    except ImportError:
        try:
            from ..carol_nio_agent import process_daniel_message
            reply = process_daniel_message(phone, message, customer_name=name)
        except Exception as e:
            _log.error(f"Agent error: {e}")
            reply = None
    except Exception as e:
        _log.error(f"Agent error: {e}")
        reply = None
    if not reply:
        return
    token = _os_meta.getenv("META_ACCESS_TOKEN", "")
    phone_id = _os_meta.getenv("META_PHONE_NUMBER_ID", "")
    if token and phone_id:
        try:
            from urllib.request import urlopen, Request
            url = f"https://graph.facebook.com/v18.0/{phone_id}/messages"
            data = _j.dumps({"messaging_product": "whatsapp", "to": phone, "type": "text", "text": {"body": reply}}).encode()
            req = Request(url, data=data, headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"}, method="POST")
            urlopen(req, timeout=30)
        except Exception as e:
            _log.error(f"Meta send: {e}")
    try:
        cw_url = _os_meta.getenv("CHATWOOT_URL", "")
        cw_token = _os_meta.getenv("CHATWOOT_API_TOKEN", "")
        inbox_id = int(_os_meta.getenv("CHATWOOT_NIO_INBOX_ID", "4"))
        if cw_url and cw_token:
            from ..chatwoot_integration import get_chatwoot_client, get_or_create_chatwoot_conversation
            cl = get_chatwoot_client("nio")
            if cl:
                cid = get_or_create_chatwoot_conversation(cl, "meta-nio", phone, inbox_id)
                if cid:
                    cl.send_message(cid, message, message_type="incoming")
                    cl.send_message(cid, "[Daniel] " + reply, message_type="outgoing", private=True)
    except Exception:
        pass


def register_whatsapp_agent_routes(app) -> None:

    from .auth import _get_user_session

    # ── Page ──────────────────────────────────────────────────

    @app.get("/app/whatsapp", tags=["whatsapp"])
    async def whatsapp_page(request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return RedirectResponse("/login", status_code=302)
        tpl = Path(__file__).parent.parent / "templates" / "whatsapp.html"
        if tpl.exists():
            return _HR(tpl.read_text(encoding="utf-8"))
        return _HR("<h1>WhatsApp Agent</h1>")

    # ── CRUD Instances ────────────────────────────────────────

    @app.get("/api/v1/whatsapp/instances", tags=["whatsapp"])
    async def list_instances(request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..whatsapp_agent import get_wa_manager
        mgr = get_wa_manager()
        instances = mgr.get_instances(sess["user_id"])
        extra_cost = mgr.get_extra_cost(sess["user_id"])
        return _JR({"instances": instances, "count": len(instances), "extra_cost_brl": extra_cost, "included": 2})

    @app.post("/api/v1/whatsapp/instances", tags=["whatsapp"])
    async def create_instance(request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        from ..whatsapp_agent import get_wa_manager
        result = get_wa_manager().create_instance(
            tenant_id=sess["user_id"],
            name=body.get("name", "Meu WhatsApp"),
            zapi_instance_id=body.get("zapi_instance_id", ""),
            zapi_token=body.get("zapi_token", ""),
            system_prompt=body.get("system_prompt", ""),
            provider=body.get("provider", "zapi"),
            meta_phone_number_id=body.get("meta_phone_number_id", ""),
            meta_waba_id=body.get("meta_waba_id", ""),
            meta_access_token=body.get("meta_access_token", ""),
            meta_verify_token=body.get("meta_verify_token", ""),
        )
        return _JR(result, status_code=201 if result.get("success") else 400)

    @app.get("/api/v1/whatsapp/instances/{instance_id}", tags=["whatsapp"])
    async def get_instance(instance_id: str, request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..whatsapp_agent import get_wa_manager
        inst = get_wa_manager().get_instance(instance_id, sess["user_id"])
        if not inst:
            return _JR({"error": "Nao encontrada"}, status_code=404)
        # Return full data (including full token for owner)
        d = inst.to_dict()
        d["zapi_token_full"] = inst.zapi_token
        d["system_prompt_full"] = inst.system_prompt
        d["rag_text_full"] = inst.rag_text
        d["meta_access_token_full"] = inst.meta_access_token
        d["provider"] = inst.provider
        return _JR(d)

    @app.put("/api/v1/whatsapp/instances/{instance_id}", tags=["whatsapp"])
    async def update_instance(instance_id: str, request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        from ..whatsapp_agent import get_wa_manager
        allowed = {"name", "zapi_instance_id", "zapi_token", "system_prompt", "rag_text", "active", "context_size", "handoff_enabled", "handoff_keyword", "provider", "meta_phone_number_id", "meta_waba_id", "meta_access_token", "meta_verify_token"}
        updates = {k: v for k, v in body.items() if k in allowed}
        result = get_wa_manager().update_instance(instance_id, sess["user_id"], **updates)
        return _JR(result)

    @app.delete("/api/v1/whatsapp/instances/{instance_id}", tags=["whatsapp"])
    async def delete_instance(instance_id: str, request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..whatsapp_agent import get_wa_manager
        ok = get_wa_manager().delete_instance(instance_id, sess["user_id"])
        return _JR({"success": ok})

    @app.post("/api/v1/whatsapp/instances/{instance_id}/activate", tags=["whatsapp"])
    async def activate_instance(instance_id: str, request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..whatsapp_agent import get_wa_manager
        return _JR(get_wa_manager().update_instance(instance_id, sess["user_id"], active=True))

    @app.post("/api/v1/whatsapp/instances/{instance_id}/deactivate", tags=["whatsapp"])
    async def deactivate_instance(instance_id: str, request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..whatsapp_agent import get_wa_manager
        return _JR(get_wa_manager().update_instance(instance_id, sess["user_id"], active=False))

    # ── Auto-Reply Toggle ────────────────────────────────────

    @app.put("/api/v1/whatsapp/instances/{instance_id}/auto-reply", tags=["whatsapp"])
    async def toggle_auto_reply(instance_id: str, request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        enabled = body.get("enabled", True)
        from ..whatsapp_agent import get_wa_manager
        result = get_wa_manager().update_instance(instance_id, sess["user_id"], auto_reply_enabled=enabled)
        return _JR(result)

    @app.get("/api/v1/whatsapp/instances/{instance_id}/diagnose", tags=["whatsapp"])
    async def diagnose_instance(instance_id: str, request: _Req):
        """Diagnostico completo de uma instancia WhatsApp."""
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..whatsapp_agent import get_wa_manager
        inst = get_wa_manager().get_instance(instance_id, sess["user_id"])
        if not inst:
            return _JR({"error": "Instancia nao encontrada"}, status_code=404)

        checks = []

        # 1. Credenciais Z-API
        try:
            from urllib.request import urlopen as _urlopen, Request as _Request
            import json as _json
            zurl = f"https://api.z-api.io/instances/{inst.zapi_instance_id}/token/{inst.zapi_token}/status"
            zresp = _urlopen(_Request(zurl), timeout=10)
            zdata = _json.loads(zresp.read().decode())
            checks.append({"name": "Credenciais Z-API", "status": "ok", "detail": f"Conectado: {zdata}"})
        except Exception as e:
            checks.append({"name": "Credenciais Z-API", "status": "error", "detail": str(e)[:150]})

        # 2. Prompt
        has_prompt = bool(inst.system_prompt and len(inst.system_prompt) > 10)
        checks.append({"name": "Prompt do agente", "status": "ok" if has_prompt else "warning",
                        "detail": f"{len(inst.system_prompt)} caracteres" if has_prompt else "Vazio ou muito curto"})

        # 3. Auto-reply
        checks.append({"name": "Resposta automatica (IA)", "status": "ok" if inst.auto_reply_enabled else "off",
                        "detail": "Ativada" if inst.auto_reply_enabled else "Desativada"})

        # 4. Webhook URL esperada
        checks.append({"name": "Webhook URL", "status": "info", "detail": inst.webhook_url})

        return _JR({"instance": inst.name, "checks": checks})

    # ── RAG ───────────────────────────────────────────────────

    @app.put("/api/v1/whatsapp/instances/{instance_id}/rag/text", tags=["whatsapp"])
    async def update_rag_text(instance_id: str, request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        from ..whatsapp_agent import get_wa_manager
        return _JR(get_wa_manager().update_instance(instance_id, sess["user_id"], rag_text=body.get("text", "")))

    # ── Conversations ─────────────────────────────────────────

    @app.get("/api/v1/whatsapp/instances/{instance_id}/conversations", tags=["whatsapp"])
    async def list_conversations(instance_id: str, request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..whatsapp_agent import get_wa_manager
        inst = get_wa_manager().get_instance(instance_id, sess["user_id"])
        if not inst:
            return _JR({"error": "Nao encontrada"}, status_code=404)
        return _JR({"conversations": get_wa_manager().list_conversations(inst)})

    @app.get("/api/v1/whatsapp/instances/{instance_id}/conversations/{phone}", tags=["whatsapp"])
    async def get_conversation(instance_id: str, phone: str, request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..whatsapp_agent import get_wa_manager
        inst = get_wa_manager().get_instance(instance_id, sess["user_id"])
        if not inst:
            return _JR({"error": "Nao encontrada"}, status_code=404)
        return _JR({"messages": get_wa_manager().get_conversation_history(inst, phone)})

    @app.delete("/api/v1/whatsapp/instances/{instance_id}/conversations/{phone}", tags=["whatsapp"])
    async def clear_conversation(instance_id: str, phone: str, request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..whatsapp_agent import get_wa_manager
        inst = get_wa_manager().get_instance(instance_id, sess["user_id"])
        if not inst:
            return _JR({"error": "Nao encontrada"}, status_code=404)
        return _JR({"success": get_wa_manager().clear_conversation(inst, phone)})

    # ── Test Connection (standalone, no instance needed) ─────

    @app.post("/api/v1/whatsapp/instances/test-connection", tags=["whatsapp"])
    async def test_connection_standalone(request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        from ..whatsapp_agent import get_wa_manager
        return _JR(get_wa_manager().test_connection(body.get("zapi_instance_id", ""), body.get("zapi_token", "")))

    # ── Test Connection (existing instance) ───────────────────

    @app.post("/api/v1/whatsapp/instances/test", tags=["whatsapp"])
    async def test_wa_connection(request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        iid = body.get("instance_id", "").strip()
        tok = body.get("token", "").strip()
        if not iid or not tok:
            return _JR({"success": False, "error": "Instance ID e Token obrigatorios"}, status_code=400)
        import urllib.request, urllib.error, json as _json
        try:
            url = f"https://api.z-api.io/instances/{iid}/token/{tok}/status"
            req = urllib.request.Request(url)
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = _json.loads(resp.read().decode())
                ok = data.get("connected", False) or data.get("smartphoneConnected", False)
                return _JR({"success": True, "connected": ok, "message": "Conexao OK!" if ok else "Z-API acessivel mas WhatsApp nao conectado."})
        except urllib.error.HTTPError as e:
            return _JR({"success": False, "error": f"Erro Z-API: {e.code}"}, status_code=400)
        except Exception as e:
            return _JR({"success": False, "error": str(e)}, status_code=500)

    @app.post("/api/v1/whatsapp/instances/{instance_id}/test", tags=["whatsapp"])
    async def test_instance(instance_id: str, request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..whatsapp_agent import get_wa_manager
        inst = get_wa_manager().get_instance(instance_id, sess["user_id"])
        if not inst:
            return _JR({"error": "Nao encontrada"}, status_code=404)
        return _JR(get_wa_manager().test_connection(inst.zapi_instance_id, inst.zapi_token))

    # ── Meta API Webhook - Verification (GET) ────────────────



    
    # ── Meta Template Manager Routes ─────────────────────

    @app.get("/api/v1/whatsapp/templates/list", tags=["templates"])
    async def list_meta_templates(request: _Req):
        """List templates from Meta API + local DB status."""
        sess = _get_user_session(request)
        if not sess or not sess.get("is_admin"):
            return _JR({"error": "Acesso negado"}, status_code=403)
        import os as _os
        token = _os.getenv("META_ACCESS_TOKEN", "")
        waba = _os.getenv("META_WABA_ID", "")
        # Fetch from Meta
        meta_templates = []
        if token and waba:
            try:
                from urllib.request import urlopen, Request as _Req2
                url = f"https://graph.facebook.com/v18.0/{waba}/message_templates?fields=name,status,rejected_reason,category,language,components&limit=50"
                req = _Req2(url, headers={"Authorization": f"Bearer {token}"})
                resp = urlopen(req, timeout=15)
                data = json.loads(resp.read().decode())
                meta_templates = data.get("data", [])
            except Exception:
                pass
        # Fetch local DB
        from ..database import get_db
        with get_db() as db:
            local = db.execute("SELECT * FROM meta_templates WHERE user_id=? ORDER BY created_at DESC", (sess["user_id"],)).fetchall()
        local_dict = {r["template_name"]: dict(r) for r in local} if local else {}
        # Merge
        result = []
        for t in meta_templates:
            name = t.get("name", "")
            body = ""
            for comp in t.get("components", []):
                if comp.get("type") == "BODY":
                    body = comp.get("text", "")
            result.append({
                "name": name, "status": t.get("status", ""),
                "rejected_reason": t.get("rejected_reason", ""),
                "category": t.get("category", ""),
                "language": t.get("language", ""),
                "body": body,
                "local": local_dict.get(name, {}),
            })
        # Add local-only templates not yet in Meta
        for name, loc in local_dict.items():
            if not any(r["name"] == name for r in result):
                result.append({"name": name, "status": loc.get("status", "PENDING"),
                               "body": loc.get("template_text", ""), "category": loc.get("category", "UTILITY"),
                               "language": "pt_BR", "rejected_reason": loc.get("rejected_reason", ""), "local": loc})
        return _JR({"templates": result})

    @app.post("/api/v1/whatsapp/templates/submit", tags=["templates"])
    async def submit_meta_templates(request: _Req):
        """Submit templates to Meta for approval."""
        sess = _get_user_session(request)
        if not sess or not sess.get("is_admin"):
            return _JR({"error": "Acesso negado"}, status_code=403)
        body = await request.json()
        templates = body.get("templates", [])
        if not templates:
            return _JR({"error": "Nenhum template selecionado"}, status_code=400)
        import os as _os
        token = _os.getenv("META_ACCESS_TOKEN", "")
        waba = _os.getenv("META_WABA_ID", "")
        if not token or not waba:
            return _JR({"error": "META_ACCESS_TOKEN ou META_WABA_ID nao configurados"}, status_code=500)
        from urllib.request import urlopen, Request as _Req2
        from urllib.error import HTTPError
        from ..database import get_db
        results = []
        for tpl in templates:
            name = tpl.get("name", "").strip().lower().replace(" ", "_").replace("-", "_")
            text = tpl.get("text", "").strip()
            if not name or not text:
                results.append({"name": name, "success": False, "error": "Nome e texto obrigatorios"})
                continue
            try:
                url = f"https://graph.facebook.com/v18.0/{waba}/message_templates"
                payload = json.dumps({
                    "name": name, "language": "pt_BR", "category": "UTILITY",
                    "components": [{"type": "BODY", "text": text}]
                }).encode()
                req = _Req2(url, data=payload, headers={
                    "Content-Type": "application/json", "Authorization": f"Bearer {token}"
                }, method="POST")
                resp = urlopen(req, timeout=15)
                data = json.loads(resp.read().decode())
                tpl_id = data.get("id", "")
                with get_db() as db:
                    db.execute("INSERT INTO meta_templates (user_id,connection_id,template_id,template_name,template_text,category,status,submitted_at,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                               (sess["user_id"], _os.getenv("META_PHONE_NUMBER_ID",""), tpl_id, name, text, "UTILITY", "PENDING", time.time(), time.time()))
                results.append({"name": name, "success": True, "template_id": tpl_id})
            except HTTPError as e:
                err = e.read().decode()[:200] if e.fp else str(e)
                results.append({"name": name, "success": False, "error": err})
                with get_db() as db:
                    db.execute("INSERT INTO meta_templates (user_id,template_name,template_text,category,status,rejected_reason,created_at) VALUES (?,?,?,?,?,?,?)",
                               (sess["user_id"], name, text, "UTILITY", "FAILED", err[:200], time.time()))
            except Exception as e:
                results.append({"name": name, "success": False, "error": str(e)[:100]})
        return _JR({"results": results})

    @app.post("/api/v1/whatsapp/templates/refresh", tags=["templates"])
    async def refresh_template_status(request: _Req):
        """Refresh status of all templates from Meta API."""
        sess = _get_user_session(request)
        if not sess or not sess.get("is_admin"):
            return _JR({"error": "Acesso negado"}, status_code=403)
        import os as _os
        token = _os.getenv("META_ACCESS_TOKEN", "")
        waba = _os.getenv("META_WABA_ID", "")
        if not token or not waba:
            return _JR({"error": "Credenciais Meta nao configuradas"}, status_code=500)
        try:
            from urllib.request import urlopen, Request as _Req2
            url = f"https://graph.facebook.com/v18.0/{waba}/message_templates?fields=name,status,rejected_reason&limit=50"
            req = _Req2(url, headers={"Authorization": f"Bearer {token}"})
            resp = urlopen(req, timeout=15)
            data = json.loads(resp.read().decode())
            from ..database import get_db
            updated = 0
            for t in data.get("data", []):
                name = t.get("name", "")
                status = t.get("status", "")
                reason = t.get("rejected_reason", "") or ""
                with get_db() as db:
                    r = db.execute("UPDATE meta_templates SET status=?, rejected_reason=?, last_checked_at=?, approved_at=CASE WHEN ?='APPROVED' THEN ? ELSE approved_at END WHERE template_name=? AND status != ?",
                                   (status, reason, time.time(), status, time.time(), name, status))
                    if r.rowcount > 0:
                        updated += 1
            return _JR({"updated": updated, "total": len(data.get("data", []))})
        except Exception as e:
            return _JR({"error": str(e)[:200]}, status_code=500)


    # ── Blast Campaign Routes ────────────────────────────────

    @app.get("/api/v1/whatsapp/blast/templates", tags=["blast"])
    async def list_blast_templates(request: _Req):
        sess = _get_user_session(request)
        if not sess or not sess.get("is_admin"):
            return _JR({"error": "Acesso negado"}, status_code=403)
        from ..blast_sender import list_templates
        return _JR({"templates": list_templates()})

    @app.get("/api/v1/whatsapp/blast/campaigns", tags=["blast"])
    async def list_blast_campaigns(request: _Req):
        sess = _get_user_session(request)
        if not sess or not sess.get("is_admin"):
            return _JR({"error": "Acesso negado"}, status_code=403)
        from ..blast_sender import list_campaigns
        return _JR({"campaigns": list_campaigns(sess["user_id"])})

    @app.post("/api/v1/whatsapp/blast/campaigns", tags=["blast"])
    async def create_blast_campaign(request: _Req):
        sess = _get_user_session(request)
        if not sess or not sess.get("is_admin"):
            return _JR({"error": "Acesso negado"}, status_code=403)
        body = await request.json()
        from ..blast_sender import create_campaign
        return _JR(create_campaign(sess["user_id"], body.get("name",""), body.get("template_name",""), body.get("contacts",[])))

    @app.post("/api/v1/whatsapp/blast/campaigns/{cid}/start", tags=["blast"])
    async def start_blast(cid: str, request: _Req):
        sess = _get_user_session(request)
        if not sess or not sess.get("is_admin"):
            return _JR({"error": "Acesso negado"}, status_code=403)
        from ..blast_sender import start_campaign
        return _JR(start_campaign(cid))

    @app.get("/api/v1/whatsapp/blast/campaigns/{cid}/progress", tags=["blast"])
    async def blast_progress(cid: str, request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..blast_sender import get_campaign_progress
        return _JR(get_campaign_progress(cid))

    @app.post("/api/v1/whatsapp/blast/campaigns/{cid}/pause", tags=["blast"])
    async def pause_blast(cid: str, request: _Req):
        sess = _get_user_session(request)
        if not sess or not sess.get("is_admin"):
            return _JR({"error": "Acesso negado"}, status_code=403)
        from ..blast_sender import pause_campaign
        return _JR(pause_campaign(cid))


    # Meta API Webhook - Generic (no connection_id)
    @app.get("/api/v1/whatsapp/meta/webhook", tags=["whatsapp"], include_in_schema=False)
    async def meta_webhook_verify_generic(request: _Req):
        params = request.query_params
        mode = params.get("hub.mode", "")
        token = params.get("hub.verify_token", "")
        challenge = params.get("hub.challenge", "")
        if mode == "subscribe" and token in ("clow-webhook-2026", "clow-daniel-2026", os.getenv("META_VERIFY_TOKEN", "")):
            from fastapi.responses import PlainTextResponse
            return PlainTextResponse(challenge)
        return _JR({"error": "Verification failed"}, status_code=403)

    @app.post("/api/v1/whatsapp/meta/webhook", tags=["whatsapp"], include_in_schema=False)
    async def meta_webhook_receive_generic(request: _Req):
        try:
            body = await request.json()
        except Exception:
            return _JR({"status": "invalid"}, status_code=400)
        try:
            entry = body.get("entry", [{}])[0]
            changes = entry.get("changes", [{}])[0]
            value = changes.get("value", {})
            messages = value.get("messages", [])
            metadata = value.get("metadata", {})
            phone_number_id = metadata.get("phone_number_id", "")
            # Extract contact name
            contacts_list = value.get("contacts", [])
            if contacts_list:
                profile = contacts_list[0].get("profile", {})
                contact_name = profile.get("name", "")
                if contact_name and messages:
                    from_phone = messages[0].get("from", "")
                    if from_phone:
                        _meta_contact_names[from_phone] = contact_name
            # Skip status updates (delivery receipts)
            if value.get("statuses"):
                return _JR({"status": "status_update"})
            if not messages:
                return _JR({"status": "no_messages"})
            from ..whatsapp_agent import get_wa_manager, WhatsAppInstance
            from pathlib import Path
            inst = None
            wa_dir = Path.home() / ".clow" / "whatsapp_instances"
            if wa_dir.exists():
                for td in wa_dir.iterdir():
                    if not td.is_dir():
                        continue
                    for idir in td.iterdir():
                        if not idir.is_dir():
                            continue
                        c = WhatsAppInstance.load(idir)
                        if c and getattr(c, "provider", "zapi") == "meta" and getattr(c, "meta_phone_number_id", "") == phone_number_id:
                            inst = c
                            break
                    if inst:
                        break
            if not inst or not inst.active:
                return _JR({"status": "no_matching_instance"})
            for msg in messages:
                phone = msg.get("from", "")
                msg_type = msg.get("type", "")
                text = ""
                if msg_type == "text":
                    text = msg.get("text", {}).get("body", "")
                elif msg_type == "audio":
                    text = "[AUDIO] No momento so consigo te atender por texto. Me manda sua duvida escrita que te respondo!"
                elif msg_type in ("image", "document", "video", "sticker"):
                    text = "[MIDIA] No momento so consigo te atender com mensagens de texto. Me manda sua duvida por escrito!"
                elif msg_type == "reaction":
                    continue
                if not phone or not text:
                    continue
                key = inst.id + ":" + phone
                with _debounce_lock:
                    if key not in _debounce_buffers:
                        _debounce_buffers[key] = []
                    _debounce_buffers[key].append(text)
                    if key in _debounce_timers:
                        _debounce_timers[key].cancel()
                    iid = inst.id
                    p = phone
                    def flush(k=key, i=iid, ph=p):
                        with _debounce_lock:
                            msgs = _debounce_buffers.pop(k, [])
                            _debounce_timers.pop(k, None)
                        if msgs:
                            combined = " ".join(msgs)
                            try:
                                _process_meta_carol(i, ph, combined)
                            except Exception:
                                pass
                    timer = threading.Timer(DEBOUNCE_SECONDS, flush)
                    _debounce_timers[key] = timer
                    timer.start()
            return _JR({"status": "ok"})
        except Exception:
            return _JR({"status": "error"})

    @app.get("/api/v1/whatsapp/meta/webhook/{connection_id}", tags=["whatsapp"], include_in_schema=False)
    async def meta_webhook_verify(connection_id: str, request: _Req):
        """Meta webhook verification challenge."""
        params = request.query_params
        mode = params.get("hub.mode", "")
        token = params.get("hub.verify_token", "")
        challenge = params.get("hub.challenge", "")

        if mode == "subscribe":
            from ..whatsapp_agent import get_wa_manager
            inst = get_wa_manager().get_instance(connection_id)
            if inst and inst.meta_verify_token == token:
                from fastapi.responses import PlainTextResponse
                return PlainTextResponse(challenge)

        return _JR({"error": "Verification failed"}, status_code=403)

    # ── Meta API Webhook - Receive messages (POST) ────────────

    @app.post("/api/v1/whatsapp/meta/webhook/{connection_id}", tags=["whatsapp"], include_in_schema=False)
    async def meta_webhook_receive(connection_id: str, request: _Req):
        """Receive messages from Meta WhatsApp Business API."""
        try:
            body = await request.json()
        except Exception:
            return _JR({"status": "invalid"}, status_code=400)

        # Parse Meta webhook payload
        try:
            entry = body.get("entry", [{}])[0]
            changes = entry.get("changes", [{}])[0]
            value = changes.get("value", {})
            messages = value.get("messages", [])

            # Extract contact name
            contacts_list = value.get("contacts", [])
            if contacts_list:
                profile = contacts_list[0].get("profile", {})
                contact_name = profile.get("name", "")
                if contact_name and messages:
                    from_phone = messages[0].get("from", "")
                    if from_phone:
                        _meta_contact_names[from_phone] = contact_name
            # Skip status updates (delivery receipts)
            if value.get("statuses"):
                return _JR({"status": "status_update"})
            if not messages:
                return _JR({"status": "no_messages"})

            from ..whatsapp_agent import get_wa_manager
            inst = get_wa_manager().get_instance(connection_id)
            if not inst or not inst.active or inst.provider != "meta":
                return _JR({"status": "inactive"})

            for msg in messages:
                phone = msg.get("from", "")
                msg_type = msg.get("type", "")

                if msg_type == "text":
                    text = msg.get("text", {}).get("body", "")
                elif msg_type in ("image", "audio", "video", "document"):
                    text = f"[{msg_type} recebido]"
                else:
                    continue

                if not phone or not text:
                    continue

                # Use same debounce mechanism as Z-API
                key = f"{connection_id}:{phone}"
                with _debounce_lock:
                    if key not in _debounce_buffers:
                        _debounce_buffers[key] = []
                    _debounce_buffers[key].append(text)

                    if key in _debounce_timers:
                        _debounce_timers[key].cancel()

                    iid = connection_id
                    p = phone
                    def flush(k=key, i=iid, ph=p):
                        with _debounce_lock:
                            msgs = _debounce_buffers.pop(k, [])
                            _debounce_timers.pop(k, None)
                        if msgs:
                            combined = " ".join(msgs)
                            try:
                                _process_meta_carol(i, ph, combined)
                            except Exception as e:
                                logger.error(f"Meta process error: {e}")

                    timer = threading.Timer(DEBOUNCE_SECONDS, flush)
                    timer.daemon = True
                    _debounce_timers[key] = timer
                    timer.start()

            return _JR({"status": "ok"})
        except Exception as e:
            logger.error(f"Meta webhook error: {e}")
            return _JR({"status": "error"})

    # ── Test Meta Connection ──────────────────────────────────

    @app.post("/api/v1/whatsapp/instances/test-meta", tags=["whatsapp"])
    async def test_meta_connection(request: _Req):
        """Test Meta WhatsApp Business API connection."""
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        token = body.get("access_token", "").strip()
        phone_id = body.get("phone_number_id", "").strip()
        if not token or not phone_id:
            return _JR({"success": False, "error": "Access Token e Phone Number ID obrigatorios"}, status_code=400)
        from ..whatsapp_agent import get_wa_manager
        result = get_wa_manager().test_meta_connection(token, phone_id)
        return _JR({"success": result.get("connected", False), **result})

    # ── Webhook (public — Z-API calls this) ───────────────────

    @app.post("/api/v1/whatsapp/webhook/{instance_id}", tags=["whatsapp"], include_in_schema=False)
    async def whatsapp_webhook(instance_id: str, request: _Req):
        try:
            body = await request.json()
        except Exception:
            return _JR({"error": "Invalid JSON"}, status_code=400)

        phone = body.get("phone", "")
        message = body.get("body", "")
        from_me = body.get("fromMe", False)
        is_group = body.get("isGroup", False)
        msg_type = body.get("type", "")
        moment = body.get("momment", 0) or body.get("moment", 0)

        # Filters
        if from_me or is_group or msg_type != "chat" or not message or not phone:
            return _JR({"status": "ignored"})

        # Skip old messages (> 5 min)
        if moment and (time.time() - moment) > 300:
            return _JR({"status": "too_old"})

        # Validate instance exists
        from ..whatsapp_agent import get_wa_manager
        inst = get_wa_manager().get_instance(instance_id)
        if not inst or not inst.active:
            return _JR({"status": "inactive"})

        # Validate Z-API instance ID matches
        if body.get("instanceId") and body["instanceId"] != inst.zapi_instance_id:
            return _JR({"status": "instance_mismatch"})

        # Debounce: accumulate messages for 8 seconds
        key = f"{instance_id}:{phone}"
        with _debounce_lock:
            if key not in _debounce_buffers:
                _debounce_buffers[key] = []
            _debounce_buffers[key].append(message)

            # Cancel existing timer
            if key in _debounce_timers:
                _debounce_timers[key].cancel()

            # Start new timer
            def _process_debounced(k=key, iid=instance_id, p=phone):
                with _debounce_lock:
                    msgs = _debounce_buffers.pop(k, [])
                    _debounce_timers.pop(k, None)
                if msgs:
                    combined = "\n".join(msgs)
                    _process_with_chatwoot(iid, p, combined)

            timer = threading.Timer(DEBOUNCE_SECONDS, _process_debounced)
            timer.daemon = True
            _debounce_timers[key] = timer
            timer.start()

        return _JR({"status": "queued"})

    # ── Chatwoot Webhook (receives Chatwoot events) ───────────

    @app.post("/api/v1/chatwoot/webhook", tags=["chatwoot"], include_in_schema=False)
    async def chatwoot_webhook(request: _Req):
        """Receive Chatwoot events — detect label changes for handoff control."""
        try:
            body = await request.json()
        except Exception:
            return _JR({"status": "invalid"}, status_code=400)

        event = body.get("event", "")

        if event == "conversation_updated":
            convo = body.get("conversation", {})
            convo_id = convo.get("id")
            labels = convo.get("labels", [])

            # If "humano" label was removed, reactivate bot
            # We track this by checking if bot label is missing and humano is missing
            if "humano" not in labels and convo_id:
                try:
                    from ..chatwoot_integration import get_chatwoot_client, reactivate_bot
                    client = get_chatwoot_client("global")
                    if client and "bot" not in labels:
                        reactivate_bot(client, convo_id, send_greeting=True)
                except Exception as e:
                    logger.warning(f"Chatwoot webhook reactivate_bot error: {e}")

        return _JR({"status": "ok"})


def _process_with_chatwoot(instance_id: str, phone: str, combined_message: str):
    """Process incoming message with Chatwoot integration (optional).

    Wraps the original process_incoming with Chatwoot sync:
    1. Send incoming message to Chatwoot
    2. Check if 'humano' label is active -> skip AI if yes
    3. Call process_incoming for AI response
    4. Send AI response to Chatwoot as outgoing
    5. Check for handoff keywords / lead interest
    """
    from ..whatsapp_agent import get_wa_manager

    # --- Chatwoot integration (all wrapped in try/except — never blocks main flow) ---
    cw_client = None
    cw_convo_id = None
    handoff_label = os.getenv("CHATWOOT_HANDOFF_LABEL", "humano")

    try:
        chatwoot_url = os.getenv("CHATWOOT_URL", "")
        if chatwoot_url:
            from ..chatwoot_integration import (
                get_chatwoot_client,
                get_or_create_chatwoot_conversation,
                check_handoff_label,
                trigger_handoff,
                detect_lead_interest,
            )

            cw_client = get_chatwoot_client(instance_id)
            if cw_client:
                inbox_id = int(os.getenv("CHATWOOT_INBOX_ID", "1"))
                cw_convo_id = get_or_create_chatwoot_conversation(
                    cw_client, instance_id, phone, inbox_id
                )

                # Send the incoming message to Chatwoot
                if cw_convo_id:
                    cw_client.send_message(cw_convo_id, combined_message, message_type="incoming")

                # Check if handoff is active — if so, skip AI processing entirely
                if cw_convo_id and check_handoff_label(cw_client, cw_convo_id, handoff_label):
                    logger.info(f"Handoff active for {instance_id}:{phone[-4:]}, skipping AI")
                    return
    except Exception as e:
        logger.warning(f"Chatwoot pre-processing error (non-blocking): {e}")
        # Continue with normal processing even if Chatwoot fails

    # --- Normal AI processing ---
    reply = get_wa_manager().process_incoming(instance_id, phone, combined_message)

    # --- Chatwoot post-processing (send AI reply, check labels) ---
    if cw_client and cw_convo_id:
        try:
            # Send AI response to Chatwoot as outgoing message
            if reply:
                cw_client.send_message(cw_convo_id, "[Bot] " + reply, message_type="outgoing", private=True)

            # Check for handoff keywords in user message
            handoff_keywords = ["humano", "atendente", "pessoa", "gerente", "falar com alguem"]
            msg_lower = combined_message.lower()
            if any(kw in msg_lower for kw in handoff_keywords):
                try:
                    trigger_handoff(cw_client, cw_convo_id, reason="Cliente solicitou atendimento humano", label=handoff_label)
                except Exception as e:
                    logger.warning(f"Chatwoot trigger_handoff error: {e}")

            # Check for lead interest — add "lead-quente" label
            try:
                if detect_lead_interest(combined_message):
                    cw_client.add_label(cw_convo_id, "lead-quente")
            except Exception as e:
                logger.warning(f"Chatwoot lead label error: {e}")

        except Exception as e:
            logger.warning(f"Chatwoot post-processing error (non-blocking): {e}")
