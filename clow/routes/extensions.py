"""Extension routes — Autopilot, Automations, Spectator, Teleport, Teams.

TODOS os endpoints requerem autenticacao (exceto webhook GitHub que usa signature).
"""

from __future__ import annotations
import json
import time
from typing import Any


from fastapi import Request as _FRequest
from fastapi.responses import JSONResponse as _FJSON


def _require_auth(request: _FRequest) -> dict | None:
    from .auth import _get_user_session
    return _get_user_session(request)


def _require_admin(request: _FRequest) -> dict | None:
    sess = _require_auth(request)
    return sess if sess and sess.get("is_admin") else None


def _unauth():
    return _FJSON({"error": "Nao autenticado"}, status_code=401)


def _forbidden():
    return _FJSON({"error": "Acesso negado"}, status_code=403)


def register_extension_routes(app) -> None:
    """Registra endpoints protegidos."""

    from fastapi.responses import StreamingResponse

    # ── GitHub Autopilot Webhook (protegido por signature) ────

    @app.post("/api/webhooks/github", tags=["autopilot"], include_in_schema=False)
    async def github_webhook(request: _FRequest):
        from ..autopilot import handle_webhook, verify_webhook_signature

        body = await request.body()
        signature = request.headers.get("X-Hub-Signature-256", "")

        if not verify_webhook_signature(body, signature):
            return _FJSON({"error": "Invalid signature"}, status_code=401)

        event_type = request.headers.get("X-GitHub-Event", "")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return _FJSON({"error": "Invalid JSON"}, status_code=400)

        from ..automations import get_automations_engine
        get_automations_engine().handle_github_event(event_type, payload)

        return _FJSON(handle_webhook(event_type, payload))

    # ── Admin Metrics ──────────────────────────────────────────

    @app.get("/api/v1/admin/metrics", tags=["admin"], include_in_schema=False)
    async def admin_metrics(request: _FRequest):
        if not _require_admin(request):
            return _forbidden()
        from ..metrics_collector import get_admin_metrics
        return _FJSON(get_admin_metrics())

    # ── GitHub Autopilot ──────────────────────────────────────

    @app.get("/api/autopilot/status", tags=["autopilot"], include_in_schema=False)
    async def autopilot_status(request: _FRequest):
        if not _require_admin(request):
            return _forbidden()
        from ..autopilot import list_runs, get_active_runs
        return _FJSON({"active": get_active_runs(), "recent": list_runs(10)})

    @app.get("/api/autopilot/runs/{run_id}", tags=["autopilot"], include_in_schema=False)
    async def autopilot_run_detail(run_id: int, request: _FRequest):
        if not _require_admin(request):
            return _forbidden()
        from ..autopilot import get_run
        run = get_run(run_id)
        return _FJSON(run) if run else JSONResponse({"error": "Not found"}, status_code=404)

    # ── Automations Engine (auth required) ────────────────────

    @app.get("/api/automations/dashboard", tags=["automations"], include_in_schema=False)
    async def automations_dashboard(request: _FRequest):
        if not _require_auth(request):
            return _unauth()
        from ..automations import get_automations_engine
        return _FJSON(get_automations_engine().dashboard())

    @app.post("/api/automations/{name}/trigger", tags=["automations"], include_in_schema=False)
    async def trigger_automation(name: str, request: _FRequest):
        if not _require_auth(request):
            return _unauth()
        from ..automations import get_automations_engine
        try:
            body = await request.json()
        except Exception:
            body = {}
        return _FJSON(get_automations_engine().trigger(name, body))

    @app.get("/api/automations/logs", tags=["automations"], include_in_schema=False)
    async def automations_logs(request: _FRequest, name: str | None = None, limit: int = 50):
        if not _require_auth(request):
            return _unauth()
        from ..automations import get_automations_engine
        return _FJSON({"logs": get_automations_engine().get_logs(name, min(limit, 50))})

    # ── Teleport (auth required) ──────────────────────────────

    @app.post("/api/teleport/export/{session_id}", tags=["teleport"], include_in_schema=False)
    async def teleport_export(session_id: str, request: _FRequest):
        if not _require_auth(request):
            return _unauth()
        from ..teleport import export_session
        return _FJSON(export_session(session_id))

    @app.post("/api/teleport/import", tags=["teleport"], include_in_schema=False)
    async def teleport_import(request: _FRequest):
        if not _require_auth(request):
            return _unauth()
        from ..teleport import import_session
        return _FJSON(import_session(await request.json()))

    @app.post("/api/teleport/code/generate", tags=["teleport"], include_in_schema=False)
    async def teleport_generate_code(request: _FRequest):
        if not _require_auth(request):
            return _unauth()
        from ..teleport import generate_teleport_code
        body = await request.json()
        return _FJSON(generate_teleport_code(body.get("session_id", "")))

    @app.post("/api/teleport/code/redeem", tags=["teleport"], include_in_schema=False)
    async def teleport_redeem_code(request: _FRequest):
        if not _require_auth(request):
            return _unauth()
        from ..teleport import redeem_teleport_code
        body = await request.json()
        return _FJSON(redeem_teleport_code(body.get("code", "")))

    @app.get("/api/teleport/codes", tags=["teleport"], include_in_schema=False)
    async def teleport_list_codes(request: _FRequest):
        if not _require_admin(request):
            return _forbidden()
        from ..teleport import list_active_codes
        return _FJSON({"codes": list_active_codes()})

    # ── Teams (auth required) ─────────────────────────────────

    @app.get("/api/teams/roles", tags=["teams"], include_in_schema=False)
    async def teams_default_roles(request: _FRequest):
        if not _require_auth(request):
            return _unauth()
        from ..teams import DEFAULT_ROLES
        # Retorna apenas nomes e descricoes, nao tools internas
        safe_roles = {
            k: {"name": v["name"], "description": v["description"]}
            for k, v in DEFAULT_ROLES.items()
        }
        return _FJSON({"roles": safe_roles})

    # ── NL Automations (auth required) ────────────────────────

    @app.post("/api/automations/parse-nl", tags=["automations"], include_in_schema=False)
    async def parse_nl_automation(request: _FRequest):
        if not _require_auth(request):
            return _unauth()
        from ..automations import parse_natural_language
        body = await request.json()
        return _FJSON(parse_natural_language(body.get("text", "")))

    @app.post("/api/automations/create-nl", tags=["automations"], include_in_schema=False)
    async def create_nl_automation(request: _FRequest):
        if not _require_auth(request):
            return _unauth()
        from ..automations import create_from_natural_language
        body = await request.json()
        return _FJSON(create_from_natural_language(body.get("text", "")))

    # ── Spectator (auth required, share_token para read-only) ─

    @app.get("/api/spectator/{session_id}", tags=["spectator"], include_in_schema=False)
    async def spectator_sse(session_id: str, request: _FRequest, token: str | None = None):
        from ..spectator import get_spectator, get_spectator_by_token, format_sse
        from .. import config

        if not config.CLOW_SPECTATOR:
            return _forbidden()

        # Auth: user autenticado OU share_token valido (read-only)
        sess = _require_auth(request)
        spectator = get_spectator(session_id)

        if not sess:
            # Tenta share_token para acesso read-only
            if token:
                spectator = get_spectator_by_token(token)
            if not spectator:
                return _unauth()

        if not spectator:
            return _FJSON({"error": "Sessao nao encontrada"}, status_code=404)

        subscriber_queue = spectator.subscribe()

        def event_stream():
            yield format_sse({"type": "connected", "timestamp": time.time(), "data": {"subscribers": spectator.subscriber_count}})
            try:
                while True:
                    try:
                        event = subscriber_queue.get(timeout=30)
                        yield format_sse(event)
                    except Exception:
                        yield f"event: heartbeat\ndata: {{}}\n\n"
            finally:
                spectator.unsubscribe(subscriber_queue)

        return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})

    @app.post("/api/spectator/{session_id}/approve", tags=["spectator"], include_in_schema=False)
    async def spectator_approve(session_id: str, request: _FRequest):
        # Approve requer auth completa (nao apenas share_token)
        if not _require_auth(request):
            return _unauth()
        from ..spectator import get_spectator
        spectator = get_spectator(session_id)
        if not spectator:
            return _FJSON({"error": "Session not found"}, status_code=404)
        body = await request.json()
        return _FJSON({"success": spectator.resolve_approval(body.get("approval_id", ""), body.get("approved", False))})

    @app.get("/api/spectator", tags=["spectator"], include_in_schema=False)
    async def list_spectators_endpoint(request: _FRequest):
        if not _require_admin(request):
            return _forbidden()
        from ..spectator import list_spectators
        return _FJSON({"sessions": list_spectators()})

    @app.get("/spectator/{session_id}", tags=["spectator"], include_in_schema=False)
    async def spectator_page(session_id: str, request: _FRequest):
        # Requer auth para ver a pagina
        if not _require_auth(request):
            from fastapi.responses import RedirectResponse
            return RedirectResponse("/login", status_code=302)
        from fastapi.responses import HTMLResponse
        return HTMLResponse(_spectator_html(session_id))


def _spectator_html(session_id: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="pt-br"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Clow Spectator</title><link rel="icon" href="/static/brand/favicon.png">
<style>*{{margin:0;padding:0;box-sizing:border-box}}body{{font-family:'JetBrains Mono',monospace;background:#0d1117;color:#c9d1d9;height:100vh}}.header{{background:#161b22;padding:12px 20px;border-bottom:1px solid #30363d;display:flex;justify-content:space-between;align-items:center}}.header h1{{font-size:16px;color:#9B59FC}}.status{{font-size:12px;color:#3fb950}}.container{{display:flex;height:calc(100vh - 48px)}}.panel{{flex:1;overflow-y:auto;padding:16px;border-right:1px solid #30363d}}.panel:last-child{{border-right:none}}.panel-title{{font-size:13px;color:#8b949e;margin-bottom:12px;text-transform:uppercase;letter-spacing:1px}}.event{{margin-bottom:8px;padding:8px 12px;border-radius:6px;font-size:13px;line-height:1.5}}.event-tool_call{{background:#1c2333;border-left:3px solid #9B59FC}}.event-tool_result{{background:#1c2333;border-left:3px solid #3fb950}}.event-text_delta{{color:#e6edf3}}.tool-name{{color:#9B59FC;font-weight:bold}}.tool-status{{color:#3fb950}}pre{{white-space:pre-wrap;word-break:break-all}}</style></head>
<body><div class="header"><h1>Clow Spectator</h1><span class="status" id="status">Conectando...</span></div>
<div class="container"><div class="panel" id="terminal"><div class="panel-title">Terminal</div></div><div class="panel" id="diffs"><div class="panel-title">Diffs</div></div></div>
<script>const sid="{session_id}",t=document.getElementById("terminal"),d=document.getElementById("diffs"),st=document.getElementById("status");let buf="";const es=new EventSource("/api/spectator/"+sid);es.addEventListener("connected",()=>{{st.textContent="Conectado";st.style.color="#3fb950"}});es.addEventListener("text_delta",e=>{{const x=JSON.parse(e.data);buf+=x.data.text;let el=t.querySelector(".ct");if(!el){{el=document.createElement("div");el.className="event event-text_delta ct";t.appendChild(el)}}el.textContent=buf;t.scrollTop=t.scrollHeight}});es.addEventListener("text_done",()=>{{buf="";const el=t.querySelector(".ct");if(el)el.classList.remove("ct")}});es.addEventListener("tool_call",e=>{{const x=JSON.parse(e.data).data,el=document.createElement("div");el.className="event event-tool_call";el.innerHTML='<span class="tool-name">'+x.name+"</span> "+JSON.stringify(x.arguments).substring(0,200);t.appendChild(el);t.scrollTop=t.scrollHeight}});es.addEventListener("tool_result",e=>{{const x=JSON.parse(e.data).data,el=document.createElement("div");el.className="event event-tool_result";el.innerHTML='<span class="tool-name">'+x.name+'</span> <span class="tool-status">['+x.status+"]</span><pre>"+(x.output||"").substring(0,300)+"</pre>";t.appendChild(el);t.scrollTop=t.scrollHeight}});es.addEventListener("heartbeat",()=>{{}});es.onerror=()=>{{st.textContent="Desconectado";st.style.color="#f85149"}};</script></body></html>"""
