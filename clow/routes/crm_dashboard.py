"""CRM Dashboard Routes — metricas do Chatwoot do cliente.

O CRM completo roda no Chatwoot. O Clow so mostra dashboard de metricas.
Se nao tem Chatwoot, mostra pagina de setup.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from fastapi import Request as _Req
from fastapi.responses import JSONResponse as _JR, HTMLResponse as _HR, RedirectResponse

_TPL_DIR = Path(__file__).resolve().parent.parent / "templates"

# Cache simples de metricas (5 min TTL)
_metrics_cache: dict = {}
_CACHE_TTL = 300


def _chatwoot_get(base_url: str, token: str, path: str, account_id: int = 1) -> dict | list | None:
    """GET na API do Chatwoot com tratamento de erro robusto."""
    url = f"{base_url.rstrip('/')}/api/v1/accounts/{account_id}/{path}"
    req = Request(url, headers={"api_access_token": token, "Content-Type": "application/json"})
    try:
        resp = urlopen(req, timeout=15)
        return json.loads(resp.read().decode())
    except HTTPError as e:
        return {"_error": f"HTTP {e.code}", "_status": e.code}
    except (URLError, Exception) as e:
        return {"_error": str(e)[:200]}


def register_crm_dashboard_routes(app) -> None:

    from .auth import _get_user_session

    def _auth(request: _Req):
        return _get_user_session(request)

    def _tenant(sess: dict) -> str:
        return sess["user_id"]

    def _get_infra(tenant_id: str) -> dict | None:
        from ..infra_setup import get_tenant_infra
        return get_tenant_infra(tenant_id)

    def _cached(tid: str) -> dict | None:
        entry = _metrics_cache.get(tid)
        if entry and time.time() - entry["ts"] < _CACHE_TTL:
            return entry["data"]
        return None

    # ── Pagina principal ──

    @app.get("/crm", tags=["crm"])
    @app.get("/app/crm", tags=["crm"])
    async def crm_page(request: _Req):
        sess = _auth(request)
        if not sess:
            return RedirectResponse("/login")

        from ..database import get_user_by_id
        from ..billing import PLANS
        user = get_user_by_id(_tenant(sess))
        plan_id = user.get("plan", "byok_free") if user else "byok_free"
        if plan_id in ("free", "basic", "unlimited"):
            plan_id = "byok_free"
        plan = PLANS.get(plan_id, PLANS["byok_free"])
        if not plan.get("crm_enabled", False) and not sess.get("is_admin"):
            return _HR("<html><head><meta charset='UTF-8'><title>CRM</title><style>body{background:#050510;color:#e4e4e7;font-family:system-ui;display:flex;align-items:center;justify-content:center;min-height:100vh;text-align:center}a{color:#7c5cfc}</style></head><body><div><h2>CRM disponivel nos planos pagos</h2><p>A partir do plano Lite (R$ 97/mes)</p><a href='/app/settings'>Fazer upgrade</a> | <a href='/'>Voltar</a></div></body></html>")

        infra = _get_infra(_tenant(sess))
        if not infra or not infra.get("chatwoot_url"):
            tpl = _TPL_DIR / "crm_setup.html"
            if tpl.exists():
                return _HR(tpl.read_text(encoding="utf-8"))
            return RedirectResponse("/setup")

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

        force = request.query_params.get("force", "") == "1"
        if not force:
            cached = _cached(tid)
            if cached:
                return _JR(cached)

        infra = _get_infra(tid)
        if not infra or not infra.get("chatwoot_url"):
            return _JR({"connected": False, "error": "chatwoot_not_configured"})

        url = infra["chatwoot_url"]
        token = infra["api_token"]

        # Testa conexao (profile e endpoint global, nao por account)
        try:
            req = Request(f"{url.rstrip('/')}/api/v1/profile", headers={"api_access_token": token})
            resp = urlopen(req, timeout=10)
            test = json.loads(resp.read().decode())
        except Exception as e:
            test = {"_error": str(e)[:200]}
        if not test or test.get("_error"):
            return _JR({"connected": False, "error": test.get("_error", "Chatwoot inacessivel"), "url": url})

        # Puxa dados
        convs_open = _chatwoot_get(url, token, "conversations?status=open&page=1")
        convs_resolved = _chatwoot_get(url, token, "conversations?status=resolved&page=1")
        inboxes_data = _chatwoot_get(url, token, "inboxes")
        contacts_data = _chatwoot_get(url, token, "contacts?page=1")
        labels_data = _chatwoot_get(url, token, "labels")
        agents_data = _chatwoot_get(url, token, "agents")

        # Parse conversas
        open_count = 0
        resolved_count = 0
        if isinstance(convs_open, dict) and "data" in convs_open:
            open_count = convs_open.get("data", {}).get("meta", {}).get("all_count", 0)
        if isinstance(convs_resolved, dict) and "data" in convs_resolved:
            resolved_count = convs_resolved.get("data", {}).get("meta", {}).get("all_count", 0)

        # Parse inboxes
        inboxes = []
        if isinstance(inboxes_data, dict):
            for ib in inboxes_data.get("payload", []):
                inboxes.append({
                    "id": ib.get("id"), "name": ib.get("name"),
                    "channel_type": ib.get("channel_type", ""),
                })

        # Parse contacts
        contacts_count = 0
        if isinstance(contacts_data, dict):
            contacts_count = len(contacts_data.get("payload", []))

        # Parse labels
        labels = []
        if isinstance(labels_data, dict):
            labels = [{"title": l.get("title"), "color": l.get("color")} for l in labels_data.get("payload", [])]

        # Parse agents
        agents = []
        if isinstance(agents_data, list):
            agents = [{"name": a.get("name"), "email": a.get("email")} for a in agents_data]

        data = {
            "connected": True,
            "url": url,
            "conversations_open": open_count,
            "conversations_resolved": resolved_count,
            "contacts_count": contacts_count,
            "inboxes": inboxes,
            "inboxes_count": len(inboxes),
            "labels": labels,
            "agents": agents,
            "last_sync": time.time(),
        }

        _metrics_cache[tid] = {"data": data, "ts": time.time()}
        return _JR(data)

    @app.get("/api/v1/crm/health", tags=["crm"])
    async def crm_health(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        infra = _get_infra(_tenant(sess))
        if not infra:
            return _JR({"online": False, "error": "Chatwoot nao configurado"})
        try:
            req = Request(f"{infra['chatwoot_url'].rstrip('/')}/api/v1/profile", headers={"api_access_token": infra["api_token"]})
            resp = urlopen(req, timeout=10)
            return _JR({"online": True, "url": infra["chatwoot_url"]})
        except Exception as e:
            return _JR({"online": False, "error": str(e)[:200], "url": infra["chatwoot_url"]})

    @app.post("/api/v1/crm/dashboard/refresh", tags=["crm"])
    async def crm_refresh(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        _metrics_cache.pop(_tenant(sess), None)
        return _JR({"invalidated": True})

    # ── Conexao manual ──

    @app.post("/api/v1/crm/connect", tags=["crm"])
    async def crm_connect_manual(request: _Req):
        """Conecta manualmente um Chatwoot existente."""
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        url = (body.get("chatwoot_url") or body.get("url") or "").strip().rstrip("/")
        token = (body.get("api_token") or body.get("token") or "").strip()
        if not url or not token:
            return _JR({"error": "URL e token obrigatorios"}, status_code=400)

        # Testa
        test = _chatwoot_get(url, token, "profile")
        if not test or test.get("_error"):
            return _JR({"error": f"Nao conseguiu conectar: {test.get('_error', 'erro')}"}, status_code=400)

        # Salva
        from ..infra_setup import save_tenant_infra
        save_tenant_infra(_tenant(sess), url, token)
        _metrics_cache.pop(_tenant(sess), None)
        return _JR({"connected": True, "url": url})
