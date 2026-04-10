"""Clow Health Check — verifica integridade completa do sistema.

Uso:
    from clow.health_check import run_health_check
    results = run_health_check()
    # results = {"checks": [...], "passed": N, "failed": N, "warnings": N}
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import shutil
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class CheckResult:
    name: str
    status: str  # "pass", "fail", "warn", "skip"
    message: str = ""
    details: str = ""


def run_health_check() -> dict:
    """Roda todos os health checks e retorna resultado consolidado."""
    checks: list[CheckResult] = []

    checks.append(_check_python_version())
    checks.append(_check_required_packages())
    checks.append(_check_api_key())
    checks.append(_check_database())
    checks.append(_check_migrations())
    checks.append(_check_settings_file())
    checks.append(_check_stripe())
    checks.append(_check_disk_space())
    checks.append(_check_clow_home())
    checks.append(_check_permissions())

    passed = sum(1 for c in checks if c.status == "pass")
    failed = sum(1 for c in checks if c.status == "fail")
    warnings = sum(1 for c in checks if c.status == "warn")
    skipped = sum(1 for c in checks if c.status == "skip")

    return {
        "checks": [{"name": c.name, "status": c.status, "message": c.message, "details": c.details} for c in checks],
        "passed": passed,
        "failed": failed,
        "warnings": warnings,
        "skipped": skipped,
        "total": len(checks),
        "healthy": failed == 0,
    }


def format_health_report(results: dict) -> str:
    """Formata resultado do health check para exibicao no terminal."""
    lines = ["", "  Clow Health Check", "  " + "=" * 40, ""]

    for check in results["checks"]:
        icon = {"pass": "✅", "fail": "❌", "warn": "⚠️", "skip": "⏭️"}.get(check["status"], "?")
        lines.append(f"  {icon} {check['name']}: {check['message']}")
        if check["details"]:
            lines.append(f"     {check['details']}")

    lines.append("")
    lines.append(f"  Resultado: {results['passed']} passed, {results['failed']} failed, {results['warnings']} warnings")
    if results["healthy"]:
        lines.append("  ✅ Sistema saudavel!")
    else:
        lines.append("  ❌ Problemas encontrados — corrija os itens acima.")
    lines.append("")
    return "\n".join(lines)


# ── Individual checks ──────────────────────────────────────────

def _check_python_version() -> CheckResult:
    v = sys.version_info
    version_str = f"{v.major}.{v.minor}.{v.micro}"
    if v >= (3, 10):
        return CheckResult("Python", "pass", f"v{version_str}")
    return CheckResult("Python", "fail", f"v{version_str} (requer 3.10+)")


def _check_required_packages() -> CheckResult:
    required = ["openai", "fastapi", "uvicorn", "dotenv"]
    missing = []
    for pkg in required:
        pkg_import = "dotenv" if pkg == "dotenv" else pkg
        try:
            importlib.import_module(pkg_import)
        except ImportError:
            missing.append(pkg)

    if not missing:
        return CheckResult("Pacotes", "pass", f"{len(required)} pacotes OK")
    return CheckResult("Pacotes", "fail", f"Faltando: {', '.join(missing)}",
                       "pip install " + " ".join(missing))


def _check_api_key() -> CheckResult:
    from . import config
    key = config.DEEPSEEK_API_KEY
    if not key:
        return CheckResult("API Key", "fail", "Nenhuma API key configurada",
                           "Defina DEEPSEEK_API_KEY no .env")
    return CheckResult("API Key", "pass", f"DeepSeek configurada ({key[:8]}...)")


def _check_database() -> CheckResult:
    try:
        from .database import DB_PATH, get_db
        if not DB_PATH.exists():
            return CheckResult("Database", "fail", "Arquivo nao encontrado",
                               str(DB_PATH))
        with get_db() as db:
            tables = db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = [r["name"] for r in tables]

        required_tables = ["users", "usage_log", "conversations", "messages"]
        missing = [t for t in required_tables if t not in table_names]
        if missing:
            return CheckResult("Database", "fail",
                               f"Tabelas faltando: {', '.join(missing)}")

        return CheckResult("Database", "pass",
                           f"{len(table_names)} tabelas, WAL mode",
                           str(DB_PATH))
    except Exception as e:
        return CheckResult("Database", "fail", f"Erro: {e}")


def _check_migrations() -> CheckResult:
    try:
        from .migrations import current_version, MIGRATIONS
        cv = current_version()
        latest = max(m[0] for m in MIGRATIONS) if MIGRATIONS else 0
        if cv >= latest:
            return CheckResult("Migrations", "pass", f"v{cv} (atualizado)")
        return CheckResult("Migrations", "warn",
                           f"v{cv} de {latest} — rode run_migrations()",
                           f"{latest - cv} migration(s) pendente(s)")
    except Exception as e:
        return CheckResult("Migrations", "warn", f"Erro ao verificar: {e}")


def _check_settings_file() -> CheckResult:
    from . import config
    if not config.CONFIG_FILE.exists():
        return CheckResult("Settings", "warn", "settings.json nao existe (usando defaults)")
    try:
        with open(config.CONFIG_FILE) as f:
            data = json.load(f)
        keys = len(data)
        return CheckResult("Settings", "pass", f"Valido, {keys} chaves")
    except json.JSONDecodeError as e:
        return CheckResult("Settings", "fail", f"JSON invalido: {e}",
                           str(config.CONFIG_FILE))
    except OSError as e:
        return CheckResult("Settings", "fail", f"Erro ao ler: {e}")


def _check_stripe() -> CheckResult:
    from . import config
    if not config.STRIPE_SECRET_KEY:
        return CheckResult("Stripe", "skip", "Nao configurado (opcional)")
    if config.STRIPE_SECRET_KEY.startswith("sk_"):
        mode = "live" if "live" in config.STRIPE_SECRET_KEY else "test"
        has_webhook = bool(config.STRIPE_WEBHOOK_SECRET)
        prices = sum(1 for x in [
            config.STRIPE_LITE_PRICE_ID, config.STRIPE_STARTER_PRICE_ID,
            config.STRIPE_PRO_PRICE_ID, config.STRIPE_BUSINESS_PRICE_ID,
        ] if x)
        return CheckResult("Stripe", "pass",
                           f"Modo {mode}, {prices} precos, webhook={'sim' if has_webhook else 'nao'}")
    return CheckResult("Stripe", "warn", "Key com formato incomum")


def _check_disk_space() -> CheckResult:
    try:
        from . import config
        usage = shutil.disk_usage(str(config.CLOW_HOME))
        free_gb = usage.free / (1024 ** 3)
        total_gb = usage.total / (1024 ** 3)
        pct_free = (usage.free / usage.total) * 100

        if free_gb < 1:
            return CheckResult("Disco", "fail",
                               f"{free_gb:.1f}GB livre de {total_gb:.0f}GB ({pct_free:.0f}%)")
        if free_gb < 5:
            return CheckResult("Disco", "warn",
                               f"{free_gb:.1f}GB livre de {total_gb:.0f}GB ({pct_free:.0f}%)")
        return CheckResult("Disco", "pass",
                           f"{free_gb:.1f}GB livre de {total_gb:.0f}GB ({pct_free:.0f}%)")
    except Exception as e:
        return CheckResult("Disco", "warn", f"Erro ao verificar: {e}")


def _check_clow_home() -> CheckResult:
    from . import config
    dirs = ["sessions", "memory", "credentials"]
    missing = [d for d in dirs if not (config.CLOW_HOME / d).is_dir()]
    if missing:
        return CheckResult("Clow Home", "warn",
                           f"Dirs faltando: {', '.join(missing)}",
                           str(config.CLOW_HOME))
    return CheckResult("Clow Home", "pass", str(config.CLOW_HOME))


def _check_permissions() -> CheckResult:
    try:
        from .permissions import get_current_level, PermissionLevel
        level = get_current_level()
        name = level.name
        return CheckResult("Permissoes", "pass", f"Nivel: {name}")
    except Exception as e:
        return CheckResult("Permissoes", "warn", f"Erro: {e}")
