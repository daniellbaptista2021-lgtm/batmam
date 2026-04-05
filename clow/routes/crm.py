"""CRM routes — Chatwoot integration (contacts, conversations, pipeline, dashboard)."""

from __future__ import annotations
from pathlib import Path

from fastapi import Request as _Req
from fastapi.responses import JSONResponse as _JR, HTMLResponse as _HR, RedirectResponse

_TPL_DIR = Path(__file__).resolve().parent.parent / "templates"


def register_crm_routes(app) -> None:

    from .auth import _get_user_session

    # ── helpers ────────────────────────────────────────────────

    def _auth(request: _Req):
        """Return session or None."""
        return _get_user_session(request)

    def _tenant(sess: dict) -> str:
        return sess["user_id"]

    def _client_or_error(tenant_id: str):
        from ..chatwoot import get_crm_client
        client = get_crm_client(tenant_id)
        if client is None:
            return None, _JR(
                {"error": "CRM nao configurado. Configure a integracao com o Chatwoot primeiro."},
                status_code=400,
            )
        return client, None

    # ── Page ──────────────────────────────────────────────────

    @app.get("/app/crm", tags=["crm"])
    async def crm_page(request: _Req):
        sess = _auth(request)
        if not sess:
            return RedirectResponse("/login", status_code=302)
        tpl = _TPL_DIR / "crm.html"
        if tpl.exists():
            return _HR(tpl.read_text(encoding="utf-8"))
        return _HR("<h1>CRM template not found</h1>")

    # ── Setup / Config ────────────────────────────────────────

    @app.get("/api/v1/crm/config", tags=["crm"])
    async def crm_get_config(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        try:
            from ..chatwoot import get_crm_config
            cfg = get_crm_config(_tenant(sess))
            return _JR({
                "chatwoot_url": cfg.chatwoot_url if cfg else "",
                "api_token": cfg.api_token if cfg else "",
                "account_id": cfg.account_id if cfg else "",
                "configured": cfg is not None and bool(cfg.api_token),
            })
        except Exception as exc:
            return _JR({"error": f"Erro ao buscar configuracao: {exc}"}, status_code=500)

    @app.post("/api/v1/crm/config", tags=["crm"])
    async def crm_save_config(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        try:
            body = await request.json()
            chatwoot_url = body.get("chatwoot_url", "").strip()
            api_token = body.get("api_token", "").strip()
            account_id = body.get("account_id", "").strip()

            if not chatwoot_url or not api_token or not account_id:
                return _JR({"error": "Todos os campos sao obrigatorios (chatwoot_url, api_token, account_id)"}, status_code=400)

            from ..chatwoot import save_crm_config
            result = save_crm_config(_tenant(sess), chatwoot_url, api_token, account_id)
            return _JR(result)
        except Exception as exc:
            return _JR({"error": f"Erro ao salvar configuracao: {exc}"}, status_code=500)

    @app.post("/api/v1/crm/test", tags=["crm"])
    async def crm_test_connection(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        client, err = _client_or_error(_tenant(sess))
        if err:
            return err
        try:
            result = client.test_connection()
            return _JR({"ok": True, "data": result})
        except Exception as exc:
            return _JR({"error": f"Falha na conexao com o Chatwoot: {exc}"}, status_code=502)

    # ── Contacts ──────────────────────────────────────────────

    @app.get("/api/v1/crm/contacts", tags=["crm"])
    async def crm_list_contacts(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        client, err = _client_or_error(_tenant(sess))
        if err:
            return err
        try:
            page = int(request.query_params.get("page", "1"))
            q = request.query_params.get("q", "")
            data = client.list_contacts(page=page, q=q)
            return _JR(data)
        except Exception as exc:
            return _JR({"error": f"Erro ao listar contatos: {exc}"}, status_code=500)

    @app.post("/api/v1/crm/contacts", tags=["crm"])
    async def crm_create_contact(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        client, err = _client_or_error(_tenant(sess))
        if err:
            return err
        try:
            body = await request.json()
            data = client.create_contact(body)
            return _JR(data)
        except Exception as exc:
            return _JR({"error": f"Erro ao criar contato: {exc}"}, status_code=500)

    @app.put("/api/v1/crm/contacts/{contact_id}", tags=["crm"])
    async def crm_update_contact(contact_id: int, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        client, err = _client_or_error(_tenant(sess))
        if err:
            return err
        try:
            body = await request.json()
            data = client.update_contact(contact_id, body)
            return _JR(data)
        except Exception as exc:
            return _JR({"error": f"Erro ao atualizar contato: {exc}"}, status_code=500)

    @app.delete("/api/v1/crm/contacts/{contact_id}", tags=["crm"])
    async def crm_delete_contact(contact_id: int, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        client, err = _client_or_error(_tenant(sess))
        if err:
            return err
        try:
            data = client.delete_contact(contact_id)
            return _JR(data)
        except Exception as exc:
            return _JR({"error": f"Erro ao excluir contato: {exc}"}, status_code=500)

    # ── Conversations ─────────────────────────────────────────

    @app.get("/api/v1/crm/conversations", tags=["crm"])
    async def crm_list_conversations(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        client, err = _client_or_error(_tenant(sess))
        if err:
            return err
        try:
            status = request.query_params.get("status", "open")
            page = int(request.query_params.get("page", "1"))
            data = client.list_conversations(status=status, page=page)
            return _JR(data)
        except Exception as exc:
            return _JR({"error": f"Erro ao listar conversas: {exc}"}, status_code=500)

    @app.get("/api/v1/crm/conversations/{conv_id}", tags=["crm"])
    async def crm_get_conversation(conv_id: int, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        client, err = _client_or_error(_tenant(sess))
        if err:
            return err
        try:
            data = client.get_conversation(conv_id)
            return _JR(data)
        except Exception as exc:
            return _JR({"error": f"Erro ao buscar conversa: {exc}"}, status_code=500)

    @app.get("/api/v1/crm/conversations/{conv_id}/messages", tags=["crm"])
    async def crm_get_messages(conv_id: int, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        client, err = _client_or_error(_tenant(sess))
        if err:
            return err
        try:
            data = client.get_messages(conv_id)
            return _JR(data)
        except Exception as exc:
            return _JR({"error": f"Erro ao buscar mensagens: {exc}"}, status_code=500)

    @app.post("/api/v1/crm/conversations/{conv_id}/messages", tags=["crm"])
    async def crm_send_message(conv_id: int, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        client, err = _client_or_error(_tenant(sess))
        if err:
            return err
        try:
            body = await request.json()
            content = body.get("content", "").strip()
            if not content:
                return _JR({"error": "Conteudo da mensagem e obrigatorio"}, status_code=400)
            data = client.send_message(conv_id, content)
            return _JR(data)
        except Exception as exc:
            return _JR({"error": f"Erro ao enviar mensagem: {exc}"}, status_code=500)

    @app.post("/api/v1/crm/conversations/{conv_id}/status", tags=["crm"])
    async def crm_toggle_status(conv_id: int, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        client, err = _client_or_error(_tenant(sess))
        if err:
            return err
        try:
            body = await request.json()
            status = body.get("status", "")
            if status not in ("open", "resolved", "pending"):
                return _JR({"error": "Status invalido. Use: open, resolved ou pending"}, status_code=400)
            data = client.toggle_status(conv_id, status)
            return _JR(data)
        except Exception as exc:
            return _JR({"error": f"Erro ao alterar status da conversa: {exc}"}, status_code=500)

    # ── Pipeline (Labels) ─────────────────────────────────────

    @app.get("/api/v1/crm/labels", tags=["crm"])
    async def crm_list_labels(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        client, err = _client_or_error(_tenant(sess))
        if err:
            return err
        try:
            data = client.list_labels()
            return _JR(data)
        except Exception as exc:
            return _JR({"error": f"Erro ao listar labels: {exc}"}, status_code=500)

    @app.post("/api/v1/crm/labels", tags=["crm"])
    async def crm_create_label(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        client, err = _client_or_error(_tenant(sess))
        if err:
            return err
        try:
            body = await request.json()
            data = client.create_label(body)
            return _JR(data)
        except Exception as exc:
            return _JR({"error": f"Erro ao criar label: {exc}"}, status_code=500)

    @app.post("/api/v1/crm/conversations/{conv_id}/labels", tags=["crm"])
    async def crm_add_labels(conv_id: int, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        client, err = _client_or_error(_tenant(sess))
        if err:
            return err
        try:
            body = await request.json()
            labels = body.get("labels", [])
            if not labels:
                return _JR({"error": "Lista de labels e obrigatoria"}, status_code=400)
            data = client.add_label_to_conversation(conv_id, labels)
            return _JR(data)
        except Exception as exc:
            return _JR({"error": f"Erro ao adicionar labels a conversa: {exc}"}, status_code=500)

    @app.get("/api/v1/crm/conversations/{conv_id}/labels", tags=["crm"])
    async def crm_get_conv_labels(conv_id: int, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        client, err = _client_or_error(_tenant(sess))
        if err:
            return err
        try:
            data = client.get_conversation_labels(conv_id)
            return _JR(data)
        except Exception as exc:
            return _JR({"error": f"Erro ao buscar labels da conversa: {exc}"}, status_code=500)

    # ── Dashboard ─────────────────────────────────────────────

    @app.get("/api/v1/crm/dashboard", tags=["crm"])
    async def crm_dashboard(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        client, err = _client_or_error(_tenant(sess))
        if err:
            return err
        try:
            counts = client.get_conversation_counts()
            summary = client.get_account_summary()
            return _JR({"counts": counts, "summary": summary})
        except Exception as exc:
            return _JR({"error": f"Erro ao carregar dashboard: {exc}"}, status_code=500)

    # ── Inboxes ───────────────────────────────────────────────

    @app.get("/api/v1/crm/inboxes", tags=["crm"])
    async def crm_list_inboxes(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        client, err = _client_or_error(_tenant(sess))
        if err:
            return err
        try:
            data = client.list_inboxes()
            return _JR(data)
        except Exception as exc:
            return _JR({"error": f"Erro ao listar inboxes: {exc}"}, status_code=500)
