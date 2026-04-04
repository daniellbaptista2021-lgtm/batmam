"""WhatsApp Agent routes — CRUD instances, webhook, conversations."""

from __future__ import annotations
import time
import threading
from pathlib import Path

from fastapi import Request as _Req
from fastapi.responses import JSONResponse as _JR, HTMLResponse as _HR, RedirectResponse


# Debounce buffers: {instance_id:phone -> [messages]}
_debounce_buffers: dict[str, list[str]] = {}
_debounce_timers: dict[str, threading.Timer] = {}
_debounce_lock = threading.Lock()
DEBOUNCE_SECONDS = 8


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
        return _JR(d)

    @app.put("/api/v1/whatsapp/instances/{instance_id}", tags=["whatsapp"])
    async def update_instance(instance_id: str, request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        from ..whatsapp_agent import get_wa_manager
        allowed = {"name", "zapi_instance_id", "zapi_token", "system_prompt", "rag_text", "active", "context_size", "handoff_enabled", "handoff_keyword"}
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

    # ── Test Connection ───────────────────────────────────────

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
                    get_wa_manager().process_incoming(iid, p, combined)

            timer = threading.Timer(DEBOUNCE_SECONDS, _process_debounced)
            timer.daemon = True
            _debounce_timers[key] = timer
            timer.start()

        return _JR({"status": "queued"})
