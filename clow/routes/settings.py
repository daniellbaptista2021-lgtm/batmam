"""Settings routes — painel do cliente estilo Claude.ai."""

from __future__ import annotations
import time
from pathlib import Path

from fastapi import Request as _Req
from fastapi.responses import JSONResponse as _JR, HTMLResponse as _HR, RedirectResponse


def register_settings_routes(app) -> None:

    from .auth import _get_user_session

    # ── Analytics ──────────────────────────────────────────────

    @app.post("/api/v1/analytics/pageview", tags=["analytics"], include_in_schema=False)
    async def track_pageview(request: _Req):
        try:
            body = await request.json()
            from ..logging import log_action
            page = body.get("page", "/")
            ref = body.get("ref", "")
            ip = request.client.host if request.client else ""
            log_action("pageview", f"page={page} ref={ref[:50]} ip={ip}")
        except Exception:
            pass
        return _JR({"ok": True})

    # ── Legal Pages ────────────────────────────────────────────

    @app.get("/termos", tags=["legal"])
    async def termos_page():
        tpl = Path(__file__).parent.parent / "templates" / "termos.html"
        return _HR(tpl.read_text(encoding="utf-8")) if tpl.exists() else _HR("<h1>Termos</h1>")

    @app.get("/privacidade", tags=["legal"])
    async def privacidade_page():
        tpl = Path(__file__).parent.parent / "templates" / "privacidade.html"
        return _HR(tpl.read_text(encoding="utf-8")) if tpl.exists() else _HR("<h1>Privacidade</h1>")

    # ── Settings Page ─────────────────────────────────────────

    @app.get("/app/settings", tags=["settings"])
    async def settings_page(request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return RedirectResponse("/login", status_code=302)
        tpl = Path(__file__).parent.parent / "templates" / "settings.html"
        if tpl.exists():
            return _HR(tpl.read_text(encoding="utf-8"))
        return _HR("<h1>Settings template not found</h1>")

    # ── Profile ───────────────────────────────────────────────

    @app.get("/api/v1/user/profile", tags=["settings"])
    async def get_profile(request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..database import get_user_by_id
        user = get_user_by_id(sess["user_id"])
        if not user:
            return _JR({"error": "User nao encontrado"}, status_code=404)
        return _JR({
            "id": user["id"],
            "name": user.get("name", ""),
            "email": user["email"],
            "plan": user.get("plan", "lite"),
            "created_at": user.get("created_at", 0),
            "is_admin": bool(user.get("is_admin")),
            "byok_enabled": bool(user.get("byok_enabled")),
            "accepted_terms_at": user.get("accepted_terms_at", 0),
        })

    @app.put("/api/v1/user/profile", tags=["settings"])
    async def update_profile(request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        from ..database import get_db
        name = body.get("name", "").strip()
        if name:
            with get_db() as db:
                db.execute("UPDATE users SET name=? WHERE id=?", (name, sess["user_id"]))
        return _JR({"success": True})

    # ── Usage ─────────────────────────────────────────────────

    @app.get("/api/v1/user/usage", tags=["settings"])
    async def get_usage(request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)

        from ..database import get_db, get_user_by_id
        from ..billing import get_plan

        user = get_user_by_id(sess["user_id"])
        plan_id = user.get("plan", "lite") if user else "byok_free"
        is_admin = bool(user.get("is_admin")) if user else False
        if plan_id in ("free", "basic", "byok_free"):
            plan_id = "lite"
        elif plan_id == "unlimited":
            plan_id = "business" if is_admin else "byok_free"
        plan = get_plan(plan_id)
        uid = sess["user_id"]
        now = time.time()
        today_start = now - (now % 86400)
        week_start = now - 7 * 86400

        with get_db() as db:
            today = db.execute(
                "SELECT COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0), COUNT(*) FROM usage_log WHERE user_id=? AND created_at>=?",
                (uid, today_start),
            ).fetchone()
            week = db.execute(
                "SELECT COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0), COUNT(*) FROM usage_log WHERE user_id=? AND created_at>=?",
                (uid, week_start),
            ).fetchone()

        return _JR({
            "plan_id": plan_id,
            "plan_name": plan["name"],
            "model": plan["model"],
            "today": {"input": today[0], "output": today[1], "requests": today[2]},
            "week": {"input": week[0], "output": week[1]},
            "limits": {
                "daily_input": plan["daily_input_tokens"],
                "daily_output": plan["daily_output_tokens"],
                "weekly_input": plan["weekly_input_tokens"],
                "weekly_output": plan["weekly_output_tokens"],
            },
            "renews_in_hours": int((today_start + 86400 - now) / 3600),
        })

    @app.get("/api/v1/user/usage/history", tags=["settings"])
    async def get_usage_history(request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..database import get_db
        with get_db() as db:
            rows = db.execute(
                "SELECT date(created_at,'unixepoch') as day, SUM(input_tokens) as inp, SUM(output_tokens) as out, COUNT(*) as reqs "
                "FROM usage_log WHERE user_id=? AND created_at>=? GROUP BY day ORDER BY day DESC LIMIT 7",
                (sess["user_id"], time.time() - 7 * 86400),
            ).fetchall()
        return _JR({"days": [{"date": r[0], "input": r[1] or 0, "output": r[2] or 0, "requests": r[3]} for r in rows]})

    # ── Preferences ───────────────────────────────────────────

    @app.get("/api/v1/user/preferences", tags=["settings"])
    async def get_preferences(request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..database import get_db
        with get_db() as db:
            try:
                db.execute("ALTER TABLE users ADD COLUMN preferences TEXT DEFAULT '{}'")
            except Exception:
                pass
            row = db.execute("SELECT preferences FROM users WHERE id=?", (sess["user_id"],)).fetchone()
        import json
        prefs = json.loads(row[0] or "{}") if row else {}
        return _JR({
            "dark_mode": prefs.get("dark_mode", True),
            "notifications": prefs.get("notifications", True),
            "extended_thinking": prefs.get("extended_thinking", True),
            "language": prefs.get("language", "pt-BR"),
            "agent_type": prefs.get("agent_type", "general"),
            "custom_instructions": prefs.get("custom_instructions", ""),
        })

    @app.put("/api/v1/user/preferences", tags=["settings"])
    async def update_preferences(request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        import json
        from ..database import get_db
        with get_db() as db:
            try:
                db.execute("ALTER TABLE users ADD COLUMN preferences TEXT DEFAULT '{}'")
            except Exception:
                pass
            db.execute("UPDATE users SET preferences=? WHERE id=?", (json.dumps(body), sess["user_id"]))
        return _JR({"success": True})

    # ── API Key ───────────────────────────────────────────────

    @app.put("/api/v1/user/apikey", tags=["settings"])
    async def update_apikey(request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        key = body.get("api_key", "").strip()
        from ..database import set_user_api_key
        set_user_api_key(sess["user_id"], key)
        return _JR({"success": True, "valid": True})

    # ── Invoices ──────────────────────────────────────────────

    @app.get("/api/v1/user/invoices", tags=["settings"])
    async def get_invoices(request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..database import get_user_by_id
        user = get_user_by_id(sess["user_id"])
        cid = user.get("stripe_customer_id", "") if user else ""
        if not cid:
            return _JR({"invoices": []})
        try:
            import stripe
            stripe.api_key = __import__("clow.config", fromlist=["STRIPE_SECRET_KEY"]).STRIPE_SECRET_KEY
            invoices = stripe.Invoice.list(customer=cid, limit=20)
            return _JR({"invoices": [
                {"id": i.id, "date": i.created, "amount": i.amount_paid / 100, "currency": i.currency, "status": i.status, "pdf": i.invoice_pdf}
                for i in invoices.data
            ]})
        except Exception:
            return _JR({"invoices": []})

    # ── Workflows ─────────────────────────────────────────────

    @app.get("/api/v1/user/workflows", tags=["settings"])
    async def get_workflows(request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..database import get_user_by_id
        from ..billing import get_plan
        user = get_user_by_id(sess["user_id"])
        plan_id = user.get("plan", "lite") if user else "byok_free"
        plan = get_plan(plan_id)
        flows_count = plan.get("n8n_flows", 0)

        base_flows = [
            {"id": "agente-orquestrador", "name": "Agente Orquestrador", "desc": "Orquestra multiplos agentes para tarefas complexas", "category": "automacao", "file": "agente-orquestrador.json"},
            {"id": "atendimento-geral", "name": "Atendimento Geral", "desc": "Chatbot completo com RAG e handoff humano", "category": "suporte", "file": "atendimento-geral.json"},
            {"id": "atendimento-instagram", "name": "Atendimento Instagram", "desc": "Agente de atendimento via DM do Instagram", "category": "suporte", "file": "atendimento-instagram.json"},
            {"id": "sdr-rag-followup", "name": "SDR + RAG + Follow Up", "desc": "Qualificacao, agendamento e follow-up automatico", "category": "vendas", "file": "sdr-rag-followup.json"},
            {"id": "reunioes-mentorias", "name": "Reunioes e Mentorias", "desc": "Criacao automatica de reunioes e mentorias", "category": "produtividade", "file": "reunioes-mentorias.json"},
            {"id": "conteudo-redes-sociais", "name": "Conteudo + Redes Sociais", "desc": "Criacao e publicacao automatica em todas as redes", "category": "marketing", "file": "conteudo-redes-sociais.json"},
            {"id": "super-rag", "name": "Super RAG", "desc": "Busca inteligente em documentos com IA avancada", "category": "dados", "file": "super-rag.json"},
            {"id": "disparo-massa", "name": "Disparo em Massa", "desc": "Workflow de disparo em massa via WhatsApp", "category": "vendas", "file": "disparo-massa.json"},
        ]

        # Adiciona URL de download
        for f in base_flows:
            f["download_url"] = f"/static/workflows/principais/{f['file']}"

        return _JR({
            "plan_id": plan_id,
            "flows_included": flows_count,
            "base_flows": base_flows if flows_count >= 8 else [],
            "has_library": flows_count >= 2000,
            "library_count": flows_count,
            "library_url": "https://drive.google.com/drive/folders/1w2_aZ3UONCyQ10LXG8T6PRvjz4AlDutH" if flows_count >= 2000 else "",
        })
