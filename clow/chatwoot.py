"""Chatwoot CRM Integration — API client for Clow CRM.

Cada tenant configura suas credenciais Chatwoot.
O Clow consome a API REST do Chatwoot e apresenta como CRM proprio.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from . import config
from .logging import log_action

CRM_BASE_DIR = config.CLOW_HOME / "crm"
CRM_BASE_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Configuration per tenant
# ---------------------------------------------------------------------------

@dataclass
class CRMConfig:
    tenant_id: str
    chatwoot_url: str = ""            # e.g. http://localhost:3000
    chatwoot_api_token: str = ""
    chatwoot_account_id: int = 1
    configured: bool = False
    created_at: float = field(default_factory=time.time)

    # -- paths --------------------------------------------------------------

    @property
    def config_dir(self) -> Path:
        d = CRM_BASE_DIR / self.tenant_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    # -- persistence --------------------------------------------------------

    def save(self) -> None:
        """Persist config to *config_dir*/crm_config.json."""
        payload = {
            "tenant_id": self.tenant_id,
            "chatwoot_url": self.chatwoot_url,
            "chatwoot_api_token": self.chatwoot_api_token,
            "chatwoot_account_id": self.chatwoot_account_id,
            "configured": self.configured,
            "created_at": self.created_at,
        }
        path = self.config_dir / "crm_config.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, tenant_id: str) -> CRMConfig:
        """Load from file; return an unconfigured default when the file is
        missing or unreadable."""
        path = CRM_BASE_DIR / tenant_id / "crm_config.json"
        if not path.exists():
            return cls(tenant_id=tenant_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                tenant_id=data.get("tenant_id", tenant_id),
                chatwoot_url=data.get("chatwoot_url", ""),
                chatwoot_api_token=data.get("chatwoot_api_token", ""),
                chatwoot_account_id=data.get("chatwoot_account_id", 1),
                configured=data.get("configured", False),
                created_at=data.get("created_at", 0.0),
            )
        except (json.JSONDecodeError, OSError):
            return cls(tenant_id=tenant_id)

    # -- serialisation ------------------------------------------------------

    def to_dict(self) -> dict:
        """Return a safe dict — the API token is masked."""
        token = self.chatwoot_api_token
        masked = (token[:4] + "****" + token[-4:]) if len(token) > 8 else "****"
        return {
            "tenant_id": self.tenant_id,
            "chatwoot_url": self.chatwoot_url,
            "chatwoot_api_token": masked,
            "chatwoot_account_id": self.chatwoot_account_id,
            "configured": self.configured,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Chatwoot REST client
# ---------------------------------------------------------------------------

class ChatwootClient:
    """Thin wrapper around Chatwoot REST API v1."""

    def __init__(self, cfg: CRMConfig):
        self.cfg = cfg
        self.base = f"{cfg.chatwoot_url}/api/v1/accounts/{cfg.chatwoot_account_id}"
        self.headers = {
            "Content-Type": "application/json",
            "api_access_token": cfg.chatwoot_api_token,
        }

    # -- low-level ----------------------------------------------------------

    def _request(self, method: str, path: str, data: dict | None = None) -> dict:
        """Make HTTP request to Chatwoot API.  Return parsed JSON."""
        url = f"{self.base}{path}"
        body = json.dumps(data).encode() if data else None
        req = Request(url, data=body, headers=self.headers, method=method)
        try:
            resp = urlopen(req, timeout=15)
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
        except HTTPError as e:
            error_body = e.read().decode() if e.fp else ""
            log_action(
                "crm_api_error",
                f"{method} {path} -> {e.code}: {error_body[:200]}",
                level="error",
            )
            return {"error": f"Chatwoot API error: {e.code}", "details": error_body[:200]}
        except (URLError, OSError, Exception) as e:
            log_action(
                "crm_api_error",
                f"{method} {path} -> {str(e)[:200]}",
                level="error",
            )
            return {"error": str(e)[:200]}

    # ── Contacts ──────────────────────────────────────────────────────────

    def list_contacts(self, page: int = 1, query: str = "") -> dict:
        """List or search contacts."""
        if query:
            path = f"/contacts/search?q={query}&page={page}"
        else:
            path = f"/contacts?page={page}"
        return self._request("GET", path)

    def get_contact(self, contact_id: int) -> dict:
        """Get a single contact by id."""
        return self._request("GET", f"/contacts/{contact_id}")

    def create_contact(
        self,
        name: str,
        phone: str = "",
        email: str = "",
        custom_attrs: dict | None = None,
    ) -> dict:
        """Create a new contact."""
        data: dict[str, Any] = {"name": name}
        if phone:
            data["phone_number"] = phone
        if email:
            data["email"] = email
        if custom_attrs:
            data["custom_attributes"] = custom_attrs
        return self._request("POST", "/contacts", data)

    def update_contact(self, contact_id: int, **kwargs: Any) -> dict:
        """Update an existing contact with arbitrary fields."""
        return self._request("PUT", f"/contacts/{contact_id}", kwargs)

    def delete_contact(self, contact_id: int) -> dict:
        """Delete a contact."""
        return self._request("DELETE", f"/contacts/{contact_id}")

    # ── Conversations ─────────────────────────────────────────────────────

    def list_conversations(
        self,
        status: str = "open",
        page: int = 1,
        inbox_id: int | None = None,
    ) -> dict:
        """List conversations filtered by status (open/resolved/pending)."""
        path = f"/conversations?status={status}&page={page}"
        if inbox_id is not None:
            path += f"&inbox_id={inbox_id}"
        return self._request("GET", path)

    def get_conversation(self, conv_id: int) -> dict:
        """Get a single conversation."""
        return self._request("GET", f"/conversations/{conv_id}")

    def get_messages(self, conv_id: int) -> dict:
        """Get messages for a conversation."""
        return self._request("GET", f"/conversations/{conv_id}/messages")

    def send_message(
        self,
        conv_id: int,
        content: str,
        message_type: str = "outgoing",
        private: bool = False,
    ) -> dict:
        """Send a message to a conversation."""
        return self._request(
            "POST",
            f"/conversations/{conv_id}/messages",
            {"content": content, "message_type": message_type, "private": private},
        )

    def toggle_status(self, conv_id: int, status: str) -> dict:
        """Toggle conversation status.  *status*: open | resolved | pending."""
        return self._request(
            "POST",
            f"/conversations/{conv_id}/toggle_status",
            {"status": status},
        )

    def assign_conversation(self, conv_id: int, assignee_id: int) -> dict:
        """Assign a conversation to an agent."""
        return self._request(
            "POST",
            f"/conversations/{conv_id}/assignments",
            {"assignee_id": assignee_id},
        )

    # ── Labels (Pipeline stages) ─────────────────────────────────────────

    def list_labels(self) -> dict:
        """List all account labels."""
        return self._request("GET", "/labels")

    def create_label(
        self,
        title: str,
        description: str = "",
        color: str = "#1F93FF",
    ) -> dict:
        """Create a new label."""
        return self._request(
            "POST",
            "/labels",
            {"title": title, "description": description, "color": color},
        )

    def add_label_to_conversation(self, conv_id: int, labels: list[str]) -> dict:
        """Set labels on a conversation (replaces existing labels)."""
        return self._request(
            "POST",
            f"/conversations/{conv_id}/labels",
            {"labels": labels},
        )

    def get_conversation_labels(self, conv_id: int) -> dict:
        """Get labels attached to a conversation."""
        return self._request("GET", f"/conversations/{conv_id}/labels")

    # ── Inboxes ───────────────────────────────────────────────────────────

    def list_inboxes(self) -> dict:
        """List all inboxes for the account."""
        return self._request("GET", "/inboxes")

    # ── Reports / Dashboard ───────────────────────────────────────────────

    def get_account_summary(self, since: str | None = None) -> dict:
        """Get agent summary report.  *since*: Unix timestamp string."""
        path = "/reports/agents/summary"
        if since:
            path += f"?since={since}"
        return self._request("GET", path)

    def get_conversation_counts(self) -> dict:
        """Count conversations grouped by status."""
        result: dict[str, int] = {}
        for status in ("open", "resolved", "pending"):
            r = self._request("GET", f"/conversations?status={status}&page=1")
            if "data" in r and isinstance(r["data"], dict):
                meta = r["data"].get("meta", {})
                result[status] = meta.get("all_count", 0)
            elif "error" not in r:
                result[status] = 0
        return result

    # ── Test Connection ───────────────────────────────────────────────────

    def test_connection(self) -> dict:
        """Test whether the stored credentials are valid."""
        result = self._request("GET", "/inboxes")
        if "error" in result:
            return {"connected": False, "error": result["error"]}
        payload = result.get("payload", result.get("data", []))
        count = len(payload) if isinstance(payload, list) else 0
        return {"connected": True, "inboxes": count}


# ---------------------------------------------------------------------------
# Pipeline helpers  (labels as CRM stages)
# ---------------------------------------------------------------------------

DEFAULT_PIPELINE: list[dict[str, str]] = [
    {"title": "lead",            "description": "Novo lead",          "color": "#FFB800"},
    {"title": "qualificado",     "description": "Lead qualificado",   "color": "#1F93FF"},
    {"title": "proposta",        "description": "Proposta enviada",   "color": "#8B5CF6"},
    {"title": "negociacao",      "description": "Em negociacao",      "color": "#F97316"},
    {"title": "fechado_ganho",   "description": "Fechado - Ganho",    "color": "#22C55E"},
    {"title": "fechado_perdido", "description": "Fechado - Perdido",  "color": "#EF4444"},
]


def setup_pipeline(client: ChatwootClient) -> list[dict]:
    """Create the default pipeline labels if they do not exist yet."""
    existing = client.list_labels()
    existing_titles: set[str] = set()
    if isinstance(existing, dict) and "payload" in existing:
        existing_titles = {lb.get("title", "") for lb in existing["payload"]}
    elif isinstance(existing, list):
        existing_titles = {lb.get("title", "") for lb in existing}

    created: list[dict] = []
    for stage in DEFAULT_PIPELINE:
        if stage["title"] not in existing_titles:
            res = client.create_label(**stage)
            created.append(res)
    return created


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_crm_config(tenant_id: str) -> CRMConfig:
    """Return the CRM configuration for *tenant_id*."""
    return CRMConfig.load(tenant_id)


def save_crm_config(
    tenant_id: str,
    chatwoot_url: str,
    api_token: str,
    account_id: int = 1,
) -> dict:
    """Validate credentials and persist the CRM configuration."""
    cfg = CRMConfig(
        tenant_id=tenant_id,
        chatwoot_url=chatwoot_url.rstrip("/"),
        chatwoot_api_token=api_token,
        chatwoot_account_id=account_id,
        configured=True,
    )
    # Test connection before saving
    client = ChatwootClient(cfg)
    test = client.test_connection()
    if not test.get("connected"):
        return {
            "error": f"Nao foi possivel conectar: {test.get('error', 'erro desconhecido')}"
        }
    cfg.save()
    log_action("crm_configured", f"tenant={tenant_id}")
    return {"success": True, "config": cfg.to_dict()}


def get_crm_client(tenant_id: str) -> ChatwootClient | None:
    """Return a ready-to-use client, or *None* if CRM is not configured."""
    cfg = CRMConfig.load(tenant_id)
    if not cfg.configured:
        return None
    return ChatwootClient(cfg)
