"""CRM Dashboard Routes — metricas do Chatwoot do cliente.

O CRM completo roda no Chatwoot. O Clow so mostra dashboard de metricas.
Se nao tem Chatwoot, mostra pagina de setup.
"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import Request as _Req
from fastapi.responses import JSONResponse as _JR, HTMLResponse as _HR, RedirectResponse

_TPL_DIR = Path(__file__).resolve().parent.parent / "templates"

# Cache simples de metricas (5 min TTL)
_metrics_cache: dict = {}
_CACHE_TTL = 300


def register_crm_dashboard_routes(app) -> None:

    from .auth import _get_user_session

    def _auth(request: _Req):
        return _get_user_session(request)

    def _tenant(sess: dict) -> str:
        return sess["user_id"]

    def _get_sync(tenant_id: str):
        from ..chatwoot_sync import get_sync_client
        return get_sync_client(tenant_id)

    def _cached_metrics(tenant_id: str) -> dict | None:
        entry = _metrics_cache.get(tenant_id)
        if entry and time.time() - entry["ts"] < _CACHE_TTL:
            return entry["data"]
        return None

    def _set_cache(tenant_id: str, data: dict):
        _metrics_cache[tenant_id] = {"data": data, "ts": time.time()}

    # ── Pagina principal ──

    @app.get("/crm", tags=["crm"])
    @app.get("/app/crm", tags=["crm"])
    async def crm_page(request: _Req):
        sess = _auth(request)
        if not sess:
            return RedirectResponse("/login")

        # Verifica CRM habilitado no plano
        from ..database import get_user_by_id
        from ..billing import PLANS
        user = get_user_by_id(_tenant(sess))
        plan_id = user.get("plan", "byok_free") if user else "byok_free"
        if plan_id in ("free", "basic", "unlimited"):
            plan_id = "byok_free"
        plan = PLANS.get(plan_id, PLANS["byok_free"])
        if not plan.get("crm_enabled", False) and not sess.get("is_admin"):
            tpl = _TPL_DIR / "crm_locked.html"
            if tpl.exists():
                return _HR(tpl.read_text(encoding="utf-8"))
            return _HR("<h1 style='text-align:center;margin-top:80px;font-family:sans-serif;color:#fff;background:#050510;min-height:100vh;padding-top:100px'>CRM disponivel nos planos pagos. <a href='/app/settings' style='color:#7c5cfc'>Fazer upgrade</a></h1>")

        # Verifica Chatwoot configurado
        from ..infra_setup import get_tenant_infra
        infra = get_tenant_infra(_tenant(sess))

        if not infra or not infra.get("chatwoot_url"):
            tpl = _TPL_DIR / "crm_setup.html"
            if tpl.exists():
                return _HR(tpl.read_text(encoding="utf-8"))
            return RedirectResponse("/setup")

        # Dashboard
        tpl = _TPL_DIR / "crm_dashboard.html"
        if tpl.exists():
            html = tpl.read_text(encoding="utf-8")
            html = html.replace("{{CHATWOOT_URL}}", infra["chatwoot_url"])
            return _HR(html)
        return _HR("<h1>CRM Dashboard</h1>")

    # ── API de metricas ──

    @app.get("/api/v1/crm/dashboard", tags=["crm"])
    async def crm_dashboard_data(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        tid = _tenant(sess)

        # Cache
        force = request.query_params.get("force", "") == "1"
        if not force:
            cached = _cached_metrics(tid)
            if cached:
                return _JR(cached)

        client = _get_sync(tid)
        if not client:
            return _JR({"error": "Chatwoot nao configurado"}, status_code=400)

        try:
            # Puxa dados do Chatwoot
            inboxes = client.list_inboxes()
            wa_inboxes = client.get_whatsapp_inboxes()

            # Conversas por status
            open_convs = client.list_conversations(status="open", page=1)
            resolved_convs = client.list_conversations(status="resolved", page=1)
            pending_convs = client.list_conversations(status="pending", page=1)

            open_count = len(open_convs)
            resolved_count = len(resolved_convs)
            pending_count = len(pending_convs)

            # Contatos
            contacts = client.list_contacts(page=1)

            # Canais
            channels = {}
            for inbox in inboxes:
                ch_type = inbox.get("channel_type", "other")
                name = inbox.get("name", ch_type)
                channels[name] = channels.get(name, 0) + 1

            data = {
                "conversations_open": open_count,
                "conversations_resolved": resolved_count,
                "conversations_pending": pending_count,
                "conversations_total": open_count + resolved_count + pending_count,
                "contacts_count": len(contacts),
                "inboxes_count": len(inboxes),
                "whatsapp_inboxes": len(wa_inboxes),
                "channels": [{"name": inbox.get("name", ""), "type": inbox.get("channel_type", ""), "id": inbox.get("id", 0)} for inbox in inboxes],
                "last_sync": time.time(),
            }

            _set_cache(tid, data)
            return _JR(data)
        except Exception as e:
            return _JR({"error": str(e)[:200]}, status_code=502)

    @app.get("/api/v1/crm/health", tags=["crm"])
    async def crm_health(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..infra_setup import get_infra_status
        return _JR(get_infra_status(_tenant(sess)))

    @app.post("/api/v1/crm/dashboard/refresh", tags=["crm"])
    async def crm_refresh(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        tid = _tenant(sess)
        _metrics_cache.pop(tid, None)
        return _JR({"invalidated": True})
