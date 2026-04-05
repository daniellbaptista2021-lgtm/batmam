"""Infra Setup Routes — wizard de instalacao guiada."""

from __future__ import annotations
from pathlib import Path

from fastapi import Request as _Req
from fastapi.responses import JSONResponse as _JR, HTMLResponse as _HR, Response, RedirectResponse

_TPL_DIR = Path(__file__).resolve().parent.parent / "templates"


def register_infra_setup_routes(app) -> None:

    from .auth import _get_user_session

    def _auth(request: _Req):
        return _get_user_session(request)

    def _tenant(sess: dict) -> str:
        return sess["user_id"]

    # ── Pagina do wizard ──

    @app.get("/setup", tags=["setup"])
    async def setup_page(request: _Req):
        sess = _auth(request)
        if not sess:
            return RedirectResponse("/login")
        tpl = _TPL_DIR / "setup.html"
        if tpl.exists():
            return _HR(tpl.read_text(encoding="utf-8"))
        return _HR("<h1>Setup em construcao</h1>")

    # ── Gerar script ──

    @app.post("/api/v1/setup/generate", tags=["setup"])
    async def setup_generate(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        setup_type = body.get("type", "vps")
        email = body.get("email", "").strip()
        password = body.get("password", "").strip()
        if not email or not password:
            return _JR({"error": "Email e senha obrigatorios"}, status_code=400)
        if len(password) < 8:
            return _JR({"error": "Senha minimo 8 caracteres"}, status_code=400)

        from ..infra_setup import generate_setup_token
        cfg = {
            "type": setup_type,
            "domain": body.get("domain", ""),
            "subdomain": body.get("subdomain", "chat"),
            "email": email,
            "password": password,
            "port": int(body.get("port", 3000)),
            "zapi_instance_id": body.get("zapi_instance_id", ""),
            "zapi_token": body.get("zapi_token", ""),
        }
        token = generate_setup_token(_tenant(sess), cfg)
        return _JR({
            "setup_token": token,
            "script_url": f"/api/v1/setup/script/{token}",
            "curl_command": f"curl -sSL https://clow.pvcorretor01.com.br/api/v1/setup/script/{token} | sudo bash",
        })

    # ── Servir script (publico, acessado pelo curl do cliente) ──

    @app.get("/api/v1/setup/script/{token}", tags=["setup"])
    async def setup_script(token: str):
        from ..infra_setup import get_setup_data, mark_token_used
        from ..infra_setup import generate_vps_script, generate_local_script
        data = get_setup_data(token)
        if not data:
            return Response(
                content="# ERRO: Token invalido, expirado ou ja utilizado.\n# Gere um novo no Clow.\nexit 1\n",
                media_type="text/plain", status_code=404,
            )
        cfg = data.get("config", {})
        if cfg.get("type") == "local":
            script = generate_local_script(cfg)
        else:
            script = generate_vps_script(cfg)
        mark_token_used(token)
        return Response(content=script, media_type="text/plain")

    # ── Download do script como arquivo ──

    @app.get("/api/v1/setup/script/{token}/download", tags=["setup"])
    async def setup_script_download(token: str):
        from ..infra_setup import get_setup_data, mark_token_used
        from ..infra_setup import generate_vps_script, generate_local_script
        data = get_setup_data(token)
        if not data:
            return _JR({"error": "Token invalido ou expirado"}, status_code=404)
        cfg = data.get("config", {})
        script = generate_local_script(cfg) if cfg.get("type") == "local" else generate_vps_script(cfg)
        mark_token_used(token)
        return Response(
            content=script, media_type="application/x-sh",
            headers={"Content-Disposition": "attachment; filename=setup-clow.sh"},
        )

    # ── Testar conexao ──

    @app.post("/api/v1/setup/test-connection", tags=["setup"])
    async def setup_test(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        code = body.get("connection_code", "").strip()
        if not code:
            return _JR({"error": "Codigo de conexao obrigatorio"}, status_code=400)
        from ..infra_setup import decode_connection_code, test_chatwoot_connection
        decoded = decode_connection_code(code)
        if not decoded:
            return _JR({"error": "Codigo invalido. Deve comecar com clow_conn_"}, status_code=400)
        result = test_chatwoot_connection(decoded["chatwoot_url"], decoded["api_token"])
        return _JR(result)

    # ── Salvar conexao ──

    @app.post("/api/v1/setup/connect", tags=["setup"])
    async def setup_connect(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        code = body.get("connection_code", "").strip()
        from ..infra_setup import decode_connection_code, test_chatwoot_connection, save_tenant_infra
        decoded = decode_connection_code(code)
        if not decoded:
            return _JR({"error": "Codigo invalido"}, status_code=400)
        result = test_chatwoot_connection(decoded["chatwoot_url"], decoded["api_token"])
        if not result.get("ok"):
            return _JR({"error": f"Nao foi possivel conectar: {result.get('error', '')}"}, status_code=400)
        tid = _tenant(sess)
        save_tenant_infra(tid, decoded["chatwoot_url"], decoded["api_token"])

        # Auto-sync: importa inboxes e contatos do Chatwoot
        sync_result = {}
        try:
            from ..chatwoot_sync import full_sync
            sync_result = full_sync(tid)
        except Exception:
            pass

        return _JR({
            "connected": True,
            "chatwoot_url": decoded["chatwoot_url"],
            "sync": sync_result,
        })

    # ── Status da infra ──

    @app.get("/api/v1/setup/status", tags=["setup"])
    async def setup_status(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..infra_setup import get_infra_status
        return _JR(get_infra_status(_tenant(sess)))

    # ── Monitor de saude ──

    @app.get("/api/v1/infra/health", tags=["infra"])
    async def infra_health(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..infra_monitor import check_health
        return _JR(check_health(_tenant(sess)))

    @app.get("/api/v1/infra/health/history", tags=["infra"])
    async def infra_health_history(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..infra_monitor import get_health_history
        limit = int(request.query_params.get("limit", "50"))
        return _JR({"history": get_health_history(_tenant(sess), limit)})

    @app.get("/api/v1/infra/health/uptime", tags=["infra"])
    async def infra_uptime(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..infra_monitor import get_uptime
        days = int(request.query_params.get("days", "30"))
        return _JR({"uptime_percent": get_uptime(_tenant(sess), days), "days": days})

    @app.put("/api/v1/infra/health/config", tags=["infra"])
    async def infra_health_config(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        from ..infra_monitor import save_monitor_config
        save_monitor_config(_tenant(sess), body)
        return _JR({"success": True})

    # ── Chatwoot Sync ──

    @app.post("/api/v1/infra/sync", tags=["infra"])
    async def infra_sync(request: _Req):
        """Sincroniza Chatwoot → CRM (inboxes, contatos, conversas)."""
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..chatwoot_sync import full_sync
        result = full_sync(_tenant(sess))
        if "error" in result:
            return _JR(result, status_code=400)
        return _JR(result)

    @app.get("/api/v1/infra/inboxes", tags=["infra"])
    async def infra_inboxes(request: _Req):
        """Lista inboxes WhatsApp do Chatwoot do cliente."""
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..chatwoot_sync import get_sync_client
        client = get_sync_client(_tenant(sess))
        if not client:
            return _JR({"error": "Chatwoot nao configurado", "inboxes": []})
        inboxes = client.get_whatsapp_inboxes()
        return _JR({"inboxes": [
            {"id": i["id"], "name": i["name"], "channel_type": i.get("channel_type", "")}
            for i in inboxes
        ]})

    @app.post("/api/v1/infra/send-via-chatwoot", tags=["infra"])
    async def infra_send_chatwoot(request: _Req):
        """Envia mensagem via Chatwoot (para instancias que usam Chatwoot como bridge)."""
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        conv_id = body.get("conversation_id")
        content = body.get("content", "")
        if not conv_id or not content:
            return _JR({"error": "conversation_id e content obrigatorios"}, status_code=400)
        from ..chatwoot_sync import get_sync_client
        client = get_sync_client(_tenant(sess))
        if not client:
            return _JR({"error": "Chatwoot nao configurado"}, status_code=400)
        result = client.send_message(conv_id, content)
        return _JR(result)
