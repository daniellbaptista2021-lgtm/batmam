"""CRM Intelligence — sugestoes proativas de IA para follow-up.

Analisa leads inativos e gera sugestoes de acao:
- Follow-up WhatsApp para leads com telefone
- Follow-up email para leads com email
- Preparacao para agendamentos do dia
"""

from __future__ import annotations

import time
from datetime import datetime

from .logging import log_action


def get_ai_suggestions(tenant_id: str) -> list[dict]:
    """Gera sugestoes de IA baseadas no estado atual do CRM."""
    from .crm_models import get_stale_leads, list_appointments

    suggestions = []

    # 1. Leads inativos (sem contato ha 3+ dias)
    stale = get_stale_leads(tenant_id, days=3)
    for lead in stale[:10]:  # Max 10 sugestoes
        days_ago = 0
        if lead.get("last_contact_at"):
            days_ago = int((time.time() - lead["last_contact_at"]) / 86400)
        else:
            days_ago = int((time.time() - lead["created_at"]) / 86400)

        name = lead.get("name") or "Sem nome"

        if lead.get("phone"):
            suggestions.append({
                "lead_id": lead["id"],
                "type": "whatsapp_followup",
                "priority": "alta" if days_ago > 7 else "media",
                "title": f"Enviar WhatsApp para {name}",
                "description": f"Sem contato ha {days_ago} dias. Status: {lead['status']}.",
                "action": "whatsapp",
                "days_inactive": days_ago,
            })
        elif lead.get("email"):
            suggestions.append({
                "lead_id": lead["id"],
                "type": "email_followup",
                "priority": "alta" if days_ago > 7 else "media",
                "title": f"Enviar email para {name}",
                "description": f"Sem contato ha {days_ago} dias. Status: {lead['status']}.",
                "action": "email",
                "days_inactive": days_ago,
            })
        else:
            suggestions.append({
                "lead_id": lead["id"],
                "type": "manual_followup",
                "priority": "baixa",
                "title": f"Contatar {name}",
                "description": f"Sem contato ha {days_ago} dias. Sem telefone nem email cadastrado.",
                "action": "manual",
                "days_inactive": days_ago,
            })

    # 2. Agendamentos de hoje
    today = datetime.utcnow().strftime("%Y-%m-%d")
    appointments = list_appointments(tenant_id, date=today, status="confirmado")
    for apt in appointments:
        suggestions.append({
            "lead_id": apt.get("lead_id", ""),
            "type": "appointment_today",
            "priority": "alta",
            "title": f"Reuniao com {apt['name']} as {apt['time']}",
            "description": f"Agendamento confirmado para hoje. Duracao: {apt['duration_minutes']}min.",
            "action": "prepare",
            "appointment_id": apt["id"],
        })

    # Ordena por prioridade
    priority_order = {"alta": 0, "media": 1, "baixa": 2}
    suggestions.sort(key=lambda s: priority_order.get(s.get("priority", "baixa"), 3))

    return suggestions


def execute_suggestion(lead_id: str, tenant_id: str, action: str) -> dict:
    """Executa uma sugestao de follow-up.

    Actions:
      - whatsapp: envia mensagem de follow-up via Z-API
      - email: envia email de follow-up via SMTP
      - manual: registra como nota na timeline
    """
    from .crm_models import get_lead, add_activity

    lead = get_lead(lead_id, tenant_id)
    if not lead:
        return {"success": False, "error": "Lead nao encontrado"}

    name = lead.get("name") or "Cliente"

    if action == "whatsapp":
        if not lead.get("phone"):
            return {"success": False, "error": "Lead sem telefone"}

        # Envia via Z-API usando a primeira instancia ativa do tenant
        try:
            from .whatsapp_agent import get_wa_manager
            manager = get_wa_manager()
            instances = manager.get_instances(tenant_id)
            if not instances:
                return {"success": False, "error": "Nenhuma instancia WhatsApp configurada"}

            inst = manager.get_instance(instances[0]["id"], tenant_id)
            if not inst:
                return {"success": False, "error": "Instancia nao encontrada"}

            msg = f"Ola {name}, tudo bem? Estamos entrando em contato para saber se podemos ajudar em algo. Ficamos a disposicao!"
            manager._send_zapi(inst, lead["phone"], msg)

            add_activity(lead_id, tenant_id, "whatsapp", f"Follow-up automatico: {msg[:100]}")
            log_action("crm_followup_whatsapp", f"lead={lead_id}")
            return {"success": True, "message": f"WhatsApp enviado para {lead.get('phone')}"}
        except Exception as e:
            return {"success": False, "error": str(e)[:200]}

    elif action == "email":
        from .integrations.email_sender import send_followup_email
        result = send_followup_email(lead_id, tenant_id)
        if result["success"]:
            log_action("crm_followup_email", f"lead={lead_id}")
        return result

    elif action == "manual":
        add_activity(lead_id, tenant_id, "note", "Follow-up manual registrado pela IA")
        return {"success": True, "message": "Nota registrada na timeline"}

    return {"success": False, "error": f"Acao desconhecida: {action}"}
