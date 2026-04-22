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
    auto_reply_enabled: bool = True
    context_size: int = 20
    handoff_enabled: bool = False
    handoff_keyword: str = "humano"
    created_at: float = field(default_factory=time.time)
    stats: dict = field(default_factory=lambda: {"messages_today": 0, "messages_total": 0, "last_message_at": 0})
    provider: str = "zapi"  # "zapi" or "meta"
    meta_phone_number_id: str = ""
    meta_waba_id: str = ""
    meta_access_token: str = ""
    meta_verify_token: str = ""
    zapi_client_token: str = ""

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
            "system_prompt": self.system_prompt,
            "rag_text": self.rag_text,
            "rag_documents": [{"filename": d["filename"], "size": d.get("size", 0)} for d in self.rag_documents],
            "active": self.active, "context_size": self.context_size,
            "handoff_enabled": self.handoff_enabled, "handoff_keyword": self.handoff_keyword,
            "webhook_url": self.webhook_url, "created_at": self.created_at, "stats": self.stats,
            "provider": self.provider,
            "meta_phone_number_id": self.meta_phone_number_id,
            "meta_waba_id": self.meta_waba_id,
            "meta_access_token": self.meta_access_token[:8] + "..." if self.meta_access_token else "",
            "meta_verify_token": self.meta_verify_token,
            "zapi_client_token": self.zapi_client_token[:8] + "..." if self.zapi_client_token else "",
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
            "provider": self.provider,
            "meta_phone_number_id": self.meta_phone_number_id,
            "meta_waba_id": self.meta_waba_id,
            "meta_access_token": self.meta_access_token,
            "meta_verify_token": self.meta_verify_token,
            "zapi_client_token": self.zapi_client_token,
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

    def create_instance(self, tenant_id: str, name: str, zapi_instance_id: str, zapi_token: str, system_prompt: str = "",
                        provider: str = "zapi", meta_phone_number_id: str = "", meta_waba_id: str = "",
                        meta_access_token: str = "", meta_verify_token: str = "",
                        zapi_client_token: str = "") -> dict:
        can, msg = self.can_add_instance(tenant_id)
        if not can:
            return {"error": msg}
        inst = WhatsAppInstance(
            id=uuid.uuid4().hex[:12], tenant_id=tenant_id, name=name,
            zapi_instance_id=zapi_instance_id, zapi_token=zapi_token,
            system_prompt=system_prompt,
            provider=provider,
            meta_phone_number_id=meta_phone_number_id,
            meta_waba_id=meta_waba_id,
            meta_access_token=meta_access_token,
            meta_verify_token=meta_verify_token,
            zapi_client_token=zapi_client_token,
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

    def get_instance(self, instance_id: str, tenant_id: str = "", allow_webhook: bool = False) -> WhatsAppInstance | None:
        if tenant_id:
            path = WA_BASE_DIR / tenant_id / instance_id
            return WhatsAppInstance.load(path)
        # Sem tenant_id: so permitido se allow_webhook=True (chamada interna de webhook)
        if not allow_webhook:
            import logging
            logging.getLogger('clow.security').warning(
                f'WA cross-tenant lookup blocked: instance_id={instance_id} without tenant_id'
            )
            return None
        # Webhook: search com audit log
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
        # Webhook interno: deriva tenant_id via scan controlado (marca como trusted)
        inst = self.get_instance(instance_id, allow_webhook=True)
        if not inst or not inst.active:
            return None

        # Check auto_reply — se desligado, nao responde mas registra metricas
        if not inst.auto_reply_enabled:
            log_action("whatsapp_msg_skipped", f"inst={instance_id} auto_reply=off")
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

        # ── CRM: busca/cria lead automaticamente com instance_id ──
        crm_lead_id = None
        try:
            from .crm_models import get_lead_by_phone, create_lead, add_activity
            crm_lead = get_lead_by_phone(inst.tenant_id, sender_phone)
            if not crm_lead:
                crm_lead = create_lead(
                    inst.tenant_id, phone=sender_phone,
                    source="whatsapp", notes="Lead criado automaticamente via WhatsApp",
                    instance_id=inst.id,
                    source_phone=inst.zapi_instance_id,
                )
            crm_lead_id = crm_lead["id"] if crm_lead else None
        except Exception:
            pass  # CRM e opcional, nao bloqueia o fluxo

        # Load conversation history
        history = self.get_conversation_history(inst, sender_phone)

        # Build context — verifica A/B test
        active_prompt = inst.system_prompt
        try:
            from .prompt_ab_test import get_prompt_for_variant, record_interaction
            ab_prompt = get_prompt_for_variant(inst.id, sender_phone)
            if ab_prompt:
                active_prompt = ab_prompt
                record_interaction(inst.id, sender_phone)
        except Exception:
            pass

        system_parts = []
        if active_prompt:
            system_parts.append(active_prompt)
        if inst.rag_text:
            system_parts.append(f"\n[Base de Conhecimento]\n{inst.rag_text}")

        # Injeta correcoes/treinamento do agente
        try:
            from .crm_agent_training import get_training_context
            training = get_training_context(inst.tenant_id, inst.id)
            if training:
                system_parts.append(training)
        except Exception:
            pass

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
            wa_model = plan.get("wa_model", "deepseek-chat")
            api_key = None
            if not plan_uses_server_key(plan_id):
                api_key = get_user_api_key(inst.tenant_id)
                if not api_key:
                    return None

            llm_msgs = [{"role": "system", "content": system_prompt}]
            llm_msgs.extend([m for m in messages if m["role"] != "system"])

            from openai import OpenAI
            client = OpenAI(**config.get_deepseek_client_kwargs())
            # OBRIGATORIO: WhatsApp auto-reply SEMPRE usa deepseek-chat (mais barato)
            # Nunca usar reasoner para respostas automaticas
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=llm_msgs,
                max_tokens=1024,
            )
            reply = response.choices[0].message.content if response.choices else ""
            inp_tokens = response.usage.prompt_tokens if response.usage else 0
            out_tokens = response.usage.completion_tokens if response.usage else 0
            # Cache metrics
            cache_hit = getattr(response.usage, 'prompt_cache_hit_tokens', 0) or 0
            cache_miss = getattr(response.usage, 'prompt_cache_miss_tokens', 0) or 0
            if cache_hit > 0:
                log_action("wa_cache", f"hit={cache_hit} miss={cache_miss} pct={round(cache_hit/(cache_hit+cache_miss)*100) if (cache_hit+cache_miss)>0 else 0}%")
            from .metrics_collector import record_request
            record_request(inst.tenant_id, plan_id, inp_tokens, out_tokens, source="whatsapp")

            # Registra custo no lead do CRM
            if crm_lead_id:
                try:
                    from .crm_models import update_lead
                    token_cost = (inp_tokens * config.DEEPSEEK_INPUT_PRICE_PER_MTOK + out_tokens * config.DEEPSEEK_OUTPUT_PRICE_PER_MTOK) / 1_000_000
                    old_tokens = crm_lead.get("cost_tokens_used", 0) if crm_lead else 0
                    old_cost = crm_lead.get("cost_estimated_brl", 0) if crm_lead else 0
                    update_lead(crm_lead_id, inst.tenant_id,
                                cost_tokens_used=old_tokens + inp_tokens + out_tokens,
                                cost_estimated_brl=round(old_cost + token_cost, 6))
                except Exception:
                    pass

        except Exception as e:
            log_action("whatsapp_agent_error", str(e)[:200], level="error")
            return None

        # Save to history
        self._save_message(inst, sender_phone, "user", message_text)
        self._save_message(inst, sender_phone, "assistant", reply)

        # ── CRM: registra atividade na timeline do lead ──
        if crm_lead_id:
            try:
                from .crm_models import add_activity
                add_activity(crm_lead_id, inst.tenant_id, "whatsapp",
                             f"Cliente: {message_text[:100]}")
                add_activity(crm_lead_id, inst.tenant_id, "whatsapp",
                             f"Bot: {reply[:100]}")
            except Exception:
                pass

            # ── CRM: funil automatico — analisa conversa e move/sugere ──
            try:
                from .crm_auto_funnel import process_new_message
                lead_status = crm_lead.get("status", "novo") if crm_lead else "novo"
                recent = history[-(inst.context_size):] + [
                    {"role": "user", "content": message_text},
                    {"role": "assistant", "content": reply},
                ]
                process_new_message(inst.tenant_id, inst.id, crm_lead_id, lead_status, recent)
            except Exception:
                pass

        # Update stats
        inst.stats["messages_today"] = inst.stats.get("messages_today", 0) + 1
        inst.stats["messages_total"] = inst.stats.get("messages_total", 0) + 1
        inst.stats["last_message_at"] = time.time()
        inst.save()

        # Send via provider (Meta or Z-API)
        if inst.provider == "meta":
            self._send_meta(inst, sender_phone, reply)
        else:
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
            headers = {"Content-Type": "application/json"}
            # Z-API requires Client-Token header
            client_token = getattr(inst, "zapi_client_token", "") or os.getenv("ZAPI_CLIENT_TOKEN", "")
            if client_token:
                headers["Client-Token"] = client_token
            req = Request(url, data=data, headers=headers, method="POST")
            urlopen(req, timeout=30)
            return True
        except Exception as e:
            log_action("whatsapp_send_error", str(e)[:100], level="error")
            return False

    def _send_meta(self, inst: WhatsAppInstance, phone: str, message: str) -> bool:
        """Send message via Meta WhatsApp Business API."""
        try:
            url = f"https://graph.facebook.com/v18.0/{inst.meta_phone_number_id}/messages"
            data = json.dumps({
                "messaging_product": "whatsapp",
                "to": phone.lstrip("+"),
                "type": "text",
                "text": {"body": message}
            }).encode()
            req = Request(url, data=data, headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {inst.meta_access_token}",
            }, method="POST")
            urlopen(req, timeout=30)
            return True
        except Exception as e:
            log_action("meta_send_error", str(e)[:100], level="error")
            return False

    def test_meta_connection(self, access_token: str, phone_number_id: str) -> dict:
        """Test Meta WhatsApp Business API connection."""
        try:
            url = f"https://graph.facebook.com/v18.0/{phone_number_id}"
            req = Request(url, headers={"Authorization": f"Bearer {access_token}"})
            resp = urlopen(req, timeout=15)
            data = json.loads(resp.read().decode())
            return {"connected": True, "phone": data.get("display_phone_number", ""), "name": data.get("verified_name", "")}
        except Exception as e:
            return {"connected": False, "error": str(e)[:150]}

    def test_connection(self, zapi_instance_id: str, zapi_token: str, zapi_client_token: str = "") -> dict:
        try:
            url = f"https://api.z-api.io/instances/{zapi_instance_id}/token/{zapi_token}/status"
            headers = {"Content-Type": "application/json"}
            if zapi_client_token:
                headers["Client-Token"] = zapi_client_token
            req = Request(url, headers=headers)
            resp = urlopen(req, timeout=15)
            data = json.loads(resp.read().decode())
            return {"connected": bool(data.get("connected")), "status": data}
        except Exception as e:
            return {"connected": False, "error": str(e)[:150]}


# Global manager
_manager = WhatsAppAgentManager()

def get_wa_manager() -> WhatsAppAgentManager:
    return _manager
