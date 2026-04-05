"""Notificacoes Multi-Canal — badge, push e WhatsApp.

Centraliza todas as notificacoes do sistema: leads novos, alertas,
vendas, falhas. Cada tenant configura canais e preferencias.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from . import config
from .logging import log_action

_NOTIF_DIR = config.CLOW_HOME / "notifications"
_NOTIF_DIR.mkdir(parents=True, exist_ok=True)

NOTIFICATION_TYPES = {
    "lead_new": {"title": "Novo lead", "priority": "normal", "icon": "👤"},
    "lead_hot": {"title": "Lead quente", "priority": "high", "icon": "🔥"},
    "agent_failed": {"title": "Agente falhou", "priority": "high", "icon": "⚠️"},
    "quota_warning": {"title": "Franquia em 80%", "priority": "high", "icon": "⚠️"},
    "quota_limit": {"title": "Franquia atingida", "priority": "urgent", "icon": "🚫"},
    "infra_down": {"title": "Servidor offline", "priority": "urgent", "icon": "🔴"},
    "infra_up": {"title": "Servidor voltou", "priority": "normal", "icon": "🟢"},
    "deal_closed": {"title": "Venda fechada!", "priority": "normal", "icon": "💰"},
    "followup_responded": {"title": "Follow-up respondido", "priority": "normal", "icon": "💬"},
    "funnel_suggestion": {"title": "Sugestao do funil", "priority": "low", "icon": "🤖"},
}


def _tenant_dir(tenant_id: str) -> Path:
    d = _NOTIF_DIR / tenant_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_notifications(tenant_id: str) -> list[dict]:
    path = _tenant_dir(tenant_id) / "notifications.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_notifications(tenant_id: str, notifs: list[dict]) -> None:
    # Max 200
    if len(notifs) > 200:
        notifs = notifs[-200:]
    path = _tenant_dir(tenant_id) / "notifications.json"
    path.write_text(json.dumps(notifs, ensure_ascii=False), encoding="utf-8")


def get_config(tenant_id: str) -> dict:
    path = _tenant_dir(tenant_id) / "config.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "channel_badge": True,
        "channel_whatsapp": True,
        "whatsapp_number": "",
        "quiet_start": "22:00",
        "quiet_end": "07:00",
        "quiet_enabled": False,
    }


def save_config(tenant_id: str, cfg: dict) -> None:
    path = _tenant_dir(tenant_id) / "config.json"
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def send_notification(tenant_id: str, ntype: str, message: str,
                      data: dict | None = None) -> str:
    """Envia notificacao. Retorna ID."""
    type_info = NOTIFICATION_TYPES.get(ntype, {"title": ntype, "priority": "normal", "icon": "📋"})
    nid = uuid.uuid4().hex[:10]
    notif = {
        "id": nid,
        "type": ntype,
        "title": type_info["title"],
        "icon": type_info["icon"],
        "priority": type_info["priority"],
        "message": message,
        "data": data or {},
        "read": False,
        "created_at": time.time(),
    }

    # Salva no badge
    cfg = get_config(tenant_id)
    if cfg.get("channel_badge", True):
        notifs = _load_notifications(tenant_id)
        notifs.append(notif)
        _save_notifications(tenant_id, notifs)

    # WhatsApp para urgentes
    if cfg.get("channel_whatsapp") and type_info["priority"] in ("high", "urgent"):
        phone = cfg.get("whatsapp_number", "")
        if phone:
            _send_whatsapp_alert(tenant_id, phone, type_info["icon"], type_info["title"], message)

    return nid


def _send_whatsapp_alert(tenant_id: str, phone: str, icon: str, title: str, message: str) -> None:
    """Envia alerta via WhatsApp."""
    try:
        from .whatsapp_agent import get_wa_manager
        manager = get_wa_manager()
        instances = manager.get_instances(tenant_id)
        if not instances:
            return
        inst = manager.get_instance(instances[0]["id"], tenant_id)
        if inst:
            msg = f"{icon} *{title}*\n{message}"
            manager._send_zapi(inst, phone, msg)
    except Exception:
        pass


def get_notifications(tenant_id: str, unread_only: bool = False, limit: int = 50) -> list[dict]:
    notifs = _load_notifications(tenant_id)
    if unread_only:
        notifs = [n for n in notifs if not n.get("read")]
    return notifs[-limit:]


def get_unread_count(tenant_id: str) -> int:
    notifs = _load_notifications(tenant_id)
    return sum(1 for n in notifs if not n.get("read"))


def mark_read(tenant_id: str, nid: str) -> None:
    notifs = _load_notifications(tenant_id)
    for n in notifs:
        if n.get("id") == nid:
            n["read"] = True
            break
    _save_notifications(tenant_id, notifs)


def mark_all_read(tenant_id: str) -> None:
    notifs = _load_notifications(tenant_id)
    for n in notifs:
        n["read"] = True
    _save_notifications(tenant_id, notifs)
