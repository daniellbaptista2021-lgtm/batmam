"""Chatwoot Integration — sync messages, labels, and handoff control."""

import json
import logging
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

logger = logging.getLogger("clow.chatwoot_integration")


class ChatwootClient:
    """Client for Chatwoot API v1."""

    def __init__(self, url: str, account_id: int, api_token: str):
        self.base_url = url.rstrip("/")
        self.account_id = account_id
        self.api_token = api_token

    def _api(self, method: str, path: str, data: dict = None) -> dict:
        """Make API call to Chatwoot."""
        url = f"{self.base_url}/api/v1/accounts/{self.account_id}/{path}"
        headers = {
            "Content-Type": "application/json",
            "api_access_token": self.api_token,
        }
        body = json.dumps(data).encode() if data else None
        req = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except HTTPError as e:
            body = e.read().decode() if e.fp else ""
            logger.error(f"Chatwoot API {method} {path}: {e.code} {body[:200]}")
            return {"error": e.code, "message": body[:200]}
        except Exception as e:
            logger.error(f"Chatwoot API error: {e}")
            return {"error": str(e)}

    def find_contact_by_phone(self, phone: str) -> dict | None:
        """Search for contact by phone number."""
        result = self._api("GET", f"contacts/search?q={phone}&include_contacts=true")
        contacts = result.get("payload", [])
        if contacts:
            return contacts[0]
        # Try without + prefix
        clean = phone.lstrip("+").lstrip("55")
        result = self._api("GET", f"contacts/search?q={clean}")
        contacts = result.get("payload", [])
        return contacts[0] if contacts else None

    def create_contact(self, phone: str, name: str = "") -> dict:
        """Create a new contact."""
        if not name:
            name = f"WhatsApp {phone[-4:]}"
        return self._api("POST", "contacts", {
            "name": name,
            "phone_number": f"+{phone.lstrip('+')}",
            "identifier": phone,
        })

    def find_or_create_contact(self, phone: str, name: str = "") -> dict:
        """Find existing contact or create new one."""
        contact = self.find_contact_by_phone(phone)
        if contact:
            return contact
        return self.create_contact(phone, name)

    def get_conversations_for_contact(self, contact_id: int) -> list:
        """Get all conversations for a contact."""
        result = self._api("GET", f"contacts/{contact_id}/conversations")
        return result.get("payload", [])

    def create_conversation(self, contact_id: int, inbox_id: int, message: str = "") -> dict:
        """Create a new conversation."""
        data = {
            "contact_id": contact_id,
            "inbox_id": inbox_id,
        }
        if message:
            data["message"] = {"content": message}
        return self._api("POST", "conversations", data)

    def find_or_create_conversation(self, contact_id: int, inbox_id: int) -> dict:
        """Find open conversation or create new one."""
        convos = self.get_conversations_for_contact(contact_id)
        for c in convos:
            if c.get("inbox_id") == inbox_id and c.get("status") in ("open", "pending"):
                return c
        return self.create_conversation(contact_id, inbox_id)

    def send_message(self, conversation_id: int, content: str, message_type: str = "incoming", private: bool = False) -> dict:
        """Send a message in a conversation.
        message_type: 'incoming' (from customer) or 'outgoing' (from agent/bot)
        """
        return self._api("POST", f"conversations/{conversation_id}/messages", {
            "content": content,
            "message_type": message_type,
            "private": private,
        })

    def get_labels(self, conversation_id: int) -> list[str]:
        """Get labels for a conversation."""
        result = self._api("GET", f"conversations/{conversation_id}/labels")
        return result.get("payload", [])

    def add_label(self, conversation_id: int, label: str) -> dict:
        """Add a label to a conversation."""
        current = self.get_labels(conversation_id)
        if label not in current:
            current.append(label)
        return self._api("POST", f"conversations/{conversation_id}/labels", {
            "labels": current,
        })

    def remove_label(self, conversation_id: int, label: str) -> dict:
        """Remove a label from a conversation."""
        current = self.get_labels(conversation_id)
        if label in current:
            current.remove(label)
        return self._api("POST", f"conversations/{conversation_id}/labels", {
            "labels": current,
        })

    def has_label(self, conversation_id: int, label: str) -> bool:
        """Check if conversation has a specific label."""
        return label in self.get_labels(conversation_id)

    def get_messages(self, conversation_id: int) -> list:
        """Get messages for a conversation."""
        result = self._api("GET", f"conversations/{conversation_id}/messages")
        return result.get("payload", [])

    def get_inboxes(self) -> list:
        """List all inboxes."""
        result = self._api("GET", "inboxes")
        return result.get("payload", [])

    def assign_conversation(self, conversation_id: int, agent_id: int = None) -> dict:
        """Assign conversation to an agent."""
        data = {}
        if agent_id:
            data["assignee_id"] = agent_id
        return self._api("POST", f"conversations/{conversation_id}/assignments", data)


# Cache of clients per tenant
_clients: dict[str, ChatwootClient] = {}


def get_chatwoot_client(tenant_id: str) -> ChatwootClient | None:
    """Get or create Chatwoot client for a tenant. Uses per-instance config or global env."""
    if tenant_id in _clients:
        return _clients[tenant_id]

    import os
    url = os.getenv("CHATWOOT_URL", "")
    account_id = int(os.getenv("CHATWOOT_ACCOUNT_ID", "0"))
    token = os.getenv("CHATWOOT_API_TOKEN", "")

    if not url or not token:
        return None

    client = ChatwootClient(url, account_id, token)
    _clients[tenant_id] = client
    return client


# Conversation ID cache: {instance_id:phone -> chatwoot_conversation_id}
_conversation_cache: dict[str, int] = {}


def get_or_create_chatwoot_conversation(client: ChatwootClient, instance_id: str, phone: str, inbox_id: int) -> int | None:
    """Get or create a Chatwoot conversation for a phone number. Returns conversation_id."""
    cache_key = f"{instance_id}:{phone}"
    if cache_key in _conversation_cache:
        return _conversation_cache[cache_key]

    try:
        contact = client.find_or_create_contact(phone)
        contact_id = contact.get("id")
        if not contact_id:
            logger.error(f"Could not find/create contact for {phone}")
            return None

        convo = client.find_or_create_conversation(contact_id, inbox_id)
        convo_id = convo.get("id")
        if convo_id:
            _conversation_cache[cache_key] = convo_id
            # Add "bot" label to new conversations
            client.add_label(convo_id, "bot")
        return convo_id
    except Exception as e:
        logger.error(f"Chatwoot conversation error: {e}")
        return None


def check_handoff_label(client: ChatwootClient, conversation_id: int, label: str = "humano") -> bool:
    """Check if the conversation has the handoff label active."""
    return client.has_label(conversation_id, label)


def trigger_handoff(client: ChatwootClient, conversation_id: int, reason: str = "", label: str = "humano"):
    """Trigger handoff: add label, notify agents."""
    client.add_label(conversation_id, label)
    # Remove bot label
    client.remove_label(conversation_id, "bot")
    # Send internal note
    note = "Bot transferiu para atendimento humano."
    if reason:
        note += f"\nMotivo: {reason}"
    client.send_message(conversation_id, note, message_type="outgoing", private=True)
    logger.info(f"Handoff triggered for conversation {conversation_id}: {reason}")


def reactivate_bot(client: ChatwootClient, conversation_id: int, label: str = "humano", send_greeting: bool = True):
    """Reactivate bot after human handoff ends."""
    client.remove_label(conversation_id, label)
    client.add_label(conversation_id, "bot")
    if send_greeting:
        client.send_message(conversation_id, "Ola! Sou o assistente virtual. Posso ajudar em algo mais?", message_type="outgoing")
    logger.info(f"Bot reactivated for conversation {conversation_id}")


LEAD_KEYWORDS = ["preco", "preço", "valor", "quanto", "comprar", "quero", "contratar", "assinar", "plano"]


def detect_lead_interest(message: str) -> bool:
    """Detect if message shows purchase interest."""
    msg_lower = message.lower()
    return any(kw in msg_lower for kw in LEAD_KEYWORDS)
