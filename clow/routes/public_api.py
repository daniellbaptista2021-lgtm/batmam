"""Public API — endpoints autenticados por API key para integracoes externas.

Autenticacao: header X-Clow-API-Key
Rate limit: 60 req/min por key
"""

from __future__ import annotations

from fastapi import Request as _Req
from fastapi.responses import JSONResponse as _JR


def register_public_api_routes(app) -> None:

    def _auth_api(request: _Req) -> str | None:
        """Autentica via API key. Retorna tenant_id ou None."""
        key = request.headers.get("X-Clow-API-Key", "")
        if not key:
            return None
        from ..api_keys import validate_key
        return validate_key(key)

    def _err401():
        return _JR({"error": "API key invalida ou ausente. Use header X-Clow-API-Key."}, status_code=401)

    # ── API Key Management (via session auth) ──

    from .auth import _get_user_session

    @app.get("/api/v1/api-keys", tags=["api-keys"])
    async def api_keys_list(request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..api_keys import list_keys
        return _JR({"keys": list_keys(sess["user_id"])})

    @app.post("/api/v1/api-keys", tags=["api-keys"])
    async def api_keys_create(request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        from ..api_keys import generate_key
        key = generate_key(sess["user_id"], body.get("name", "default"))
        return _JR({"key": key, "message": "Copie a key agora. Ela nao sera exibida novamente."})

    @app.delete("/api/v1/api-keys/{key_id}", tags=["api-keys"])
    async def api_keys_revoke(key_id: str, request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..api_keys import revoke_key
        ok = revoke_key(sess["user_id"], key_id)
        return _JR({"success": ok})

    # ══════════════════════════════════════════════════════════
    # PUBLIC API (autenticada por X-Clow-API-Key)
    # ══════════════════════════════════════════════════════════

    # ── Leads ──

    @app.get("/public/v1/leads", tags=["public-api"])
    async def pub_leads(request: _Req):
        tid = _auth_api(request)
        if not tid:
            return _err401()
        from ..crm_models import list_leads
        instance_id = request.query_params.get("instance_id", "")
        status = request.query_params.get("stage", request.query_params.get("status", ""))
        page = int(request.query_params.get("page", "1"))
        limit = int(request.query_params.get("limit", "50"))
        return _JR(list_leads(tid, status=status, instance_id=instance_id, page=page, limit=limit))

    @app.post("/public/v1/leads", tags=["public-api"])
    async def pub_create_lead(request: _Req):
        tid = _auth_api(request)
        if not tid:
            return _err401()
        body = await request.json()
        from ..crm_models import create_lead
        lead = create_lead(
            tid, name=body.get("name", ""), email=body.get("email", ""),
            phone=body.get("phone", ""), source=body.get("source", "api"),
            instance_id=body.get("instance_id", ""),
        )
        return _JR(lead)

    @app.get("/public/v1/leads/{lead_id}", tags=["public-api"])
    async def pub_get_lead(lead_id: str, request: _Req):
        tid = _auth_api(request)
        if not tid:
            return _err401()
        from ..crm_models import get_lead, get_lead_timeline
        lead = get_lead(lead_id, tid)
        if not lead:
            return _JR({"error": "Lead nao encontrado"}, status_code=404)
        lead["timeline"] = get_lead_timeline(lead_id, tid)
        return _JR(lead)

    @app.put("/public/v1/leads/{lead_id}", tags=["public-api"])
    async def pub_update_lead(lead_id: str, request: _Req):
        tid = _auth_api(request)
        if not tid:
            return _err401()
        body = await request.json()
        from ..crm_models import update_lead
        lead = update_lead(lead_id, tid, **body)
        if not lead:
            return _JR({"error": "Lead nao encontrado"}, status_code=404)
        return _JR(lead)

    @app.delete("/public/v1/leads/{lead_id}", tags=["public-api"])
    async def pub_delete_lead(lead_id: str, request: _Req):
        tid = _auth_api(request)
        if not tid:
            return _err401()
        from ..crm_models import delete_lead
        ok = delete_lead(lead_id, tid)
        return _JR({"success": ok})

    @app.put("/public/v1/leads/{lead_id}/stage", tags=["public-api"])
    async def pub_lead_stage(lead_id: str, request: _Req):
        tid = _auth_api(request)
        if not tid:
            return _err401()
        body = await request.json()
        from ..crm_models import change_lead_status
        lead = change_lead_status(lead_id, tid, body.get("stage", ""))
        if not lead:
            return _JR({"error": "Lead nao encontrado"}, status_code=404)
        return _JR(lead)

    # ── Mensagens ──

    @app.post("/public/v1/messages/send", tags=["public-api"])
    async def pub_send_msg(request: _Req):
        tid = _auth_api(request)
        if not tid:
            return _err401()
        body = await request.json()
        phone = body.get("phone", "")
        message = body.get("message", "")
        instance_id = body.get("instance_id", "")
        if not phone or not message:
            return _JR({"error": "phone e message obrigatorios"}, status_code=400)
        from ..whatsapp_agent import get_wa_manager
        manager = get_wa_manager()
        inst = manager.get_instance(instance_id, tid) if instance_id else None
        if not inst:
            instances = manager.get_instances(tid)
            inst = manager.get_instance(instances[0]["id"], tid) if instances else None
        if not inst:
            return _JR({"error": "Nenhuma instancia WhatsApp"}, status_code=400)
        ok = manager._send_zapi(inst, phone, message)
        return _JR({"sent": ok})

    # ── Metricas ──

    @app.get("/public/v1/metrics", tags=["public-api"])
    async def pub_metrics(request: _Req):
        tid = _auth_api(request)
        if not tid:
            return _err401()
        instance_id = request.query_params.get("instance_id", "")
        period = request.query_params.get("period", "30d")
        days = int(period.replace("d", "")) if period.endswith("d") else 30
        from ..crm_models import get_results_data
        return _JR(get_results_data(tid, instance_id, days))

    @app.get("/public/v1/metrics/funnel", tags=["public-api"])
    async def pub_funnel(request: _Req):
        tid = _auth_api(request)
        if not tid:
            return _err401()
        instance_id = request.query_params.get("instance_id", "")
        if instance_id:
            from ..crm_models import get_instance_metrics
            m = get_instance_metrics(tid, instance_id)
            return _JR({"pipeline": m.get("pipeline", {})})
        from ..crm_models import get_dashboard_stats
        return _JR({"pipeline": get_dashboard_stats(tid).get("leads_by_status", {})})

    # ── Instancias ──

    @app.get("/public/v1/instances", tags=["public-api"])
    async def pub_instances(request: _Req):
        tid = _auth_api(request)
        if not tid:
            return _err401()
        from ..whatsapp_agent import get_wa_manager
        return _JR({"instances": get_wa_manager().get_instances(tid)})
