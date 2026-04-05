"""CRM Daily Report — relatorio diario enviado no WhatsApp do dono.

Coleta metricas do dia e envia resumo formatado via Z-API.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from . import config
from .logging import log_action

_REPORT_DIR = config.CLOW_HOME / "crm_reports"
_REPORT_DIR.mkdir(parents=True, exist_ok=True)


def get_report_config(tenant_id: str, instance_id: str) -> dict:
    path = _REPORT_DIR / tenant_id / instance_id / "config.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "enabled": False,
        "time": "21:00",
        "phone": "",
        "weekends": True,
        "include": {
            "leads_summary": True,
            "funnel_movement": True,
            "attention_needed": True,
            "top_questions": False,
            "revenue_estimate": False,
        },
    }


def save_report_config(tenant_id: str, instance_id: str, cfg: dict) -> None:
    d = _REPORT_DIR / tenant_id / instance_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def generate_report(tenant_id: str, instance_id: str) -> dict:
    """Coleta metricas do dia."""
    from .crm_models import get_instance_metrics, get_stale_leads, list_leads

    metrics = get_instance_metrics(tenant_id, instance_id)
    stale = get_stale_leads(tenant_id, days=3, instance_id=instance_id)

    # Nome da instancia
    from .whatsapp_agent import get_wa_manager
    inst = get_wa_manager().get_instance(instance_id, tenant_id)
    inst_name = inst.name if inst else instance_id

    now = datetime.now()
    report = {
        "date": now.strftime("%d/%m/%Y"),
        "instance_name": inst_name,
        "leads_total": metrics.get("leads_total", 0),
        "leads_today": metrics.get("leads_today", 0),
        "leads_week": metrics.get("leads_this_week", 0),
        "messages_today": metrics.get("messages_today", 0),
        "conversions_week": metrics.get("conversions_this_week", 0),
        "pipeline": metrics.get("pipeline", {}),
        "leads_needing_attention": [
            {"name": l.get("name", "?"), "phone": l.get("phone", "")[-4:],
             "reason": f"Sem contato ha {int((time.time() - (l.get('last_contact_at') or l.get('created_at', 0))) / 86400)} dias"}
            for l in stale[:5]
        ],
    }
    return report


def format_whatsapp_message(report: dict) -> str:
    """Formata relatorio como mensagem WhatsApp."""
    pipeline = report.get("pipeline", {})
    attention = report.get("leads_needing_attention", [])

    msg = f"""📊 *Relatorio do dia — {report['date']}*
_{report['instance_name']}_

📈 *Resumo*
• {report['leads_today']} leads novos hoje
• {report['messages_today']} mensagens trocadas
• {report['conversions_week']} conversoes na semana
• {report['leads_total']} leads total

⚡ *Pipeline*"""

    for status, count in pipeline.items():
        msg += f"\n{status}: {count}"

    if attention:
        msg += "\n\n⚠️ *Atencao necessaria*"
        for a in attention:
            msg += f"\n• {a['name']} (...{a['phone']}): {a['reason']}"

    msg += "\n\n_Enviado pelo Clow_"
    return msg


def send_report(tenant_id: str, instance_id: str) -> dict:
    """Gera e envia relatorio via Z-API."""
    cfg = get_report_config(tenant_id, instance_id)
    phone = cfg.get("phone", "")
    if not phone:
        return {"error": "Numero do dono nao configurado"}

    report = generate_report(tenant_id, instance_id)
    message = format_whatsapp_message(report)

    from .whatsapp_agent import get_wa_manager
    manager = get_wa_manager()
    inst = manager.get_instance(instance_id, tenant_id)
    if not inst:
        return {"error": "Instancia nao encontrada"}

    success = manager._send_zapi(inst, phone, message)
    if success:
        log_action("daily_report_sent", f"tenant={tenant_id} inst={instance_id}")
    return {"success": success, "report": report, "message": message}


def run_daily_reports() -> None:
    """Chamado pelo cron — verifica quais tenants precisam de relatorio agora."""
    from .whatsapp_agent import WA_BASE_DIR
    if not WA_BASE_DIR.exists():
        return

    now = datetime.now()
    current_time = f"{now.hour:02d}:{now.minute:02d}"

    # Margem de 5 minutos
    current_min = now.hour * 60 + now.minute

    for tenant_dir in WA_BASE_DIR.iterdir():
        if not tenant_dir.is_dir():
            continue
        tenant_id = tenant_dir.name
        for inst_dir in tenant_dir.iterdir():
            if not inst_dir.is_dir():
                continue
            instance_id = inst_dir.name
            try:
                cfg = get_report_config(tenant_id, instance_id)
                if not cfg.get("enabled"):
                    continue
                if not cfg.get("weekends", True) and now.weekday() >= 5:
                    continue
                report_time = cfg.get("time", "21:00")
                rh, rm = map(int, report_time.split(":"))
                report_min = rh * 60 + rm
                # Dentro de 5 minutos do horario configurado
                if abs(current_min - report_min) <= 2:
                    send_report(tenant_id, instance_id)
            except Exception as e:
                log_action("daily_report_error", f"{tenant_id}/{instance_id}: {e}", level="error")
