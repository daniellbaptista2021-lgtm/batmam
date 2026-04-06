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

    def _check_crm_access(sess: dict):
        """Verifica se o plano do usuario inclui CRM."""
        from ..database import get_user_by_id
        from ..billing import PLANS
        user = get_user_by_id(sess["user_id"])
        plan_id = user.get("plan", "byok_free") if user else "byok_free"
        if plan_id in ("free", "basic", "unlimited"):
            plan_id = "byok_free"
        plan = PLANS.get(plan_id, PLANS["byok_free"])
        if not plan.get("crm_enabled", False) and not sess.get("is_admin"):
            return _JR({
                "error": "crm_not_available",
                "message": "O CRM nao esta disponivel no plano gratuito. Faca upgrade a partir do plano Lite (R$ 169/mes).",
                "upgrade_url": "/app/settings#plan",
            }, status_code=403)
        return None

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
        blocked = _check_crm_access(sess)
        if blocked:
            return blocked
        from ..crm_models import list_leads, search_leads
        tid = _tenant(sess)
        instance_id = request.query_params.get("instance_id", "")
        search = request.query_params.get("search", "")
        if search:
            leads = search_leads(tid, search)
            if instance_id:
                leads = [l for l in leads if l.get("instance_id") == instance_id]
            return _JR({"leads": leads, "total": len(leads), "page": 1, "pages": 1})
        status = request.query_params.get("status", "")
        source = request.query_params.get("source", "")
        page = int(request.query_params.get("page", "1"))
        limit = int(request.query_params.get("limit", "50"))
        return _JR(list_leads(tid, status=status, source=source, instance_id=instance_id, page=page, limit=limit))

    @app.post("/api/v1/crm/leads", tags=["crm"])
    async def crm_create_lead(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..crm_models import create_lead

        # Assinantes so recebem leads via WhatsApp; manual apenas admin
        is_admin = sess.get("is_admin", False)
        body = await request.json()
        source = body.get("source", "manual")
        if not is_admin and source not in ("whatsapp", "agendamento"):
            source = "manual"  # Admin pode qualquer source

        lead = create_lead(
            tenant_id=_tenant(sess),
            name=body.get("name", ""),
            email=body.get("email", ""),
            phone=body.get("phone", ""),
            source=source,
            notes=body.get("notes", ""),
            tags=body.get("tags"),
            custom_fields=body.get("custom_fields"),
            instance_id=body.get("instance_id", ""),
            source_phone=body.get("source_phone", ""),
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
        tid = _tenant(sess)
        lead = change_lead_status(lead_id, tid, new_status)
        if not lead:
            return _JR({"error": "Lead nao encontrado"}, status_code=404)
        # Marca como arraste manual para o funil automatico respeitar
        try:
            from ..crm_models import update_lead, add_activity
            import json as _json
            cf = _json.loads(lead.get("custom_fields") or "{}") if isinstance(lead.get("custom_fields"), str) else (lead.get("custom_fields") or {})
            cf["last_move_source"] = "manual"
            update_lead(lead_id, tid, custom_fields=cf)
            add_activity(lead_id, tid, "status_change", f"👤 Movido manualmente para {new_status}")
        except Exception:
            pass
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
    # INSTANCIAS + METRICAS POR INSTANCIA
    # ══════════════════════════════════════════════════════════

    @app.get("/api/v1/crm/instances", tags=["crm"])
    async def crm_instances(request: _Req):
        """Lista instancias Z-API do tenant com contagem de leads."""
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        tid = _tenant(sess)
        from ..whatsapp_agent import get_wa_manager
        from ..crm_models import get_leads_count_by_instance
        manager = get_wa_manager()
        wa_instances = manager.get_instances(tid)
        lead_counts = get_leads_count_by_instance(tid)
        result = []
        for inst in wa_instances:
            iid = inst["id"]
            counts = lead_counts.get(iid, {"total": 0, "new_today": 0})
            result.append({
                "instance_id": iid,
                "name": inst.get("name", "WhatsApp"),
                "phone": inst.get("zapi_instance_id", ""),
                "active": inst.get("active", True),
                "leads_count": counts["total"],
                "new_today": counts["new_today"],
            })
        return _JR(result)

    @app.get("/api/v1/crm/metrics", tags=["crm"])
    async def crm_metrics(request: _Req):
        """Metricas filtradas por instancia."""
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        tid = _tenant(sess)
        instance_id = request.query_params.get("instance_id", "")
        if not instance_id:
            return _JR({"error": "instance_id obrigatorio"}, status_code=400)
        from ..crm_models import get_instance_metrics
        metrics = get_instance_metrics(tid, instance_id)
        # Adiciona nome da instancia
        from ..whatsapp_agent import get_wa_manager
        inst = get_wa_manager().get_instance(instance_id, tid)
        if inst:
            metrics["instance_name"] = inst.name
            metrics["phone"] = inst.zapi_instance_id
        return _JR(metrics)

    # ══════════════════════════════════════════════════════════
    # FUNIL AUTOMATICO
    # ══════════════════════════════════════════════════════════

    @app.get("/api/v1/crm/funnel/rules", tags=["crm"])
    async def crm_funnel_rules(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        instance_id = request.query_params.get("instance_id", "")
        if not instance_id:
            return _JR({"error": "instance_id obrigatorio"}, status_code=400)
        from ..crm_auto_funnel import get_rules, is_enabled
        return _JR({"rules": get_rules(_tenant(sess), instance_id), "enabled": is_enabled(_tenant(sess), instance_id)})

    @app.put("/api/v1/crm/funnel/rules", tags=["crm"])
    async def crm_funnel_save_rules(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        instance_id = body.get("instance_id", "")
        if not instance_id:
            return _JR({"error": "instance_id obrigatorio"}, status_code=400)
        from ..crm_auto_funnel import set_rules, set_enabled
        if "rules" in body:
            set_rules(_tenant(sess), instance_id, body["rules"])
        if "enabled" in body:
            set_enabled(_tenant(sess), instance_id, body["enabled"])
        return _JR({"success": True})

    @app.get("/api/v1/crm/funnel/suggestions", tags=["crm"])
    async def crm_funnel_suggestions(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        instance_id = request.query_params.get("instance_id", "")
        from ..crm_auto_funnel import get_pending_suggestions
        return _JR({"suggestions": get_pending_suggestions(_tenant(sess), instance_id)})

    @app.post("/api/v1/crm/funnel/suggestion/{lead_id}/accept", tags=["crm"])
    async def crm_funnel_accept(lead_id: str, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        tid = _tenant(sess)
        body = await request.json()
        instance_id = body.get("instance_id", "")
        from ..crm_auto_funnel import get_pending_suggestions, dismiss_suggestion
        suggestions = get_pending_suggestions(tid, instance_id)
        suggestion = next((s for s in suggestions if s.get("lead_id") == lead_id), None)
        if not suggestion:
            return _JR({"error": "Sugestao nao encontrada"}, status_code=404)
        from ..crm_models import change_lead_status, add_activity
        change_lead_status(lead_id, tid, suggestion["suggested_stage"])
        add_activity(lead_id, tid, "status_change",
                     f"👤 Sugestao IA aceita: {suggestion['current_stage']} → {suggestion['suggested_stage']}")
        dismiss_suggestion(tid, instance_id, lead_id)
        return _JR({"success": True})

    @app.post("/api/v1/crm/funnel/suggestion/{lead_id}/dismiss", tags=["crm"])
    async def crm_funnel_dismiss(lead_id: str, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        from ..crm_auto_funnel import dismiss_suggestion
        dismiss_suggestion(_tenant(sess), body.get("instance_id", ""), lead_id)
        return _JR({"success": True})

    # ══════════════════════════════════════════════════════════
    # FOLLOW-UP AUTOMATICO
    # ══════════════════════════════════════════════════════════

    @app.get("/api/v1/crm/followup/config", tags=["crm"])
    async def crm_followup_config(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        instance_id = request.query_params.get("instance_id", "")
        from ..crm_followup import get_followup_config
        return _JR(get_followup_config(_tenant(sess), instance_id))

    @app.put("/api/v1/crm/followup/config", tags=["crm"])
    async def crm_followup_save(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        instance_id = body.get("instance_id", "")
        from ..crm_followup import save_followup_config
        save_followup_config(_tenant(sess), instance_id, body.get("config", body))
        return _JR({"success": True})

    @app.post("/api/v1/crm/followup/{lead_id}/pause", tags=["crm"])
    async def crm_followup_pause(lead_id: str, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..crm_followup import pause_followup
        pause_followup(lead_id)
        return _JR({"success": True})

    @app.get("/api/v1/crm/followup/{lead_id}/history", tags=["crm"])
    async def crm_followup_history(lead_id: str, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..crm_followup import get_followup_history
        return _JR({"history": get_followup_history(lead_id)})

    # ══════════════════════════════════════════════════════════
    # RELATORIO DIARIO
    # ══════════════════════════════════════════════════════════

    @app.get("/api/v1/crm/report/config", tags=["crm"])
    async def crm_report_config(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        instance_id = request.query_params.get("instance_id", "")
        from ..crm_daily_report import get_report_config
        return _JR(get_report_config(_tenant(sess), instance_id))

    @app.put("/api/v1/crm/report/config", tags=["crm"])
    async def crm_report_save(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        from ..crm_daily_report import save_report_config
        save_report_config(_tenant(sess), body.get("instance_id", ""), body.get("config", body))
        return _JR({"success": True})

    @app.post("/api/v1/crm/report/preview", tags=["crm"])
    async def crm_report_preview(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        from ..crm_daily_report import generate_report, format_whatsapp_message
        report = generate_report(_tenant(sess), body.get("instance_id", ""))
        return _JR({"report": report, "message": format_whatsapp_message(report)})

    @app.post("/api/v1/crm/report/send-now", tags=["crm"])
    async def crm_report_send(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        from ..crm_daily_report import send_report
        result = send_report(_tenant(sess), body.get("instance_id", ""))
        return _JR(result)

    # ══════════════════════════════════════════════════════════
    # TREINAMENTO DO AGENTE
    # ══════════════════════════════════════════════════════════

    @app.post("/api/v1/crm/training/correction", tags=["crm"])
    async def crm_save_correction(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        from ..crm_agent_training import record_correction
        cid = record_correction(
            _tenant(sess), body.get("instance_id", ""),
            body.get("client_message", ""),
            body.get("original_response", ""),
            body.get("corrected_response", ""),
            body.get("context"),
        )
        return _JR({"success": True, "correction_id": cid})

    @app.get("/api/v1/crm/training/corrections", tags=["crm"])
    async def crm_list_corrections(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        instance_id = request.query_params.get("instance_id", "")
        from ..crm_agent_training import get_corrections
        return _JR({"corrections": get_corrections(_tenant(sess), instance_id)})

    @app.delete("/api/v1/crm/training/correction/{cid}", tags=["crm"])
    async def crm_delete_correction(cid: str, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        instance_id = request.query_params.get("instance_id", "")
        from ..crm_agent_training import delete_correction
        ok = delete_correction(_tenant(sess), instance_id, cid)
        return _JR({"success": ok})

    @app.post("/api/v1/crm/training/consolidate", tags=["crm"])
    async def crm_consolidate(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        from ..crm_agent_training import consolidate_corrections
        rules = consolidate_corrections(_tenant(sess), body.get("instance_id", ""))
        return _JR({"success": True, "rules": rules})

    # ══════════════════════════════════════════════════════════
    # RESULTADOS / ROI
    # ══════════════════════════════════════════════════════════

    @app.get("/api/v1/crm/results", tags=["crm"])
    async def crm_results(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        instance_id = request.query_params.get("instance_id", "")
        period = request.query_params.get("period", "30d")
        days = int(period.replace("d", "")) if period.endswith("d") else 30
        from ..crm_models import get_results_data
        return _JR(get_results_data(_tenant(sess), instance_id, days))

    @app.put("/api/v1/crm/leads/{lead_id}/deal", tags=["crm"])
    async def crm_update_deal(lead_id: str, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        from ..crm_models import update_lead, add_activity
        tid = _tenant(sess)
        updates = {}
        if "value" in body:
            updates["deal_value"] = float(body["value"])
        if "products" in body:
            updates["deal_products"] = body["products"] if isinstance(body["products"], str) else json.dumps(body["products"])
        if "notes" in body:
            updates["deal_notes"] = body["notes"]
        lead = update_lead(lead_id, tid, **updates)
        if not lead:
            return _JR({"error": "Lead nao encontrado"}, status_code=404)
        if "value" in body:
            add_activity(lead_id, tid, "note", f"Valor do negocio: R$ {body['value']}")
        return _JR(lead)

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
    # NOTIFICACOES
    # ══════════════════════════════════════════════════════════

    @app.get("/api/v1/notifications", tags=["notifications"])
    async def notif_list(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..notifications import get_notifications
        unread = request.query_params.get("unread", "") == "1"
        return _JR({"notifications": get_notifications(_tenant(sess), unread)})

    @app.get("/api/v1/notifications/unread-count", tags=["notifications"])
    async def notif_count(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..notifications import get_unread_count
        return _JR({"count": get_unread_count(_tenant(sess))})

    @app.post("/api/v1/notifications/{nid}/read", tags=["notifications"])
    async def notif_read(nid: str, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..notifications import mark_read
        mark_read(_tenant(sess), nid)
        return _JR({"success": True})

    @app.post("/api/v1/notifications/read-all", tags=["notifications"])
    async def notif_read_all(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..notifications import mark_all_read
        mark_all_read(_tenant(sess))
        return _JR({"success": True})

    @app.put("/api/v1/notifications/config", tags=["notifications"])
    async def notif_config(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        from ..notifications import save_config
        save_config(_tenant(sess), body)
        return _JR({"success": True})

    # ══════════════════════════════════════════════════════════
    # A/B TESTING
    # ══════════════════════════════════════════════════════════

    @app.post("/api/v1/ab-test/create", tags=["ab-test"])
    async def ab_create(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        from ..prompt_ab_test import create_test
        result = create_test(_tenant(sess), body.get("instance_id", ""),
                             body.get("prompt_a", ""), body.get("prompt_b", ""),
                             int(body.get("sample_size", 100)))
        return _JR(result)

    @app.get("/api/v1/ab-test/{instance_id}", tags=["ab-test"])
    async def ab_results(instance_id: str, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..prompt_ab_test import get_results
        results = get_results(instance_id)
        if not results:
            return _JR({"error": "Nenhum teste encontrado"}, status_code=404)
        return _JR(results)

    @app.post("/api/v1/ab-test/{test_id}/end", tags=["ab-test"])
    async def ab_end(test_id: str, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        from ..prompt_ab_test import end_test
        return _JR(end_test(test_id, body.get("apply_winner", True)))

    # ══════════════════════════════════════════════════════════
    # WEBHOOK PARA FORMULARIOS / LANDING PAGES
    # ══════════════════════════════════════════════════════════

    @app.post("/api/v1/crm/webhook/form/{tenant_id}", tags=["crm"])
    async def crm_form_webhook(tenant_id: str, request: _Req):
        """Recebe dados de formulario de landing pages (publico).
        Cria lead e opcionalmente envia WhatsApp de boas-vindas.
        """
        from ..crm_models import create_lead, get_lead_by_email, get_lead_by_phone, add_activity
        try:
            content_type = request.headers.get("content-type", "")
            if "json" in content_type:
                body = await request.json()
            else:
                form = await request.form()
                body = dict(form)

            name = (body.get("name") or body.get("nome") or "").strip()
            email = (body.get("email") or "").strip()
            phone = (body.get("phone") or body.get("telefone") or "").strip()
            source = body.get("source", "landing_page")
            instance_id = body.get("instance_id", "")
            welcome_msg = body.get("welcome_message", "")
            interesse = body.get("interesse", "")
            pagina = body.get("pagina", "")

            if not name and not email and not phone:
                return _JR({"error": "Dados insuficientes"}, status_code=400)

            # Evita duplicatas
            existing = None
            if email:
                existing = get_lead_by_email(tenant_id, email)
            if not existing and phone:
                existing = get_lead_by_phone(tenant_id, phone)

            if existing:
                lead = existing
            else:
                lead = create_lead(tenant_id, name=name, email=email, phone=phone,
                                   source=source, instance_id=instance_id)
                add_activity(lead["id"], tenant_id, "note",
                             f"🌐 Lead via landing page" + (f": {pagina}" if pagina else ""))

            # Envia WhatsApp de boas-vindas se tiver phone e instance_id
            if phone and instance_id and welcome_msg:
                import threading
                delay = int(body.get("delay", "30"))
                def _send_welcome():
                    import time as _t
                    _t.sleep(delay)
                    try:
                        from ..whatsapp_agent import get_wa_manager
                        manager = get_wa_manager()
                        inst = manager.get_instance(instance_id, tenant_id)
                        if inst and inst.active:
                            # Substitui variaveis
                            msg = welcome_msg.replace("{nome}", name).replace("{email}", email)
                            msg = msg.replace("{telefone}", phone).replace("{interesse}", interesse)
                            msg = msg.replace("{pagina}", pagina)
                            manager._send_zapi(inst, phone, msg)
                            manager._save_message(inst, phone, "assistant", msg)
                            add_activity(lead["id"], tenant_id, "whatsapp",
                                         f"📱 Boas-vindas enviada: {msg[:80]}")
                    except Exception:
                        pass
                threading.Thread(target=_send_welcome, daemon=True).start()

            return _JR({"success": True, "lead_id": lead["id"]})
        except Exception as e:
            return _JR({"error": str(e)[:200]}, status_code=500)
