"""Extension routes — Autopilot, Automations, Spectator."""

from __future__ import annotations
import json
import time
from typing import Any


def register_extension_routes(app) -> None:
    """Registra endpoints de Autopilot, Automations e Spectator."""

    from fastapi import Request, Response
    from fastapi.responses import JSONResponse, StreamingResponse

    # ── GitHub Autopilot Webhook ──────────────────────────────

    @app.post("/api/webhooks/github", tags=["autopilot"])
    async def github_webhook(request: Request):
        """Recebe webhooks do GitHub para o Autopilot."""
        from ..autopilot import handle_webhook, verify_webhook_signature

        body = await request.body()
        signature = request.headers.get("X-Hub-Signature-256", "")

        if not verify_webhook_signature(body, signature):
            return JSONResponse({"error": "Invalid signature"}, status_code=401)

        event_type = request.headers.get("X-GitHub-Event", "")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)

        # Rota para automations engine tambem
        from ..automations import get_automations_engine
        engine = get_automations_engine()
        engine.handle_github_event(event_type, payload)

        result = handle_webhook(event_type, payload)
        return JSONResponse(result)

    @app.get("/api/autopilot/status", tags=["autopilot"])
    async def autopilot_status():
        """Status das execucoes do autopilot."""
        from ..autopilot import list_runs, get_active_runs
        return JSONResponse({
            "active": get_active_runs(),
            "recent": list_runs(10),
        })

    @app.get("/api/autopilot/runs/{run_id}", tags=["autopilot"])
    async def autopilot_run_detail(run_id: int):
        from ..autopilot import get_run
        run = get_run(run_id)
        if not run:
            return JSONResponse({"error": "Run not found"}, status_code=404)
        return JSONResponse(run)

    # ── Automations Engine ────────────────────────────────────

    @app.get("/api/automations/dashboard", tags=["automations"])
    async def automations_dashboard():
        """Dashboard de todas as automacoes."""
        from ..automations import get_automations_engine
        engine = get_automations_engine()
        return JSONResponse(engine.dashboard())

    @app.post("/api/automations/{name}/trigger", tags=["automations"])
    async def trigger_automation(name: str, request: Request):
        """Aciona uma automacao via webhook."""
        from ..automations import get_automations_engine
        engine = get_automations_engine()
        try:
            body = await request.json()
        except Exception:
            body = {}
        result = engine.trigger(name, body)
        return JSONResponse(result)

    @app.get("/api/automations/logs", tags=["automations"])
    async def automations_logs(name: str | None = None, limit: int = 50):
        from ..automations import get_automations_engine
        engine = get_automations_engine()
        return JSONResponse({"logs": engine.get_logs(name, limit)})

    # ── Spectator (Live Pair Programming) ─────────────────────

    @app.get("/api/spectator/{session_id}", tags=["spectator"])
    async def spectator_sse(session_id: str, token: str | None = None):
        """Stream SSE com eventos em tempo real da sessao."""
        from ..spectator import get_spectator, get_spectator_by_token, format_sse, create_spectator
        from .. import config

        if not config.CLOW_SPECTATOR:
            return JSONResponse({"error": "Spectator disabled"}, status_code=403)

        # Busca por session_id ou por token
        spectator = get_spectator(session_id)
        if not spectator and token:
            spectator = get_spectator_by_token(token)
        if not spectator:
            spectator = create_spectator(session_id)

        subscriber_queue = spectator.subscribe()

        def event_stream():
            # Envia evento inicial de conexao
            yield format_sse({
                "type": "connected",
                "timestamp": time.time(),
                "data": spectator.to_dict(),
            })

            try:
                while True:
                    try:
                        event = subscriber_queue.get(timeout=30)
                        yield format_sse(event)
                    except Exception:
                        # Heartbeat para manter conexao viva
                        yield f"event: heartbeat\ndata: {{}}\n\n"
            finally:
                spectator.unsubscribe(subscriber_queue)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/spectator/{session_id}/approve", tags=["spectator"])
    async def spectator_approve(session_id: str, request: Request):
        """Resolve pedido de aprovacao via spectator."""
        from ..spectator import get_spectator

        spectator = get_spectator(session_id)
        if not spectator:
            return JSONResponse({"error": "Session not found"}, status_code=404)

        body = await request.json()
        approval_id = body.get("approval_id", "")
        approved = body.get("approved", False)

        success = spectator.resolve_approval(approval_id, approved)
        return JSONResponse({"success": success})

    @app.get("/api/spectator", tags=["spectator"])
    async def list_spectators_endpoint():
        """Lista sessoes com spectator ativo."""
        from ..spectator import list_spectators
        return JSONResponse({"sessions": list_spectators()})

    @app.get("/spectator/{session_id}", tags=["spectator"])
    async def spectator_page(session_id: str):
        """Pagina HTML do spectator com split-screen."""
        from fastapi.responses import HTMLResponse
        html = _spectator_html(session_id)
        return HTMLResponse(html)


def _spectator_html(session_id: str) -> str:
    """Gera pagina HTML do spectator com terminal + diff view."""
    return f"""<!DOCTYPE html>
<html lang="pt-br">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Clow Spectator — {session_id[:8]}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: 'JetBrains Mono', 'Fira Code', monospace; background: #0d1117; color: #c9d1d9; height: 100vh; }}
.header {{ background: #161b22; padding: 12px 20px; border-bottom: 1px solid #30363d; display: flex; justify-content: space-between; align-items: center; }}
.header h1 {{ font-size: 16px; color: #7C5CFC; }}
.status {{ font-size: 12px; color: #3fb950; }}
.container {{ display: flex; height: calc(100vh - 48px); }}
.panel {{ flex: 1; overflow-y: auto; padding: 16px; border-right: 1px solid #30363d; }}
.panel:last-child {{ border-right: none; }}
.panel-title {{ font-size: 13px; color: #8b949e; margin-bottom: 12px; text-transform: uppercase; letter-spacing: 1px; }}
.event {{ margin-bottom: 8px; padding: 8px 12px; border-radius: 6px; font-size: 13px; line-height: 1.5; }}
.event-tool_call {{ background: #1c2333; border-left: 3px solid #7C5CFC; }}
.event-tool_result {{ background: #1c2333; border-left: 3px solid #3fb950; }}
.event-text_delta {{ color: #e6edf3; }}
.event-error {{ background: #2d1b1b; border-left: 3px solid #f85149; }}
.event-file_diff {{ background: #1c2333; border-left: 3px solid #f0883e; }}
.event-approval_request {{ background: #2d2300; border-left: 3px solid #d29922; padding: 12px; }}
.approve-btn {{ background: #238636; color: white; border: none; padding: 6px 16px; border-radius: 4px; cursor: pointer; margin-right: 8px; }}
.deny-btn {{ background: #da3633; color: white; border: none; padding: 6px 16px; border-radius: 4px; cursor: pointer; }}
.diff-add {{ color: #3fb950; }}
.diff-del {{ color: #f85149; }}
.tool-name {{ color: #7C5CFC; font-weight: bold; }}
.tool-status {{ color: #3fb950; }}
.subscribers {{ font-size: 12px; color: #8b949e; }}
pre {{ white-space: pre-wrap; word-break: break-all; }}
</style>
</head>
<body>
<div class="header">
  <h1>Clow Spectator</h1>
  <div>
    <span class="status" id="status">Conectando...</span>
    <span class="subscribers" id="subs"></span>
  </div>
</div>
<div class="container">
  <div class="panel" id="terminal">
    <div class="panel-title">Terminal ao Vivo</div>
  </div>
  <div class="panel" id="diffs">
    <div class="panel-title">Diffs de Arquivos</div>
  </div>
</div>
<script>
const sessionId = "{session_id}";
const terminal = document.getElementById("terminal");
const diffs = document.getElementById("diffs");
const status = document.getElementById("status");
const subs = document.getElementById("subs");
let textBuffer = "";

const es = new EventSource("/api/spectator/" + sessionId);

es.addEventListener("connected", (e) => {{
  status.textContent = "Conectado";
  status.style.color = "#3fb950";
  const d = JSON.parse(e.data);
  if (d.data) subs.textContent = d.data.subscribers + " assistindo";
}});

es.addEventListener("text_delta", (e) => {{
  const d = JSON.parse(e.data);
  textBuffer += d.data.text;
  let el = terminal.querySelector(".current-text");
  if (!el) {{
    el = document.createElement("div");
    el.className = "event event-text_delta current-text";
    terminal.appendChild(el);
  }}
  el.textContent = textBuffer;
  terminal.scrollTop = terminal.scrollHeight;
}});

es.addEventListener("text_done", (e) => {{
  textBuffer = "";
  const el = terminal.querySelector(".current-text");
  if (el) el.classList.remove("current-text");
}});

es.addEventListener("tool_call", (e) => {{
  const d = JSON.parse(e.data).data;
  const el = document.createElement("div");
  el.className = "event event-tool_call";
  el.innerHTML = '<span class="tool-name">' + d.name + '</span> ' + JSON.stringify(d.arguments).substring(0, 200);
  terminal.appendChild(el);
  terminal.scrollTop = terminal.scrollHeight;
}});

es.addEventListener("tool_result", (e) => {{
  const d = JSON.parse(e.data).data;
  const el = document.createElement("div");
  el.className = "event event-tool_result";
  el.innerHTML = '<span class="tool-name">' + d.name + '</span> <span class="tool-status">[' + d.status + ']</span><pre>' + (d.output || '').substring(0, 500) + '</pre>';
  terminal.appendChild(el);
  terminal.scrollTop = terminal.scrollHeight;
}});

es.addEventListener("file_diff", (e) => {{
  const d = JSON.parse(e.data).data;
  const el = document.createElement("div");
  el.className = "event event-file_diff";
  el.innerHTML = '<strong>' + d.file + '</strong><pre class="diff-del">- ' + (d.before || '').substring(0, 500) + '</pre><pre class="diff-add">+ ' + (d.after || '').substring(0, 500) + '</pre>';
  diffs.appendChild(el);
  diffs.scrollTop = diffs.scrollHeight;
}});

es.addEventListener("approval_request", (e) => {{
  const d = JSON.parse(e.data).data;
  const el = document.createElement("div");
  el.className = "event event-approval_request";
  el.innerHTML = '<p>' + d.prompt + '</p><button class="approve-btn" onclick="approve(\\'' + d.approval_id + '\\', true)">Aprovar</button><button class="deny-btn" onclick="approve(\\'' + d.approval_id + '\\', false)">Negar</button>';
  terminal.appendChild(el);
}});

es.addEventListener("heartbeat", () => {{}});
es.onerror = () => {{ status.textContent = "Desconectado"; status.style.color = "#f85149"; }};

function approve(id, approved) {{
  fetch("/api/spectator/" + sessionId + "/approve", {{
    method: "POST",
    headers: {{"Content-Type": "application/json"}},
    body: JSON.stringify({{approval_id: id, approved: approved}})
  }});
}}
</script>
</body>
</html>"""
