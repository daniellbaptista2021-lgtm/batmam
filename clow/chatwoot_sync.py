"""Chatwoot Sync — sincroniza conversas e contatos do Chatwoot com o CRM do Clow.

O Chatwoot funciona como hub de canais (WhatsApp API oficial, Z-API, etc).
O Clow puxa dados do Chatwoot via API e alimenta o CRM automaticamente.

Fluxo:
1. Cliente instala Chatwoot via setup guiado
2. Conecta WhatsApp no Chatwoot (API oficial, Cloud API ou Z-API)
3. Clow sincroniza inboxes do Chatwoot como instancias
4. Conversas e contatos fluem: Chatwoot → Clow CRM
5. O agente IA do Clow responde via Chatwoot API
"""

from __future__ import annotations

import json
import time
import threading
from urllib.request import urlopen, Request
from urllib.error import HTTPError

from . import config
from .logging import log_action


class ChatwootSync:
    """Sincroniza dados entre Chatwoot do cliente e CRM do Clow."""

    def __init__(self, tenant_id: str, chatwoot_url: str, api_token: str, account_id: int = 1):
        self.tenant_id = tenant_id
        self.base = f"{chatwoot_url.rstrip('/')}/api/v1/accounts/{account_id}"
        self.token = api_token
        self.chatwoot_url = chatwoot_url
        self.account_id = account_id

    def _get(self, path: str) -> dict:
        url = f"{self.base}{path}"
        req = Request(url, headers={"api_access_token": self.token})
        try:
            resp = urlopen(req, timeout=15)
            return json.loads(resp.read().decode())
        except HTTPError as e:
            return {"error": f"HTTP {e.code}"}
        except Exception as e:
            return {"error": str(e)[:200]}

    def _post(self, path: str, data: dict) -> dict:
        url = f"{self.base}{path}"
        body = json.dumps(data).encode()
        req = Request(url, data=body, headers={
            "api_access_token": self.token,
            "Content-Type": "application/json",
        }, method="POST")
        try:
            resp = urlopen(req, timeout=15)
            return json.loads(resp.read().decode())
        except HTTPError as e:
            err_body = e.read().decode() if e.fp else ""
            return {"error": f"HTTP {e.code}: {err_body[:200]}"}
        except Exception as e:
            return {"error": str(e)[:200]}

    # ── Inboxes (canais WhatsApp) ──

    def list_inboxes(self) -> list[dict]:
        """Lista inboxes do Chatwoot (cada inbox = um canal WhatsApp)."""
        result = self._get("/inboxes")
        return result.get("payload", [])

    def get_whatsapp_inboxes(self) -> list[dict]:
        """Retorna apenas inboxes de WhatsApp."""
        inboxes = self.list_inboxes()
        wa_types = {"Channel::Whatsapp", "Channel::Api", "Channel::TwilioSms"}
        return [i for i in inboxes if i.get("channel_type") in wa_types]

    def create_api_inbox(self, name: str) -> dict:
        """Cria inbox tipo API (para Z-API ou integracao customizada)."""
        return self._post("/inboxes", {
            "name": name,
            "channel": {"type": "api", "webhook_url": ""},
        })

    # ── Contatos ──

    def list_contacts(self, page: int = 1) -> list[dict]:
        result = self._get(f"/contacts?page={page}")
        return result.get("payload", [])

    def get_all_contacts(self, max_pages: int = 20) -> list[dict]:
        """Busca todos os contatos paginando."""
        all_contacts = []
        for page in range(1, max_pages + 1):
            batch = self.list_contacts(page)
            if not batch:
                break
            all_contacts.extend(batch)
        return all_contacts

    # ── Conversas ──

    def list_conversations(self, inbox_id: int = 0, status: str = "open", page: int = 1) -> list[dict]:
        path = f"/conversations?status={status}&page={page}"
        if inbox_id:
            path += f"&inbox_id={inbox_id}"
        result = self._get(path)
        return result.get("data", {}).get("payload", [])

    def get_conversation_messages(self, conv_id: int) -> list[dict]:
        result = self._get(f"/conversations/{conv_id}/messages")
        return result.get("payload", [])

    def send_message(self, conv_id: int, content: str, message_type: str = "outgoing") -> dict:
        """Envia mensagem numa conversa do Chatwoot."""
        return self._post(f"/conversations/{conv_id}/messages", {
            "content": content,
            "message_type": message_type,
        })

    # ── Sync para CRM ──

    def sync_inboxes_to_instances(self) -> list[dict]:
        """Sincroniza inboxes do Chatwoot como instancias WhatsApp no Clow.

        Para cada inbox WhatsApp no Chatwoot, cria/atualiza instancia no Clow.
        """
        from .whatsapp_agent import WhatsAppInstance, WA_BASE_DIR

        wa_inboxes = self.get_whatsapp_inboxes()
        synced = []

        for inbox in wa_inboxes:
            inbox_id = inbox.get("id", 0)
            instance_id = f"cw-inbox-{inbox_id}"
            name = inbox.get("name", f"WhatsApp #{inbox_id}")

            # Verifica se ja existe
            inst_dir = WA_BASE_DIR / self.tenant_id / instance_id
            inst = WhatsAppInstance.load(inst_dir) if inst_dir.exists() else None

            if not inst:
                inst = WhatsAppInstance(
                    id=instance_id,
                    tenant_id=self.tenant_id,
                    name=name,
                    zapi_instance_id=str(inbox_id),
                    zapi_token="chatwoot",  # Marker: usa Chatwoot API em vez de Z-API
                    active=True,
                )
                inst.save()
                log_action("chatwoot_inbox_synced", f"tenant={self.tenant_id} inbox={inbox_id} name={name}")

            synced.append({
                "instance_id": instance_id,
                "inbox_id": inbox_id,
                "name": name,
                "channel_type": inbox.get("channel_type", ""),
            })

        return synced

    def sync_contacts_to_leads(self) -> dict:
        """Importa contatos do Chatwoot como leads no CRM."""
        from .crm_models import create_lead, get_lead_by_phone, get_lead_by_email

        contacts = self.get_all_contacts()
        imported = 0
        skipped = 0

        for c in contacts:
            phone = c.get("phone_number", "")
            email = c.get("email", "")
            name = c.get("name", "")

            if not phone and not email and not name:
                skipped += 1
                continue

            existing = None
            if phone:
                existing = get_lead_by_phone(self.tenant_id, phone)
            if not existing and email:
                existing = get_lead_by_email(self.tenant_id, email)

            if existing:
                skipped += 1
                continue

            # Determina instancia pelo inbox das conversas (default: primeiro inbox)
            instance_id = ""
            wa_inboxes = self.get_whatsapp_inboxes()
            if wa_inboxes:
                instance_id = f"cw-inbox-{wa_inboxes[0]['id']}"

            create_lead(
                self.tenant_id, name=name, phone=phone, email=email,
                source="whatsapp", instance_id=instance_id,
            )
            imported += 1

        log_action("chatwoot_contacts_synced", f"tenant={self.tenant_id} imported={imported} skipped={skipped}")
        return {"imported": imported, "skipped": skipped, "total": len(contacts)}

    def sync_conversations_to_timeline(self, instance_id: str, inbox_id: int, limit: int = 25) -> int:
        """Importa mensagens recentes das conversas para a timeline dos leads."""
        from .crm_models import get_lead_by_phone, add_activity

        convs = self.list_conversations(inbox_id=inbox_id, status="open", page=1)
        synced = 0

        for conv in convs[:limit]:
            sender = conv.get("meta", {}).get("sender", {})
            phone = sender.get("phone_number", "")
            if not phone:
                continue

            lead = get_lead_by_phone(self.tenant_id, phone)
            if not lead:
                continue

            # Pega ultimas mensagens
            messages = self.get_conversation_messages(conv["id"])
            for msg in messages[-5:]:  # Ultimas 5
                content = msg.get("content", "")
                if not content:
                    continue
                msg_type = msg.get("message_type", 0)
                role = "Cliente" if msg_type == 0 else "Agente"
                add_activity(lead["id"], self.tenant_id, "whatsapp",
                             f"{role}: {content[:150]}")
            synced += 1

        return synced


# ── Helper para obter sync client de um tenant ──

def get_sync_client(tenant_id: str) -> ChatwootSync | None:
    """Retorna ChatwootSync configurado para o tenant, ou None."""
    from .infra_setup import get_tenant_infra
    infra = get_tenant_infra(tenant_id)
    if not infra or not infra.get("chatwoot_url"):
        return None
    return ChatwootSync(
        tenant_id=tenant_id,
        chatwoot_url=infra["chatwoot_url"],
        api_token=infra["api_token"],
    )


def full_sync(tenant_id: str) -> dict:
    """Sincronizacao completa: inboxes → instancias, contatos → leads."""
    client = get_sync_client(tenant_id)
    if not client:
        return {"error": "Chatwoot nao configurado"}

    inboxes = client.sync_inboxes_to_instances()
    contacts = client.sync_contacts_to_leads()

    # Sync conversas por inbox
    convs_synced = 0
    for inbox in inboxes:
        convs_synced += client.sync_conversations_to_timeline(
            inbox["instance_id"], inbox["inbox_id"])

    return {
        "inboxes_synced": len(inboxes),
        "contacts": contacts,
        "conversations_synced": convs_synced,
    }


def run_periodic_sync() -> None:
    """Chamado pelo cron — sincroniza todos os tenants com Chatwoot."""
    from .infra_setup import _SETUP_DIR
    tenants_dir = config.CLOW_HOME / "tenants"
    if not tenants_dir.exists():
        return

    for td in tenants_dir.iterdir():
        if not td.is_dir():
            continue
        infra_path = td / "infra.json"
        if not infra_path.exists():
            continue
        try:
            full_sync(td.name)
        except Exception as e:
            log_action("chatwoot_sync_error", f"tenant={td.name}: {e}", level="error")
