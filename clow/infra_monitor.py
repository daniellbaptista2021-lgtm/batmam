"""Infra Monitor — monitora saude do Chatwoot dos clientes.

Ping a cada 5 minutos. Se cair, alerta via WhatsApp.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from . import config
from .logging import log_action

_MONITOR_DIR = config.CLOW_HOME / "infra_monitor"
_MONITOR_DIR.mkdir(parents=True, exist_ok=True)

CHECK_INTERVAL = 300  # 5 minutos


def _tenant_dir(tenant_id: str) -> Path:
    d = _MONITOR_DIR / tenant_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_monitor_config(tenant_id: str) -> dict:
    """Config de alertas do tenant."""
    path = _tenant_dir(tenant_id) / "config.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"alerts_enabled": True, "alert_phone": "", "alert_email": ""}


def save_monitor_config(tenant_id: str, cfg: dict) -> None:
    path = _tenant_dir(tenant_id) / "config.json"
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_checks(tenant_id: str) -> list[dict]:
    path = _tenant_dir(tenant_id) / "checks.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_checks(tenant_id: str, checks: list[dict]) -> None:
    # Manter ultimos 200 checks
    if len(checks) > 200:
        checks = checks[-200:]
    path = _tenant_dir(tenant_id) / "checks.json"
    path.write_text(json.dumps(checks, ensure_ascii=False), encoding="utf-8")


def check_health(tenant_id: str) -> dict:
    """Verifica se o Chatwoot do cliente esta acessivel."""
    from .infra_setup import get_tenant_infra
    infra = get_tenant_infra(tenant_id)
    if not infra:
        return {"status": "not_configured", "response_time_ms": 0}

    url = infra.get("chatwoot_url", "").rstrip("/")
    if not url:
        return {"status": "not_configured", "response_time_ms": 0}

    start = time.time()
    try:
        req = Request(f"{url}/auth/sign_in", method="HEAD")
        urlopen(req, timeout=10)
        elapsed = int((time.time() - start) * 1000)
        result = {
            "status": "online",
            "response_time_ms": elapsed,
            "last_check": time.time(),
            "chatwoot_url": url,
        }
    except (HTTPError, URLError, Exception) as e:
        elapsed = int((time.time() - start) * 1000)
        result = {
            "status": "offline",
            "response_time_ms": elapsed,
            "last_check": time.time(),
            "error": str(e)[:100],
            "chatwoot_url": url,
        }

    # Salva check
    checks = _load_checks(tenant_id)
    checks.append(result)
    _save_checks(tenant_id, checks)

    # Conta falhas consecutivas
    consecutive = 0
    for c in reversed(checks):
        if c.get("status") == "offline":
            consecutive += 1
        else:
            break
    result["consecutive_failures"] = consecutive

    return result


def get_health_history(tenant_id: str, limit: int = 50) -> list[dict]:
    """Retorna historico de health checks."""
    checks = _load_checks(tenant_id)
    return checks[-limit:]


def get_uptime(tenant_id: str, days: int = 30) -> float:
    """Calcula uptime percentual."""
    checks = _load_checks(tenant_id)
    cutoff = time.time() - days * 86400
    recent = [c for c in checks if c.get("last_check", 0) > cutoff]
    if not recent:
        return 100.0
    online = sum(1 for c in recent if c.get("status") == "online")
    return round(online / len(recent) * 100, 1)


def handle_down(tenant_id: str, consecutive_failures: int) -> None:
    """Acoes quando Chatwoot esta offline."""
    cfg = get_monitor_config(tenant_id)
    if not cfg.get("alerts_enabled"):
        return

    phone = cfg.get("alert_phone", "")
    if not phone:
        return

    # So alerta na 3a falha (15 min) e a cada 6 falhas (30 min)
    if consecutive_failures == 3 or (consecutive_failures > 3 and consecutive_failures % 6 == 0):
        msg = f"⚠️ ALERTA CLOW: Seu servidor de atendimento esta offline ha {consecutive_failures * 5} minutos. Seus clientes podem nao estar recebendo resposta. Verifique sua VPS."

        # Envia via primeira instancia WhatsApp do tenant
        try:
            from .whatsapp_agent import get_wa_manager
            manager = get_wa_manager()
            instances = manager.get_instances(tenant_id)
            if instances:
                inst = manager.get_instance(instances[0]["id"], tenant_id)
                if inst:
                    manager._send_zapi(inst, phone, msg)
                    log_action("infra_alert_sent", f"tenant={tenant_id} failures={consecutive_failures}")
        except Exception:
            pass


def handle_recovery(tenant_id: str, downtime_minutes: int) -> None:
    """Quando o Chatwoot volta ao ar."""
    cfg = get_monitor_config(tenant_id)
    phone = cfg.get("alert_phone", "")
    if not phone or not cfg.get("alerts_enabled"):
        return

    if downtime_minutes >= 15:  # So notifica se ficou offline 15+ min
        msg = f"✅ Seu servidor voltou ao ar! Tempo offline: {downtime_minutes} minutos."
        try:
            from .whatsapp_agent import get_wa_manager
            manager = get_wa_manager()
            instances = manager.get_instances(tenant_id)
            if instances:
                inst = manager.get_instance(instances[0]["id"], tenant_id)
                if inst:
                    manager._send_zapi(inst, phone, msg)
                    log_action("infra_recovery_sent", f"tenant={tenant_id}")
        except Exception:
            pass


def run_health_checks() -> None:
    """Chamado pelo cron a cada 5 minutos."""
    from .infra_setup import get_tenant_infra
    if not _MONITOR_DIR.exists():
        return

    # Busca todos os tenants com infra configurada
    tenants_dir = config.CLOW_HOME / "tenants"
    if not tenants_dir.exists():
        return

    for td in tenants_dir.iterdir():
        if not td.is_dir():
            continue
        tenant_id = td.name
        infra = get_tenant_infra(tenant_id)
        if not infra:
            continue

        result = check_health(tenant_id)
        consecutive = result.get("consecutive_failures", 0)

        if result.get("status") == "offline":
            handle_down(tenant_id, consecutive)
        elif consecutive == 0:
            # Verifica se acabou de recuperar
            checks = _load_checks(tenant_id)
            if len(checks) >= 2 and checks[-2].get("status") == "offline":
                # Calcula downtime
                first_down = None
                for c in reversed(checks[:-1]):
                    if c.get("status") == "online":
                        break
                    first_down = c.get("last_check", 0)
                if first_down:
                    downtime = int((time.time() - first_down) / 60)
                    handle_recovery(tenant_id, downtime)
