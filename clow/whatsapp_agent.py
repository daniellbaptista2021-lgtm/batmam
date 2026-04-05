"""WhatsApp Agent — cada instancia Z-API e um agente Clow independente.

Cada cliente conecta seu WhatsApp. O Clow recebe mensagens via webhook,
processa com Sonnet/Haiku conforme plano, e responde pelo WhatsApp do cliente.
"""

from __future__ import annotations
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.request import urlopen, Request
from urllib.error import URLError

from . import config
from .logging import log_action

WA_BASE_DIR = config.CLOW_HOME / "whatsapp_instances"
WA_BASE_DIR.mkdir(parents=True, exist_ok=True)

DEBOUNCE_SECONDS = 8
MAX_PDFS_PER_INSTANCE = 5
MAX_PDF_SIZE_MB = 10
INCLUDED_INSTANCES = 2
ADDON_PACK_SIZE = 2
ADDON_PRICE_BRL = 50


@dataclass
class WhatsAppInstance:
    id: str
    tenant_id: str
    name: str
    zapi_instance_id: str
    zapi_token: str
    system_prompt: str = ""
    rag_text: str = ""
    rag_documents: list = field(default_factory=list)
    active: bool = True
    context_size: int = 20
    handoff_enabled: bool = False
    handoff_keyword: str = "humano"
    created_at: float = field(default_factory=time.time)
    stats: dict = field(default_factory=lambda: {"messages_today": 0, "messages_total": 0, "last_message_at": 0})

    @property
    def webhook_url(self) -> str:
        return f"https://clow.pvcorretor01.com.br/api/v1/whatsapp/webhook/{self.id}"

    @property
    def instance_dir(self) -> Path:
        d = WA_BASE_DIR / self.tenant_id / self.id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def to_dict(self) -> dict:
        return {
            "id": self.id, "tenant_id": self.tenant_id, "name": self.name,
            "zapi_instance_id": self.zapi_instance_id,
            "zapi_token": self.zapi_token[:8] + "..." if self.zapi_token else "",
            "system_prompt": self.system_prompt[:200],
            "rag_text": self.rag_text[:100] + "..." if len(self.rag_text) > 100 else self.rag_text,
            "rag_documents": [{"filename": d["filename"], "size": d.get("size", 0)} for d in self.rag_documents],
            "active": self.active, "context_size": self.context_size,
            "handoff_enabled": self.handoff_enabled, "handoff_keyword": self.handoff_keyword,
            "webhook_url": self.webhook_url, "created_at": self.created_at, "stats": self.stats,
        }

    def save(self) -> None:
        cfg = self.instance_dir / "config.json"
        data = {
            "id": self.id, "tenant_id": self.tenant_id, "name": self.name,
            "zapi_instance_id": self.zapi_instance_id, "zapi_token": self.zapi_token,
            "system_prompt": self.system_prompt, "rag_text": self.rag_text,
            "rag_documents": self.rag_documents, "active": self.active,
            "context_size": self.context_size, "handoff_enabled": self.handoff_enabled,
            "handoff_keyword": self.handoff_keyword, "created_at": self.created_at, "stats": self.stats,
        }
        cfg.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> WhatsAppInstance | None:
        cfg = path / "config.json"
        if not cfg.exists():
            return None
        try:
            d = json.loads(cfg.read_text(encoding="utf-8"))
            return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        except Exception:
            return None


class WhatsAppAgentManager:

    def create_instance(self, tenant_id: str, name: str, zapi_instance_id: str, zapi_token: str, system_prompt: str = "") -> dict:
        can, msg = self.can_add_instance(tenant_id)
        if not can:
            return {"error": msg}
        inst = WhatsAppInstance(
            id=uuid.uuid4().hex[:12], tenant_id=tenant_id, name=name,
            zapi_instance_id=zapi_instance_id, zapi_token=zapi_token,
            system_prompt=system_prompt,
        )
        inst.save()
        log_action("whatsapp_instance_created", f"{inst.id} for {tenant_id}")
        return {"success": True, "instance": inst.to_dict()}

    def update_instance(self, instance_id: str, tenant_id: str, **kwargs) -> dict:
        inst = self.get_instance(instance_id, tenant_id)
        if not inst:
            return {"error": "Instancia nao encontrada"}
        for k, v in kwargs.items():
            if hasattr(inst, k) and k not in ("id", "tenant_id", "created_at"):
                setattr(inst, k, v)
        inst.save()
        return {"success": True, "instance": inst.to_dict()}

    def delete_instance(self, instance_id: str, tenant_id: str) -> bool:
        inst = self.get_instance(instance_id, tenant_id)
        if not inst:
            return False
        import shutil
        shutil.rmtree(str(inst.instance_dir), ignore_errors=True)
        return True

    def get_instances(self, tenant_id: str) -> list[dict]:
        tenant_dir = WA_BASE_DIR / tenant_id
        if not tenant_dir.exists():
            return []
        instances = []
        for d in sorted(tenant_dir.iterdir()):
            if d.is_dir():
                inst = WhatsAppInstance.load(d)
                if inst:
                    instances.append(inst.to_dict())
        return instances

    def get_instance(self, instance_id: str, tenant_id: str = "") -> WhatsAppInstance | None:
        if tenant_id:
            path = WA_BASE_DIR / tenant_id / instance_id
            return WhatsAppInstance.load(path)
        # Search all tenants
        for td in WA_BASE_DIR.iterdir():
            if td.is_dir():
                path = td / instance_id
                inst = WhatsAppInstance.load(path)
                if inst:
                    return inst
        return None

    def can_add_instance(self, tenant_id: str) -> tuple[bool, str]:
        current = len(self.get_instances(tenant_id))
        return True, ""  # Always allow, billing handles the cost

    def get_extra_cost(self, tenant_id: str) -> float:
        count = len(self.get_instances(tenant_id))
        if count <= INCLUDED_INSTANCES:
            return 0
        extra = count - INCLUDED_INSTANCES
        packs = (extra + ADDON_PACK_SIZE - 1) // ADDON_PACK_SIZE
        return packs * ADDON_PRICE_BRL

    # ── Message Processing ────────────────────────────────────

    def process_incoming(self, instance_id: str, sender_phone: str, message_text: str) -> str | None:
        inst = self.get_instance(instance_id)
        if not inst or not inst.active:
            return None

        # Check handoff
        if inst.handoff_enabled and self._is_handoff_active(inst, sender_phone):
            return None

        # Check tenant quota
        from .billing import check_quota, get_plan, plan_uses_server_key
        from .database import get_user_by_id, get_user_api_key

        user = get_user_by_id(inst.tenant_id)
        if not user:
            return None
        plan_id = user.get("plan", "byok_free")
        if plan_id in ("free", "basic", "unlimited"):
            plan_id = "byok_free"

        # Todos os planos tem franquia WhatsApp separada
        quota = check_quota(inst.tenant_id, plan_id, source="whatsapp")
        if not quota["allowed"]:
            return "Ola! Nosso atendimento automatico esta temporariamente indisponivel. Por favor, tente novamente mais tarde ou aguarde que um atendente humano entrara em contato."

        # Load conversation history
        history = self.get_conversation_history(inst, sender_phone)

        # Build context
        system_parts = []
        if inst.system_prompt:
            system_parts.append(inst.system_prompt)
        if inst.rag_text:
            system_parts.append(f"\n[Base de Conhecimento]\n{inst.rag_text}")
        system_parts.append("\nVoce esta respondendo via WhatsApp. Seja conciso e objetivo. Use formatacao simples (sem markdown complexo).")

        system_prompt = "\n\n".join(system_parts)

        # Build messages
        messages = [{"role": "system", "content": system_prompt}]
        for msg in history[-(inst.context_size):]:
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": message_text})

        # Call LLM — WhatsApp SEMPRE usa Haiku (wa_model)
        try:
            plan = get_plan(plan_id)
            wa_model = plan.get("wa_model", "claude-haiku-4-5-20251001")
            api_key = None
            if not plan_uses_server_key(plan_id):
                api_key = get_user_api_key(inst.tenant_id)
                if not api_key:
                    return None

            from anthropic import Anthropic
            client = Anthropic(api_key=api_key or config.ANTHROPIC_API_KEY)
            response = client.messages.create(
                model=wa_model,
                system=system_prompt,
                messages=[m for m in messages if m["role"] != "system"],
                max_tokens=1024,
            )
            reply = response.content[0].text if response.content else ""

            # Record usage com source=whatsapp
            inp_tokens = response.usage.input_tokens if response.usage else 0
            out_tokens = response.usage.output_tokens if response.usage else 0
            from .metrics_collector import record_request
            record_request(inst.tenant_id, plan_id, inp_tokens, out_tokens, source="whatsapp")

        except Exception as e:
            log_action("whatsapp_agent_error", str(e)[:200], level="error")
            return None

        # Save to history
        self._save_message(inst, sender_phone, "user", message_text)
        self._save_message(inst, sender_phone, "assistant", reply)

        # Update stats
        inst.stats["messages_today"] = inst.stats.get("messages_today", 0) + 1
        inst.stats["messages_total"] = inst.stats.get("messages_total", 0) + 1
        inst.stats["last_message_at"] = time.time()
        inst.save()

        # Send via Z-API
        self._send_zapi(inst, sender_phone, reply)

        log_action("whatsapp_msg_processed", f"inst={instance_id} phone={sender_phone[-4:]}")
        return reply

    def get_conversation_history(self, inst: WhatsAppInstance, phone: str) -> list[dict]:
        conv_file = inst.instance_dir / "conversations" / f"{phone}.json"
        if not conv_file.exists():
            return []
        try:
            return json.loads(conv_file.read_text(encoding="utf-8"))
        except Exception:
            return []

    def clear_conversation(self, inst: WhatsAppInstance, phone: str) -> bool:
        conv_file = inst.instance_dir / "conversations" / f"{phone}.json"
        if conv_file.exists():
            conv_file.unlink()
            return True
        return False

    def list_conversations(self, inst: WhatsAppInstance) -> list[dict]:
        conv_dir = inst.instance_dir / "conversations"
        if not conv_dir.exists():
            return []
        convs = []
        for f in sorted(conv_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            phone = f.stem
            try:
                msgs = json.loads(f.read_text(encoding="utf-8"))
                last = msgs[-1] if msgs else {}
                convs.append({
                    "phone": phone,
                    "total_messages": len(msgs),
                    "last_message": last.get("content", "")[:80],
                    "last_at": last.get("timestamp", 0),
                })
            except Exception:
                continue
        return convs

    def _save_message(self, inst: WhatsAppInstance, phone: str, role: str, content: str) -> None:
        conv_dir = inst.instance_dir / "conversations"
        conv_dir.mkdir(parents=True, exist_ok=True)
        conv_file = conv_dir / f"{phone}.json"
        history = []
        if conv_file.exists():
            try:
                history = json.loads(conv_file.read_text(encoding="utf-8"))
            except Exception:
                history = []
        history.append({"role": role, "content": content, "timestamp": time.time()})
        # Keep last 200 messages
        if len(history) > 200:
            history = history[-200:]
        conv_file.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")

    def _is_handoff_active(self, inst: WhatsAppInstance, phone: str) -> bool:
        history = self.get_conversation_history(inst, phone)
        cutoff = time.time() - 7200  # 2 hours
        for msg in reversed(history):
            if msg.get("timestamp", 0) < cutoff:
                break
            if msg.get("role") == "user" and inst.handoff_keyword.lower() in msg.get("content", "").lower():
                return True
        return False

    def _send_zapi(self, inst: WhatsAppInstance, phone: str, message: str) -> bool:
        try:
            url = f"https://api.z-api.io/instances/{inst.zapi_instance_id}/token/{inst.zapi_token}/send-text"
            data = json.dumps({"phone": phone, "message": message}).encode()
            req = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
            urlopen(req, timeout=30)
            return True
        except Exception as e:
            log_action("whatsapp_send_error", str(e)[:100], level="error")
            return False

    def test_connection(self, zapi_instance_id: str, zapi_token: str) -> dict:
        try:
            url = f"https://api.z-api.io/instances/{zapi_instance_id}/token/{zapi_token}/status"
            req = Request(url, headers={"Content-Type": "application/json"})
            resp = urlopen(req, timeout=15)
            data = json.loads(resp.read().decode())
            return {"connected": True, "status": data}
        except Exception as e:
            return {"connected": False, "error": str(e)[:150]}


# Global manager
_manager = WhatsAppAgentManager()

def get_wa_manager() -> WhatsAppAgentManager:
    return _manager
