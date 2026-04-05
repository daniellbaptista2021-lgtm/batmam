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
        "description": "Auditoria de seguranca, scan de vulnerabilidades, compliance",
        "hooks": ["secret_scanner", "dangerous_command_blocker", "change_logger"],
        "skills": ["security_audit", "vulnerability_scan", "dependency_check", "secret_rotate", "ssl_check"],
        "icon": "\U0001f512",
        "plan_required": "starter",
        "tags": ["security", "audit", "compliance"],
    },
    "git-workflow": {
        "name": "Git Workflow Pro",
        "description": "Worktrees, conventional commits, release management, changelog",
        "hooks": ["conventional_commits", "tdd_gate"],
        "skills": ["git_review", "git_changelog", "worktree_init", "worktree_deliver",
                   "branch_cleanup", "pr_review", "release_prep"],
        "icon": "\U0001f500",
        "plan_required": "byok_free",
        "tags": ["git", "workflow", "release"],
    },
    "crm-suite": {
        "name": "CRM Suite",
        "description": "Gestao avancada: lead scoring, conversion reports, customer journey",
        "hooks": [],
        "skills": ["crm_lead_management", "crm_pipeline", "crm_reports",
                   "lead_scoring", "conversion_report", "customer_journey"],
        "icon": "\U0001f4bc",
        "plan_required": "lite",
        "tags": ["crm", "leads", "vendas"],
    },
    "whatsapp-pro": {
        "name": "WhatsApp Pro",
        "description": "Analytics de conversa, sentiment analysis, respostas otimizadas",
        "hooks": [],
        "skills": ["whatsapp_analytics", "conversation_summary", "sentiment_analysis",
                   "auto_tag", "response_optimizer", "peak_hours_report"],
        "icon": "\U0001f4f1",
        "plan_required": "lite",
        "tags": ["whatsapp", "atendimento", "analytics"],
    },
    "devops": {
        "name": "DevOps Toolkit",
        "description": "Docker, deploy, CI/CD, monitoring, infra as code",
        "hooks": ["plan_gate", "scope_guard"],
        "skills": ["docker_compose_gen", "dockerfile_gen", "nginx_config",
                   "ssl_setup", "systemd_service", "backup_script", "log_analyzer"],
        "icon": "\U0001f433",
        "plan_required": "starter",
        "tags": ["devops", "docker", "deploy", "infra"],
    },
    "quality-gates": {
        "name": "Quality Gates",
        "description": "TDD, plan gate, scope guard, code review, coverage",
        "hooks": ["tdd_gate", "plan_gate", "scope_guard"],
        "skills": ["code_review", "test_coverage", "test_generator",
                   "lint_fix", "complexity_report", "dead_code_finder"],
        "icon": "\u2705",
        "plan_required": "byok_free",
        "tags": ["quality", "testing", "review"],
    },
    "content-creator": {
        "name": "Content Creator",
        "description": "Landing pages, blog posts, social media, email marketing, ad copy",
        "hooks": [],
        "skills": ["landing_page", "blog_post", "social_media", "email_sequence",
                   "product_description", "ad_copy", "seo_article", "video_script"],
        "icon": "\u270d\ufe0f",
        "plan_required": "byok_free",
        "tags": ["content", "marketing", "copy"],
    },
    "data-analytics": {
        "name": "Data Analytics",
        "description": "Analise de dados, relatorios, dashboards, ETL",
        "hooks": [],
        "skills": ["csv_analyzer", "chart_generator", "report_builder",
                   "data_cleaner", "pivot_table", "trend_analysis", "export_pdf_report"],
        "icon": "\U0001f4ca",
        "plan_required": "byok_free",
        "tags": ["data", "analytics", "report"],
    },
    "automation": {
        "name": "Automation Suite",
        "description": "Fluxos n8n, cron avancado, webhooks, integracao entre sistemas",
        "hooks": ["change_logger"],
        "skills": ["n8n_flow_gen", "cron_manager", "webhook_builder",
                   "api_connector", "scheduled_report", "data_sync"],
        "icon": "\u26a1",
        "plan_required": "starter",
        "tags": ["automation", "n8n", "cron", "webhook"],
    },
    "full-stack": {
        "name": "Full Stack Dev",
        "description": "Frontend + backend + deploy: security + git + quality + devops",
        "hooks": [
            "secret_scanner", "conventional_commits",
            "tdd_gate", "dangerous_command_blocker",
        ],
        "skills": ["react_component", "api_endpoint", "database_schema",
                   "auth_setup", "crud_generator", "form_builder"],
        "icon": "\U0001f680",
        "plan_required": "byok_free",
        "tags": ["fullstack", "frontend", "backend", "web"],
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

    def search(self, query: str) -> list[dict]:
        """Busca bundles por nome, descricao ou tag."""
        q = query.lower()
        results = []
        installed = set(self.get_installed())
        for bid, bdata in BUNDLES.items():
            tags = bdata.get("tags", [])
            if (q in bid or q in bdata["name"].lower()
                    or q in bdata["description"].lower()
                    or any(q in t for t in tags)):
                results.append({"id": bid, "installed": bid in installed, **bdata})
        return results

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
