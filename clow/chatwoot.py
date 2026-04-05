"""Chatwoot CRM Integration — proxy reverso para embutir Chatwoot no Clow.

Cada tenant configura URL + credenciais do Chatwoot.
O Clow faz proxy reverso removendo X-Frame-Options para permitir iframe.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from . import config
from .logging import log_action

CRM_BASE_DIR = config.CLOW_HOME / "crm"
CRM_BASE_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class CRMConfig:
    tenant_id: str
    chatwoot_url: str = ""
    chatwoot_email: str = ""
    chatwoot_password: str = ""
    chatwoot_account_id: int = 1
    chatwoot_api_token: str = ""
    configured: bool = False
    created_at: float = field(default_factory=time.time)

    @property
    def config_dir(self) -> Path:
        d = CRM_BASE_DIR / self.tenant_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save(self) -> None:
        payload = {
            "tenant_id": self.tenant_id,
            "chatwoot_url": self.chatwoot_url,
            "chatwoot_email": self.chatwoot_email,
            "chatwoot_password": self.chatwoot_password,
            "chatwoot_account_id": self.chatwoot_account_id,
            "chatwoot_api_token": self.chatwoot_api_token,
            "configured": self.configured,
            "created_at": self.created_at,
        }
        path = self.config_dir / "crm_config.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, tenant_id: str) -> CRMConfig:
        path = CRM_BASE_DIR / tenant_id / "crm_config.json"
        if not path.exists():
            return cls(tenant_id=tenant_id)
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        except Exception:
            return cls(tenant_id=tenant_id)


def chatwoot_login(url: str, email: str, password: str) -> dict:
    """Login no Chatwoot e retorna token + cookie."""
    try:
        login_url = f"{url}/auth/sign_in"
        data = json.dumps({"email": email, "password": password}).encode()
        req = Request(login_url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        resp = urlopen(req, timeout=15)
        result = json.loads(resp.read().decode())
        if result.get("data", {}).get("access_token"):
            return {
                "success": True,
                "token": result["data"]["access_token"],
                "account_id": result["data"].get("account_id", 1),
            }
        return {"success": False, "error": "Login falhou — verifique email e senha."}
    except HTTPError as e:
        body = e.read().decode() if e.fp else ""
        return {"success": False, "error": f"Erro {e.code}: {body[:200]}"}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


def save_crm_config(tenant_id: str, url: str, email: str, password: str) -> dict:
    """Testa login e salva config."""
    url = url.rstrip("/")
    login = chatwoot_login(url, email, password)
    if not login.get("success"):
        return {"error": login.get("error", "Falha no login")}

    cfg = CRMConfig(
        tenant_id=tenant_id,
        chatwoot_url=url,
        chatwoot_email=email,
        chatwoot_password=password,
        chatwoot_account_id=login.get("account_id", 1),
        chatwoot_api_token=login["token"],
        configured=True,
    )
    cfg.save()
    log_action("crm_configured", f"tenant={tenant_id}")
    return {"success": True, "message": f"Conectado! Account ID: {cfg.chatwoot_account_id}"}


def get_crm_config(tenant_id: str) -> CRMConfig:
    return CRMConfig.load(tenant_id)
