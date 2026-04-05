"""CRM Follow-up Automatico — envia mensagens para leads inativos.

Gera mensagens personalizadas com IA baseadas no contexto da conversa.
Respeita horario comercial, maximo de follow-ups e intervalo entre envios.
"""

from __future__ import annotations

import json
import time
import threading
from pathlib import Path

from . import config
from .logging import log_action

_FOLLOWUP_DIR = config.CLOW_HOME / "crm_followup"
_FOLLOWUP_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_RULES = {
    "contatado": {
        "delay_hours": 24,
        "max_followups": 3,
        "interval_hours": 48,
        "tone": "amigavel e casual",
        "enabled": True,
    },
    "qualificado": {
        "delay_hours": 24,
        "max_followups": 2,
        "interval_hours": 72,
        "tone": "profissional com urgencia sutil",
        "enabled": True,
    },
    "proposta": {
        "delay_hours": 48,
        "max_followups": 3,
        "interval_hours": 48,
        "tone": "consultivo, oferecer ajuda com duvidas",
        "enabled": True,
    },
}

DEFAULT_SCHEDULE = {
    "enabled": False,
    "start_hour": "08:00",
    "end_hour": "20:00",
    "weekends": False,
}


def _config_path(tenant_id: str, instance_id: str) -> Path:
    d = _FOLLOWUP_DIR / tenant_id / instance_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_followup_config(tenant_id: str, instance_id: str) -> dict:
    """Retorna config de follow-up (regras + schedule)."""
    path = _config_path(tenant_id, instance_id) / "config.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"rules": DEFAULT_RULES, "schedule": DEFAULT_SCHEDULE}


def save_followup_config(tenant_id: str, instance_id: str, cfg: dict) -> None:
    path = _config_path(tenant_id, instance_id) / "config.json"
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def get_followup_history(lead_id: str) -> list[dict]:
    """Retorna historico de follow-ups enviados para um lead."""
    from .crm_models import get_lead_timeline
    timeline = get_lead_timeline(lead_id)
    return [a for a in timeline if a.get("type") == "auto_followup"]


def is_followup_paused(lead_id: str) -> bool:
    """Verifica se follow-ups estao pausados para este lead."""
    path = _FOLLOWUP_DIR / "paused" / f"{lead_id}.flag"
    return path.exists()


def pause_followup(lead_id: str) -> None:
    d = _FOLLOWUP_DIR / "paused"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{lead_id}.flag").write_text("1", encoding="utf-8")


def resume_followup(lead_id: str) -> None:
    path = _FOLLOWUP_DIR / "paused" / f"{lead_id}.flag"
    if path.exists():
        path.unlink()


def _is_business_hours(schedule: dict) -> bool:
    """Verifica se estamos em horario comercial."""
    from datetime import datetime
    now = datetime.now()
    # Fins de semana
    if now.weekday() >= 5 and not schedule.get("weekends", False):
        return False
    start = schedule.get("start_hour", "08:00")
    end = schedule.get("end_hour", "20:00")
    current = f"{now.hour:02d}:{now.minute:02d}"
    return start <= current <= end


def generate_followup_message(lead_name: str, last_messages: list[dict],
                              stage: str, tone: str, followup_number: int) -> str:
    """Gera mensagem de follow-up personalizada com Haiku."""
    msgs_preview = ""
    for m in last_messages[-5:]:
        role = "Cliente" if m.get("role") == "user" else "Agente"
        msgs_preview += f"{role}: {m.get('content', '')[:100]}\n"

    prompt = f"""Gere uma mensagem de follow-up para WhatsApp. CURTA e NATURAL.

Nome do cliente: {lead_name}
Estagio: {stage}
Tom: {tone}
Follow-up numero: {followup_number}
Ultima conversa:
{msgs_preview}

Regras:
- Maximo 2 frases
- Sem formalidade excessiva
- Referencie algo da conversa anterior
- Nao use "Prezado" ou "Estimado"
- Use emoji com moderacao (max 1)

Responda APENAS com a mensagem, sem aspas nem explicacao."""

    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
        )
        return response.content[0].text.strip() if response.content else ""
    except Exception as e:
        log_action("followup_gen_error", str(e)[:200], level="error")
        return f"Oi {lead_name}! Tudo bem? Vi que conversamos recentemente, posso ajudar com mais alguma coisa?"


def check_and_send_followups(tenant_id: str, instance_id: str) -> int:
    """Verifica leads inativos e envia follow-ups. Retorna quantidade enviada."""
    cfg = get_followup_config(tenant_id, instance_id)
    schedule = cfg.get("schedule", DEFAULT_SCHEDULE)

    if not schedule.get("enabled", False):
        return 0
    if not _is_business_hours(schedule):
        return 0

    rules = cfg.get("rules", DEFAULT_RULES)
    sent_count = 0

    from .crm_models import list_leads, get_lead_timeline, add_activity
    from .whatsapp_agent import get_wa_manager

    manager = get_wa_manager()
    inst = manager.get_instance(instance_id, tenant_id)
    if not inst or not inst.active:
        return 0

    # Para cada status com regra
    for status, rule in rules.items():
        if not rule.get("enabled", True):
            continue

        delay_seconds = rule.get("delay_hours", 24) * 3600
        max_followups = rule.get("max_followups", 3)
        interval_seconds = rule.get("interval_hours", 48) * 3600
        tone = rule.get("tone", "amigavel")

        # Busca leads neste status
        result = list_leads(tenant_id, status=status, instance_id=instance_id, limit=100)
        leads = result.get("leads", [])

        now = time.time()
        for lead in leads:
            lead_id = lead["id"]
            phone = lead.get("phone", "")
            name = lead.get("name", "")

            if not phone or is_followup_paused(lead_id):
                continue

            # Verifica ultimo contato
            last_contact = lead.get("last_contact_at") or lead.get("updated_at") or lead.get("created_at", 0)
            if now - last_contact < delay_seconds:
                continue

            # Conta follow-ups ja enviados
            history = get_followup_history(lead_id)
            if len(history) >= max_followups:
                continue

            # Verifica intervalo desde ultimo follow-up
            if history:
                last_followup = max(h.get("created_at", 0) for h in history)
                if now - last_followup < interval_seconds:
                    continue

            # Gera e envia
            conv_history = manager.get_conversation_history(inst, phone)
            msg = generate_followup_message(name, conv_history, status, tone, len(history) + 1)

            if msg:
                manager._send_zapi(inst, phone, msg)
                manager._save_message(inst, phone, "assistant", msg)
                add_activity(lead_id, tenant_id, "auto_followup",
                             f"🔄 Follow-up #{len(history)+1}: {msg[:100]}")
                sent_count += 1
                log_action("followup_sent", f"lead={lead_id} #{len(history)+1}")

    return sent_count


def run_followup_check_all() -> None:
    """Roda check para todos os tenants/instancias. Chamado pelo cron."""
    from .whatsapp_agent import get_wa_manager, WA_BASE_DIR
    if not WA_BASE_DIR.exists():
        return
    for tenant_dir in WA_BASE_DIR.iterdir():
        if not tenant_dir.is_dir():
            continue
        tenant_id = tenant_dir.name
        for inst_dir in tenant_dir.iterdir():
            if not inst_dir.is_dir():
                continue
            instance_id = inst_dir.name
            try:
                check_and_send_followups(tenant_id, instance_id)
            except Exception as e:
                log_action("followup_check_error", f"{tenant_id}/{instance_id}: {e}", level="error")
