"""Plugin Bundles — pacotes de skills/tools/hooks agrupados por dominio.

Cada bundle agrupa componentes relacionados em um pacote instalavel.
Hooks sao ativados/desativados no settings.json; skills sao registradas
no registry interno do Clow.

Usage:
    from clow.plugin_bundles import BundleManager

    mgr = BundleManager()
    mgr.install_bundle("security-pro")
    mgr.list_bundles()
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bundle definitions
# ---------------------------------------------------------------------------

BUNDLES: dict[str, dict[str, Any]] = {
    "security-pro": {
        "name": "Security Pro",
        "description": "Ferramentas de seguranca: secret scanner, command blocker, audit",
        "hooks": ["secret_scanner", "dangerous_command_blocker", "change_logger"],
        "skills": ["security_audit", "vulnerability_scan"],
        "icon": "\U0001f512",  # lock
    },
    "git-workflow": {
        "name": "Git Workflow",
        "description": "Automacao Git: conventional commits, worktrees, branch management",
        "hooks": ["conventional_commits", "tdd_gate"],
        "skills": ["git_review", "git_changelog"],
        "icon": "\U0001f500",  # twisted arrows
    },
    "crm-suite": {
        "name": "CRM Suite",
        "description": "CRM completo: leads, funil, WhatsApp, email campaigns",
        "hooks": [],
        "skills": ["crm_lead_management", "crm_pipeline", "crm_reports"],
        "icon": "\U0001f4ca",  # bar chart
    },
    "whatsapp-pro": {
        "name": "WhatsApp Pro",
        "description": "WhatsApp avancado: multi-instancia, A/B testing, RAG docs",
        "hooks": [],
        "skills": ["whatsapp_setup", "whatsapp_templates", "whatsapp_analytics"],
        "icon": "\U0001f4ac",  # speech balloon
    },
    "devops": {
        "name": "DevOps",
        "description": "CI/CD, deploy, monitoring, infraestrutura",
        "hooks": ["plan_gate", "scope_guard"],
        "skills": ["docker_setup", "nginx_config", "systemd_service"],
        "icon": "\U0001f680",  # rocket
    },
    "quality-gates": {
        "name": "Quality Gates",
        "description": "TDD gate, plan gate, scope guard, code review",
        "hooks": ["tdd_gate", "plan_gate", "scope_guard"],
        "skills": ["code_review", "test_coverage"],
        "icon": "\u2705",  # check mark
    },
    "content-creator": {
        "name": "Content Creator",
        "description": "Landing pages, blog posts, social media, email marketing",
        "hooks": [],
        "skills": ["landing_page", "blog_post", "social_media", "email_sequence"],
        "icon": "\u270d\ufe0f",  # writing hand
    },
    "data-analytics": {
        "name": "Data Analytics",
        "description": "Planilhas, dashboards, relatorios, metricas",
        "hooks": [],
        "skills": ["spreadsheet", "dashboard", "report", "kpi_tracker"],
        "icon": "\U0001f4c8",  # chart increasing
    },
    "automation": {
        "name": "Automation",
        "description": "n8n workflows, cron jobs, webhooks, integracoes",
        "hooks": ["change_logger"],
        "skills": ["n8n_workflow", "webhook_setup", "cron_scheduler"],
        "icon": "\u26a1",  # lightning
    },
    "full-stack": {
        "name": "Full Stack",
        "description": "Pacote completo: security + git + quality + devops",
        "hooks": [
            "secret_scanner",
            "conventional_commits",
            "tdd_gate",
            "dangerous_command_blocker",
        ],
        "skills": [],
        "icon": "\U0001f3d7\ufe0f",  # building construction
    },
}


# ---------------------------------------------------------------------------
# BundleManager
# ---------------------------------------------------------------------------

class BundleManager:
    """Gerencia instalacao e configuracao de bundles.

    Persists installed state in the project settings file
    (``.clow/settings.json`` under key ``installed_bundles``).
    Hooks are toggled inside the ``hooks`` dict of the same file.
    """

    def __init__(self, project_dir: str | Path | None = None) -> None:
        if project_dir is None:
            project_dir = Path.cwd()
        self._project_dir = Path(project_dir)
        self._settings_path = self._project_dir / ".clow" / "settings.json"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_bundles(self) -> list[dict]:
        """Lista todos os bundles disponiveis com status de instalacao."""
        installed = set(self.get_installed())
        result: list[dict] = []
        for bid, bdata in BUNDLES.items():
            entry = {
                "id": bid,
                "installed": bid in installed,
                **bdata,
            }
            result.append(entry)
        return result

    def get_bundle(self, bundle_id: str) -> dict | None:
        """Retorna detalhes de um bundle, ou None se nao existe."""
        bdata = BUNDLES.get(bundle_id)
        if bdata is None:
            return None
        installed = set(self.get_installed())
        return {"id": bundle_id, "installed": bundle_id in installed, **bdata}

    def install_bundle(self, bundle_id: str) -> dict:
        """Instala um bundle: ativa hooks e registra skills.

        Returns:
            dict com bundle_id, hooks_activated, skills_registered, status.
        """
        bdata = BUNDLES.get(bundle_id)
        if bdata is None:
            return {"bundle_id": bundle_id, "status": "not_found"}

        settings = self._load_settings()

        # Track installed bundles
        installed: list[str] = settings.get("installed_bundles", [])
        if bundle_id not in installed:
            installed.append(bundle_id)
        settings["installed_bundles"] = installed

        # Activate hooks
        hooks_section: dict = settings.get("hooks", {})
        hooks_activated: list[str] = []
        for hook_name in bdata.get("hooks", []):
            if not hooks_section.get(hook_name, {}).get("enabled", False):
                hooks_section[hook_name] = {"enabled": True}
                hooks_activated.append(hook_name)
        settings["hooks"] = hooks_section

        # Register skills
        skills_section: list[str] = settings.get("registered_skills", [])
        skills_registered: list[str] = []
        for skill_name in bdata.get("skills", []):
            if skill_name not in skills_section:
                skills_section.append(skill_name)
                skills_registered.append(skill_name)
        settings["registered_skills"] = skills_section

        self._save_settings(settings)
        logger.info("Bundle '%s' installed: hooks=%s skills=%s", bundle_id, hooks_activated, skills_registered)

        return {
            "bundle_id": bundle_id,
            "hooks_activated": hooks_activated,
            "skills_registered": skills_registered,
            "status": "installed",
        }

    def uninstall_bundle(self, bundle_id: str) -> dict:
        """Remove hooks e skills de um bundle.

        Returns:
            dict com bundle_id, hooks_deactivated, skills_removed, status.
        """
        bdata = BUNDLES.get(bundle_id)
        if bdata is None:
            return {"bundle_id": bundle_id, "status": "not_found"}

        settings = self._load_settings()

        # Remove from installed list
        installed: list[str] = settings.get("installed_bundles", [])
        if bundle_id in installed:
            installed.remove(bundle_id)
        settings["installed_bundles"] = installed

        # Collect hooks still needed by other installed bundles
        hooks_in_use: set[str] = set()
        for other_id in installed:
            other = BUNDLES.get(other_id, {})
            for h in other.get("hooks", []):
                hooks_in_use.add(h)

        # Deactivate hooks that are no longer needed
        hooks_section: dict = settings.get("hooks", {})
        hooks_deactivated: list[str] = []
        for hook_name in bdata.get("hooks", []):
            if hook_name not in hooks_in_use and hook_name in hooks_section:
                hooks_section[hook_name] = {"enabled": False}
                hooks_deactivated.append(hook_name)
        settings["hooks"] = hooks_section

        # Remove skills not used by other bundles
        skills_in_use: set[str] = set()
        for other_id in installed:
            other = BUNDLES.get(other_id, {})
            for s in other.get("skills", []):
                skills_in_use.add(s)

        skills_section: list[str] = settings.get("registered_skills", [])
        skills_removed: list[str] = []
        for skill_name in bdata.get("skills", []):
            if skill_name not in skills_in_use and skill_name in skills_section:
                skills_section.remove(skill_name)
                skills_removed.append(skill_name)
        settings["registered_skills"] = skills_section

        self._save_settings(settings)
        logger.info("Bundle '%s' uninstalled: hooks=%s skills=%s", bundle_id, hooks_deactivated, skills_removed)

        return {
            "bundle_id": bundle_id,
            "hooks_deactivated": hooks_deactivated,
            "skills_removed": skills_removed,
            "status": "uninstalled",
        }

    def get_installed(self) -> list[str]:
        """Retorna lista de bundle IDs atualmente instalados."""
        settings = self._load_settings()
        return list(settings.get("installed_bundles", []))

    def install_hook(self, hook_name: str) -> bool:
        """Ativa um hook builtin no settings.json.

        Returns:
            True se o hook foi ativado, False se ja estava ativo.
        """
        settings = self._load_settings()
        hooks_section: dict = settings.get("hooks", {})
        if hooks_section.get(hook_name, {}).get("enabled", False):
            return False
        hooks_section[hook_name] = {"enabled": True}
        settings["hooks"] = hooks_section
        self._save_settings(settings)
        logger.info("Hook '%s' activated.", hook_name)
        return True

    def uninstall_hook(self, hook_name: str) -> bool:
        """Desativa um hook do settings.json.

        Returns:
            True se o hook foi desativado, False se ja estava inativo.
        """
        settings = self._load_settings()
        hooks_section: dict = settings.get("hooks", {})
        if not hooks_section.get(hook_name, {}).get("enabled", False):
            return False
        hooks_section[hook_name] = {"enabled": False}
        settings["hooks"] = hooks_section
        self._save_settings(settings)
        logger.info("Hook '%s' deactivated.", hook_name)
        return True

    # ------------------------------------------------------------------
    # Settings persistence
    # ------------------------------------------------------------------

    def _load_settings(self) -> dict:
        """Load project settings from .clow/settings.json."""
        if self._settings_path.exists():
            try:
                return json.loads(self._settings_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save_settings(self, settings: dict) -> None:
        """Save project settings to .clow/settings.json."""
        self._settings_path.parent.mkdir(parents=True, exist_ok=True)
        self._settings_path.write_text(
            json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
