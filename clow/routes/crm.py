"""CRM Routes — leads, campanhas, agendamentos, dashboard, webhook.

Todos os endpoints filtram por tenant_id do usuario logado.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import Request as _Req
from fastapi.responses import JSONResponse as _JR, HTMLResponse as _HR, RedirectResponse

_TPL_DIR = Path(__file__).resolve().parent.parent / "templates"


def register_crm_routes(app) -> None:

    from .auth import _get_user_session

    def _auth(request: _Req):
        return _get_user_session(request)

    def _tenant(sess: dict) -> str:
        return sess["user_id"]

    # Inicializa tabelas CRM no startup
    from ..crm_models import init_crm_tables
    try:
        init_crm_tables()
    except Exception:
        pass

    # ══════════════════════════════════════════════════════════
    # PAGINAS HTML
    # ══════════════════════════════════════════════════════════

    @app.get("/crm", tags=["crm"])
    async def crm_dashboard_page(request: _Req):
        sess = _auth(request)
        if not sess:
            return RedirectResponse("/login")
        tpl = _TPL_DIR / "crm.html"
        if tpl.exists():
            return _HR(tpl.read_text(encoding="utf-8"))
        return _HR("<h1>CRM em construcao</h1>")

    # ══════════════════════════════════════════════════════════
    # LEADS
    # ══════════════════════════════════════════════════════════

    @app.get("/api/v1/crm/leads", tags=["crm"])
    async def crm_list_leads(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..crm_models import list_leads, search_leads
        tid = _tenant(sess)
        search = request.query_params.get("search", "")
        if search:
            leads = search_leads(tid, search)
            return _JR({"leads": leads, "total": len(leads), "page": 1, "pages": 1})
        status = request.query_params.get("status", "")
        source = request.query_params.get("source", "")
        page = int(request.query_params.get("page", "1"))
        limit = int(request.query_params.get("limit", "50"))
        return _JR(list_leads(tid, status=status, source=source, page=page, limit=limit))

    @app.post("/api/v1/crm/leads", tags=["crm"])
    async def crm_create_lead(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..crm_models import create_lead
        body = await request.json()
        lead = create_lead(
            tenant_id=_tenant(sess),
            name=body.get("name", ""),
            email=body.get("email", ""),
            phone=body.get("phone", ""),
            source=body.get("source", "manual"),
            notes=body.get("notes", ""),
            tags=body.get("tags"),
            custom_fields=body.get("custom_fields"),
        )
        return _JR(lead)

    @app.get("/api/v1/crm/leads/{lead_id}", tags=["crm"])
    async def crm_get_lead(lead_id: str, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..crm_models import get_lead, get_lead_timeline
        tid = _tenant(sess)
        lead = get_lead(lead_id, tid)
        if not lead:
            return _JR({"error": "Lead nao encontrado"}, status_code=404)
        lead["timeline"] = get_lead_timeline(lead_id, tid)
        return _JR(lead)

    @app.put("/api/v1/crm/leads/{lead_id}", tags=["crm"])
    async def crm_update_lead(lead_id: str, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..crm_models import update_lead
        body = await request.json()
        lead = update_lead(lead_id, _tenant(sess), **body)
        if not lead:
            return _JR({"error": "Lead nao encontrado"}, status_code=404)
        return _JR(lead)

    @app.delete("/api/v1/crm/leads/{lead_id}", tags=["crm"])
    async def crm_delete_lead(lead_id: str, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..crm_models import delete_lead
        ok = delete_lead(lead_id, _tenant(sess))
        if not ok:
            return _JR({"error": "Lead nao encontrado"}, status_code=404)
        return _JR({"success": True})

    @app.post("/api/v1/crm/leads/{lead_id}/activity", tags=["crm"])
    async def crm_add_activity(lead_id: str, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..crm_models import add_activity, get_lead
        tid = _tenant(sess)
        if not get_lead(lead_id, tid):
            return _JR({"error": "Lead nao encontrado"}, status_code=404)
        body = await request.json()
        act_type = body.get("type", "note")
        content = body.get("content", "")
        aid = add_activity(lead_id, tid, act_type, content, body.get("metadata"))
        return _JR({"success": True, "activity_id": aid})

    @app.put("/api/v1/crm/leads/{lead_id}/status", tags=["crm"])
    async def crm_change_status(lead_id: str, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..crm_models import change_lead_status
        body = await request.json()
        new_status = body.get("status", "")
        valid = {"novo", "contatado", "qualificado", "proposta", "ganho", "perdido"}
        if new_status not in valid:
            return _JR({"error": f"Status invalido. Use: {', '.join(sorted(valid))}"}, status_code=400)
        lead = change_lead_status(lead_id, _tenant(sess), new_status)
        if not lead:
            return _JR({"error": "Lead nao encontrado"}, status_code=404)
        return _JR(lead)

    # ══════════════════════════════════════════════════════════
    # EMAIL CAMPAIGNS
    # ══════════════════════════════════════════════════════════

    @app.get("/api/v1/crm/campaigns", tags=["crm"])
    async def crm_list_campaigns(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..crm_models import list_campaigns
        status = request.query_params.get("status", "")
        return _JR({"campaigns": list_campaigns(_tenant(sess), status)})

    @app.post("/api/v1/crm/campaigns", tags=["crm"])
    async def crm_create_campaign(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..crm_models import create_campaign
        body = await request.json()
        name = body.get("name", "").strip()
        subject = body.get("subject", "").strip()
        body_html = body.get("body_html", "").strip()
        if not name or not subject or not body_html:
            return _JR({"error": "Nome, assunto e corpo sao obrigatorios"}, status_code=400)
        campaign = create_campaign(_tenant(sess), name, subject, body_html,
                                   body.get("recipient_filter"))
        return _JR(campaign)

    @app.get("/api/v1/crm/campaigns/{cid}", tags=["crm"])
    async def crm_get_campaign(cid: str, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..crm_models import get_campaign, get_campaign_sends
        campaign = get_campaign(cid, _tenant(sess))
        if not campaign:
            return _JR({"error": "Campanha nao encontrada"}, status_code=404)
        campaign["sends"] = get_campaign_sends(cid)
        return _JR(campaign)

    @app.put("/api/v1/crm/campaigns/{cid}", tags=["crm"])
    async def crm_update_campaign(cid: str, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..crm_models import update_campaign
        body = await request.json()
        campaign = update_campaign(cid, _tenant(sess), **body)
        if not campaign:
            return _JR({"error": "Campanha nao encontrada ou ja enviada"}, status_code=400)
        return _JR(campaign)

    @app.post("/api/v1/crm/campaigns/{cid}/send", tags=["crm"])
    async def crm_send_campaign(cid: str, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..crm_models import get_campaign
        tid = _tenant(sess)
        campaign = get_campaign(cid, tid)
        if not campaign:
            return _JR({"error": "Campanha nao encontrada"}, status_code=404)
        if campaign["status"] not in ("draft", "scheduled"):
            return _JR({"error": "Campanha ja foi enviada"}, status_code=400)
        from ..integrations.email_sender import send_campaign
        send_campaign(cid, tid)
        return _JR({"success": True, "message": "Campanha sendo enviada em background"})

    @app.post("/api/v1/crm/campaigns/{cid}/schedule", tags=["crm"])
    async def crm_schedule_campaign(cid: str, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..crm_models import update_campaign_status
        body = await request.json()
        scheduled_at = body.get("scheduled_at")
        if not scheduled_at:
            return _JR({"error": "scheduled_at e obrigatorio"}, status_code=400)
        update_campaign_status(cid, _tenant(sess), "scheduled", scheduled_at=scheduled_at)
        return _JR({"success": True})

    @app.delete("/api/v1/crm/campaigns/{cid}", tags=["crm"])
    async def crm_delete_campaign(cid: str, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..crm_models import delete_campaign
        ok = delete_campaign(cid, _tenant(sess))
        if not ok:
            return _JR({"error": "Campanha nao encontrada"}, status_code=404)
        return _JR({"success": True})

    # ══════════════════════════════════════════════════════════
    # SCHEDULING LINKS
    # ══════════════════════════════════════════════════════════

    @app.get("/api/v1/crm/scheduling-links", tags=["crm"])
    async def crm_list_slinks(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..crm_models import list_scheduling_links
        return _JR({"links": list_scheduling_links(_tenant(sess))})

    @app.post("/api/v1/crm/scheduling-links", tags=["crm"])
    async def crm_create_slink(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..crm_models import create_scheduling_link
        body = await request.json()
        slug = body.get("slug", "").strip().lower().replace(" ", "-")
        title = body.get("title", "").strip()
        if not slug or not title:
            return _JR({"error": "Slug e titulo sao obrigatorios"}, status_code=400)
        link = create_scheduling_link(
            tenant_id=_tenant(sess), slug=slug, title=title,
            duration=body.get("duration_minutes", 30),
            days=body.get("available_days", "1,2,3,4,5"),
            start=body.get("available_start", "09:00"),
            end=body.get("available_end", "18:00"),
        )
        return _JR(link)

    @app.put("/api/v1/crm/scheduling-links/{slug}", tags=["crm"])
    async def crm_update_slink(slug: str, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..crm_models import update_scheduling_link
        body = await request.json()
        link = update_scheduling_link(slug, _tenant(sess), **body)
        if not link:
            return _JR({"error": "Link nao encontrado"}, status_code=404)
        return _JR(link)

    @app.delete("/api/v1/crm/scheduling-links/{slug}", tags=["crm"])
    async def crm_delete_slink(slug: str, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..crm_models import delete_scheduling_link
        ok = delete_scheduling_link(slug, _tenant(sess))
        if not ok:
            return _JR({"error": "Link nao encontrado"}, status_code=404)
        return _JR({"success": True})

    # ══════════════════════════════════════════════════════════
    # APPOINTMENTS
    # ══════════════════════════════════════════════════════════

    @app.get("/api/v1/crm/appointments", tags=["crm"])
    async def crm_list_appointments(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..crm_models import list_appointments
        date = request.query_params.get("date", "")
        status = request.query_params.get("status", "")
        return _JR({"appointments": list_appointments(_tenant(sess), date, status)})

    @app.put("/api/v1/crm/appointments/{apt_id}", tags=["crm"])
    async def crm_update_appointment(apt_id: str, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..crm_models import update_appointment
        body = await request.json()
        apt = update_appointment(apt_id, _tenant(sess), **body)
        if not apt:
            return _JR({"error": "Agendamento nao encontrado"}, status_code=404)
        return _JR(apt)

    # ══════════════════════════════════════════════════════════
    # PAGINA PUBLICA DE AGENDAMENTO
    # ══════════════════════════════════════════════════════════

    @app.get("/agendar/{slug}", tags=["crm"])
    async def crm_booking_page(slug: str, request: _Req):
        from ..crm_models import get_scheduling_link
        link = get_scheduling_link(slug)
        if not link or not link["active"]:
            return _HR("<h1 style='text-align:center;margin-top:80px;font-family:sans-serif'>Link de agendamento nao encontrado ou inativo.</h1>")
        tpl = _TPL_DIR / "agendar.html"
        if tpl.exists():
            html = tpl.read_text(encoding="utf-8")
            html = html.replace("{{SLUG}}", slug)
            html = html.replace("{{TITLE}}", link["title"])
            html = html.replace("{{DURATION}}", str(link["duration_minutes"]))
            return _HR(html)
        return _HR("<h1>Pagina de agendamento em construcao</h1>")

    @app.get("/api/v1/crm/availability/{slug}", tags=["crm"])
    async def crm_availability(slug: str, request: _Req):
        """Retorna horarios disponiveis para uma data (publico)."""
        from ..crm_models import get_available_slots
        date = request.query_params.get("date", "")
        if not date:
            return _JR({"error": "Parametro date obrigatorio (YYYY-MM-DD)"}, status_code=400)
        slots = get_available_slots(slug, date)
        return _JR({"date": date, "slots": slots})

    @app.post("/api/v1/crm/book/{slug}", tags=["crm"])
    async def crm_book_appointment(slug: str, request: _Req):
        """Cliente confirma agendamento (publico)."""
        from ..crm_models import (
            get_scheduling_link, get_available_slots, create_appointment,
            get_lead_by_email, get_lead_by_phone, create_lead, add_activity,
        )
        link = get_scheduling_link(slug)
        if not link or not link["active"]:
            return _JR({"error": "Link inativo"}, status_code=404)

        body = await request.json()
        name = body.get("name", "").strip()
        email = body.get("email", "").strip()
        phone = body.get("phone", "").strip()
        date = body.get("date", "").strip()
        time_str = body.get("time", "").strip()
        notes = body.get("notes", "")

        if not name or not date or not time_str:
            return _JR({"error": "Nome, data e horario sao obrigatorios"}, status_code=400)

        # Verifica disponibilidade
        slots = get_available_slots(slug, date)
        if time_str not in slots:
            return _JR({"error": "Horario indisponivel"}, status_code=400)

        tid = link["tenant_id"]

        # Busca ou cria lead
        lead = None
        if email:
            lead = get_lead_by_email(tid, email)
        if not lead and phone:
            lead = get_lead_by_phone(tid, phone)
        if not lead:
            lead = create_lead(tid, name=name, email=email, phone=phone,
                               source="agendamento")

        # Cria agendamento
        apt = create_appointment(
            tenant_id=tid, name=name, email=email, phone=phone,
            lead_id=lead["id"], date=date, time_str=time_str,
            duration=link["duration_minutes"], notes=notes,
        )

        # Registra atividade no lead
        add_activity(lead["id"], tid, "meeting",
                     f"Agendamento: {date} {time_str} ({link['title']})")

        return _JR({"success": True, "appointment": apt})

    # ══════════════════════════════════════════════════════════
    # DASHBOARD CRM
    # ══════════════════════════════════════════════════════════

    @app.get("/api/v1/crm/dashboard", tags=["crm"])
    async def crm_dashboard(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..crm_models import get_dashboard_stats, get_stale_leads
        tid = _tenant(sess)
        stats = get_dashboard_stats(tid)
        stats["stale_leads"] = get_stale_leads(tid, days=3)
        return _JR(stats)

    # ══════════════════════════════════════════════════════════
    # SUGESTOES IA
    # ══════════════════════════════════════════════════════════

    @app.get("/api/v1/crm/suggestions", tags=["crm"])
    async def crm_suggestions(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..crm_intelligence import get_ai_suggestions
        suggestions = get_ai_suggestions(_tenant(sess))
        return _JR({"suggestions": suggestions})

    @app.post("/api/v1/crm/suggestions/{lead_id}/execute", tags=["crm"])
    async def crm_execute_suggestion(lead_id: str, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..crm_intelligence import execute_suggestion
        body = await request.json()
        action = body.get("action", "")
        result = execute_suggestion(lead_id, _tenant(sess), action)
        return _JR(result)

    # ══════════════════════════════════════════════════════════
    # WEBHOOK PARA FORMULARIOS / LANDING PAGES
    # ══════════════════════════════════════════════════════════

    @app.post("/api/v1/crm/webhook/form/{tenant_id}", tags=["crm"])
    async def crm_form_webhook(tenant_id: str, request: _Req):
        """Recebe dados de formulario de landing pages (publico)."""
        from ..crm_models import create_lead, get_lead_by_email, get_lead_by_phone
        try:
            content_type = request.headers.get("content-type", "")
            if "json" in content_type:
                body = await request.json()
            else:
                form = await request.form()
                body = dict(form)

            name = body.get("name", "").strip()
            email = body.get("email", "").strip()
            phone = body.get("phone", "").strip()
            source = body.get("source", "landing_page")

            if not name and not email and not phone:
                return _JR({"error": "Dados insuficientes"}, status_code=400)

            # Evita duplicatas
            existing = None
            if email:
                existing = get_lead_by_email(tenant_id, email)
            if not existing and phone:
                existing = get_lead_by_phone(tenant_id, phone)

            if existing:
                return _JR({"success": True, "lead_id": existing["id"], "message": "Lead ja existe"})

            lead = create_lead(tenant_id, name=name, email=email, phone=phone, source=source)
            return _JR({"success": True, "lead_id": lead["id"]})
        except Exception as e:
            return _JR({"error": str(e)[:200]}, status_code=500)
