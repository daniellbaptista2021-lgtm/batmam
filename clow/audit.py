"""Audit Trail — registro de todas as acoes relevantes no sistema.

Cada tenant tem seu proprio log de auditoria.
Categorias: auth, crm, whatsapp, agent, billing, settings, data, team, infra, system.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from . import config
from .logging import log_action

_AUDIT_DIR = config.CLOW_HOME / "audit"
_AUDIT_DIR.mkdir(parents=True, exist_ok=True)

CATEGORIES = {
    "auth": "Autenticacao", "crm": "CRM", "whatsapp": "WhatsApp",
    "agent": "Agente IA", "billing": "Faturamento", "settings": "Configuracoes",
    "data": "Dados", "team": "Equipe", "infra": "Infraestrutura", "system": "Sistema",
}

SUPER_ADMIN_KEY = os.getenv("CLOW_SUPER_ADMIN_KEY", "clow-super-admin-2026")


def _audit_path(tenant_id: str) -> Path:
    d = _AUDIT_DIR / tenant_id
    d.mkdir(parents=True, exist_ok=True)
    return d / "logs.json"


def _load_logs(tenant_id: str) -> list[dict]:
    path = _audit_path(tenant_id)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_logs(tenant_id: str, logs: list[dict]) -> None:
    # Max 5000 entries
    if len(logs) > 5000:
        logs = logs[-5000:]
    _audit_path(tenant_id).write_text(json.dumps(logs, ensure_ascii=False), encoding="utf-8")


def log_event(tenant_id: str, category: str, action: str,
              level: str = "info", user_id: str = "", user_name: str = "",
              details: str = "", ip_address: str = "",
              metadata: dict | None = None) -> None:
    """Registra um evento no audit log."""
    logs = _load_logs(tenant_id)
    logs.append({
        "timestamp": time.time(),
        "category": category,
        "action": action,
        "level": level,
        "user_id": user_id,
        "user_name": user_name or "Sistema",
        "details": details,
        "ip_address": ip_address,
        "metadata": metadata or {},
    })
    _save_logs(tenant_id, logs)


def get_logs(tenant_id: str, limit: int = 100, offset: int = 0,
             category: str = "", level: str = "", search: str = "",
             since: float = 0, until: float = 0) -> list[dict]:
    """Busca logs com filtros."""
    logs = _load_logs(tenant_id)

    if category:
        logs = [l for l in logs if l.get("category") == category]
    if level:
        logs = [l for l in logs if l.get("level") == level]
    if since:
        logs = [l for l in logs if l.get("timestamp", 0) >= since]
    if until:
        logs = [l for l in logs if l.get("timestamp", 0) <= until]
    if search:
        q = search.lower()
        logs = [l for l in logs if q in (l.get("details", "") + l.get("action", "")).lower()]

    logs.sort(key=lambda l: l.get("timestamp", 0), reverse=True)
    return logs[offset:offset + limit]


def get_log_count(tenant_id: str, category: str = "", level: str = "") -> int:
    logs = _load_logs(tenant_id)
    if category:
        logs = [l for l in logs if l.get("category") == category]
    if level:
        logs = [l for l in logs if l.get("level") == level]
    return len(logs)


def get_summary(tenant_id: str) -> dict:
    """Resumo: erros hoje, criticos semana, acoes hoje."""
    logs = _load_logs(tenant_id)
    now = time.time()
    today = now - (now % 86400)
    week = now - 7 * 86400

    errors_today = sum(1 for l in logs if l.get("level") in ("error", "critical") and l.get("timestamp", 0) >= today)
    critical_week = sum(1 for l in logs if l.get("level") == "critical" and l.get("timestamp", 0) >= week)
    actions_today = sum(1 for l in logs if l.get("timestamp", 0) >= today)

    return {
        "errors_today": errors_today,
        "critical_week": critical_week,
        "actions_today": actions_today,
    }


def get_recent_errors(tenant_id: str, limit: int = 10) -> list[dict]:
    logs = _load_logs(tenant_id)
    errors = [l for l in logs if l.get("level") in ("error", "critical")]
    errors.sort(key=lambda l: l.get("timestamp", 0), reverse=True)
    return errors[:limit]


def cleanup_old_logs(tenant_id: str, days: int = 90) -> int:
    """Remove logs antigos."""
    cutoff = time.time() - days * 86400
    logs = _load_logs(tenant_id)
    old_count = len(logs)
    logs = [l for l in logs if l.get("timestamp", 0) > cutoff]
    _save_logs(tenant_id, logs)
    return old_count - len(logs)


# ── Super Admin ──

def get_all_tenants_summary() -> list[dict]:
    """Lista todos os tenants com resumo (super admin)."""
    results = []
    if not _AUDIT_DIR.exists():
        return results
    for td in _AUDIT_DIR.iterdir():
        if not td.is_dir():
            continue
        tenant_id = td.name
        summary = get_summary(tenant_id)
        logs = _load_logs(tenant_id)
        last_activity = logs[-1].get("timestamp", 0) if logs else 0
        results.append({
            "tenant_id": tenant_id,
            "total_logs": len(logs),
            "errors_today": summary["errors_today"],
            "critical_week": summary["critical_week"],
            "last_activity": last_activity,
        })
    return results


def get_all_errors(limit: int = 50) -> list[dict]:
    """Todos os erros de todos os tenants (super admin)."""
    all_errors = []
    if not _AUDIT_DIR.exists():
        return all_errors
    for td in _AUDIT_DIR.iterdir():
        if not td.is_dir():
            continue
        errors = get_recent_errors(td.name, limit=10)
        for e in errors:
            e["tenant_id"] = td.name
        all_errors.extend(errors)
    all_errors.sort(key=lambda l: l.get("timestamp", 0), reverse=True)
    return all_errors[:limit]
