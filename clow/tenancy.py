"""Multi-tenancy do Clow.

Permite isolar contextos por tenant (usuario/equipe/organizacao):
- Sessoes separadas por tenant
- Memoria separada por tenant
- Configuracoes por tenant
- Quotas de tokens por tenant
- Audit log por tenant

Cada tenant tem seu proprio diretorio em ~/.clow/tenants/<tenant_id>/

Configuracao em settings.json:
{
  "tenancy": {
    "enabled": true,
    "default_tenant": "default",
    "quotas": {
      "max_tokens_per_day": 1000000,
      "max_sessions": 100,
      "max_memory_entries": 500
    }
  }
}
"""

from __future__ import annotations
import json
import time
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any
from . import config
from .logging import log_action


TENANTS_DIR = config.CLOW_HOME / "tenants"
TENANTS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class TenantQuota:
    """Quotas de uso por tenant."""
    max_tokens_per_day: int = 1_000_000
    max_sessions: int = 100
    max_memory_entries: int = 500
    max_tools_per_turn: int = 30

    @classmethod
    def from_dict(cls, data: dict) -> TenantQuota:
        return cls(
            max_tokens_per_day=data.get("max_tokens_per_day", 1_000_000),
            max_sessions=data.get("max_sessions", 100),
            max_memory_entries=data.get("max_memory_entries", 500),
            max_tools_per_turn=data.get("max_tools_per_turn", 30),
        )


@dataclass
class TenantUsage:
    """Uso atual de um tenant."""
    tokens_today: int = 0
    sessions_count: int = 0
    memory_count: int = 0
    last_reset: float = 0.0

    def reset_if_new_day(self) -> None:
        """Reseta contadores se mudou o dia."""
        today = time.strftime("%Y-%m-%d")
        last_day = time.strftime("%Y-%m-%d", time.localtime(self.last_reset)) if self.last_reset else ""
        if today != last_day:
            self.tokens_today = 0
            self.last_reset = time.time()

    def to_dict(self) -> dict:
        return {
            "tokens_today": self.tokens_today,
            "sessions_count": self.sessions_count,
            "memory_count": self.memory_count,
            "last_reset": self.last_reset,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TenantUsage:
        return cls(
            tokens_today=data.get("tokens_today", 0),
            sessions_count=data.get("sessions_count", 0),
            memory_count=data.get("memory_count", 0),
            last_reset=data.get("last_reset", 0.0),
        )


@dataclass
class Tenant:
    """Representacao de um tenant."""
    id: str
    name: str = ""
    created_at: float = 0.0
    quota: TenantQuota = field(default_factory=TenantQuota)
    usage: TenantUsage = field(default_factory=TenantUsage)
    settings: dict = field(default_factory=dict)
    active: bool = True

    @property
    def base_dir(self) -> Path:
        return TENANTS_DIR / self.id

    @property
    def sessions_dir(self) -> Path:
        return self.base_dir / "sessions"

    @property
    def memory_dir(self) -> Path:
        return self.base_dir / "memory"

    @property
    def logs_dir(self) -> Path:
        return self.base_dir / "logs"

    def ensure_dirs(self) -> None:
        """Cria diretorios do tenant se necessario."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(exist_ok=True)
        self.memory_dir.mkdir(exist_ok=True)
        self.logs_dir.mkdir(exist_ok=True)

    def check_quota(self, tokens: int = 0) -> tuple[bool, str]:
        """Verifica se o tenant esta dentro das quotas.

        Retorna (permitido, motivo).
        """
        self.usage.reset_if_new_day()

        if not self.active:
            return False, "Tenant desativado"

        if self.usage.tokens_today + tokens > self.quota.max_tokens_per_day:
            return False, f"Quota de tokens excedida ({self.usage.tokens_today:,}/{self.quota.max_tokens_per_day:,} tokens/dia)"

        if self.usage.sessions_count > self.quota.max_sessions:
            return False, f"Quota de sessoes excedida ({self.usage.sessions_count}/{self.quota.max_sessions})"

        if self.usage.memory_count > self.quota.max_memory_entries:
            return False, f"Quota de memorias excedida ({self.usage.memory_count}/{self.quota.max_memory_entries})"

        return True, "OK"

    def add_tokens(self, count: int) -> None:
        """Registra uso de tokens."""
        self.usage.reset_if_new_day()
        self.usage.tokens_today += count
        self._save_usage()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "quota": {
                "max_tokens_per_day": self.quota.max_tokens_per_day,
                "max_sessions": self.quota.max_sessions,
                "max_memory_entries": self.quota.max_memory_entries,
            },
            "active": self.active,
            "settings": self.settings,
        }

    def _save_usage(self) -> None:
        """Persiste uso do tenant."""
        usage_file = self.base_dir / "usage.json"
        try:
            with open(usage_file, "w") as f:
                json.dump(self.usage.to_dict(), f)
        except OSError:
            pass


class TenantManager:
    """Gerencia tenants do Clow."""

    def __init__(self) -> None:
        self._tenants: dict[str, Tenant] = {}
        self._current_tenant_id: str = "default"

    def load_from_settings(self) -> None:
        """Carrega configuracao de tenancy do settings."""
        settings = config.load_settings()
        tenancy = settings.get("tenancy", {})

        if not tenancy.get("enabled", False):
            self._ensure_default_tenant()
            return

        self._current_tenant_id = tenancy.get("default_tenant", "default")
        default_quota = TenantQuota.from_dict(tenancy.get("quotas", {}))

        # Carrega tenants existentes do disco
        for tenant_dir in TENANTS_DIR.iterdir():
            if tenant_dir.is_dir():
                self._load_tenant(tenant_dir.name, default_quota)

        self._ensure_default_tenant(default_quota)

    def _ensure_default_tenant(self, quota: TenantQuota | None = None) -> None:
        if "default" not in self._tenants:
            t = Tenant(id="default", name="Default", created_at=time.time(), quota=quota or TenantQuota())
            t.ensure_dirs()
            self._tenants["default"] = t
            self._save_tenant(t)

    def _load_tenant(self, tenant_id: str, default_quota: TenantQuota) -> None:
        """Carrega um tenant do disco."""
        tenant_file = TENANTS_DIR / tenant_id / "tenant.json"
        usage_file = TENANTS_DIR / tenant_id / "usage.json"

        tenant = Tenant(id=tenant_id, quota=default_quota)

        if tenant_file.exists():
            try:
                with open(tenant_file) as f:
                    data = json.load(f)
                tenant.name = data.get("name", tenant_id)
                tenant.created_at = data.get("created_at", 0)
                tenant.active = data.get("active", True)
                tenant.settings = data.get("settings", {})
                if "quota" in data:
                    tenant.quota = TenantQuota.from_dict(data["quota"])
            except (json.JSONDecodeError, OSError):
                pass

        if usage_file.exists():
            try:
                with open(usage_file) as f:
                    tenant.usage = TenantUsage.from_dict(json.load(f))
            except (json.JSONDecodeError, OSError):
                pass

        tenant.ensure_dirs()
        self._tenants[tenant_id] = tenant

    def create_tenant(self, tenant_id: str, name: str = "", quota: TenantQuota | None = None) -> Tenant:
        """Cria um novo tenant."""
        if tenant_id in self._tenants:
            return self._tenants[tenant_id]

        tenant = Tenant(
            id=tenant_id,
            name=name or tenant_id,
            created_at=time.time(),
            quota=quota or TenantQuota(),
        )
        tenant.ensure_dirs()
        self._tenants[tenant_id] = tenant
        self._save_tenant(tenant)
        log_action("tenant_created", tenant_id)
        return tenant

    def get_tenant(self, tenant_id: str | None = None) -> Tenant:
        """Retorna tenant por ID ou o tenant atual."""
        tid = tenant_id or self._current_tenant_id
        if tid not in self._tenants:
            return self.create_tenant(tid)
        return self._tenants[tid]

    def set_current(self, tenant_id: str) -> None:
        """Define o tenant atual."""
        self._current_tenant_id = tenant_id

    @property
    def current(self) -> Tenant:
        """Retorna o tenant atual."""
        return self.get_tenant()

    def list_tenants(self) -> list[dict]:
        """Lista todos os tenants."""
        result = []
        for t in self._tenants.values():
            t.usage.reset_if_new_day()
            result.append({
                "id": t.id,
                "name": t.name,
                "active": t.active,
                "tokens_today": t.usage.tokens_today,
                "quota_tokens": t.quota.max_tokens_per_day,
                "sessions": t.usage.sessions_count,
            })
        return result

    def delete_tenant(self, tenant_id: str) -> bool:
        """Desativa um tenant (nao deleta dados)."""
        if tenant_id == "default":
            return False
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return False
        tenant.active = False
        self._save_tenant(tenant)
        log_action("tenant_deactivated", tenant_id)
        return True

    def _save_tenant(self, tenant: Tenant) -> None:
        """Persiste configuracao do tenant."""
        tenant_file = tenant.base_dir / "tenant.json"
        try:
            with open(tenant_file, "w") as f:
                json.dump(tenant.to_dict(), f, indent=2)
        except OSError:
            pass


# Instancia global
_tenant_manager: TenantManager | None = None


def get_tenant_manager() -> TenantManager:
    """Retorna o tenant manager global (singleton)."""
    global _tenant_manager
    if _tenant_manager is None:
        _tenant_manager = TenantManager()
        _tenant_manager.load_from_settings()
    return _tenant_manager
