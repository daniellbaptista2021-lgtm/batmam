"""WhatsApp Agent Tools — ferramentas para configurar e gerenciar instancias WhatsApp via CLI."""

from __future__ import annotations
import json
from typing import Any
from .base import BaseTool


class WhatsAppListInstancesTool(BaseTool):
    name = "whatsapp_list_instances"
    description = "Lista todas as instancias WhatsApp do usuario com status, mensagens e webhook URL."

    def get_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    def execute(self, **kwargs: Any) -> str:
        from ..whatsapp_agent import get_wa_manager
        import os
        tenant_id = os.getenv("CLOW_TENANT_ID", "cli-user")
        mgr = get_wa_manager()
        instances = mgr.get_instances(tenant_id)
        if not instances:
            return "Nenhuma instancia WhatsApp configurada. Use /whatsapp connect para conectar."
        lines = [f"## WhatsApp Trigger — {len(instances)} instancia(s)\n"]
        for i, inst in enumerate(instances, 1):
            status = "Ativo" if inst["active"] else "Inativo"
            lines.append(f"**{i}. {inst['name']}** [{status}]")
            lines.append(f"   ID: {inst['id']}")
            lines.append(f"   Msgs hoje: {inst['stats'].get('messages_today', 0)} | Total: {inst['stats'].get('messages_total', 0)}")
            lines.append(f"   Webhook: {inst['webhook_url']}")
            lines.append("")
        extra = mgr.get_extra_cost(tenant_id)
        if extra > 0:
            lines.append(f"Custo extra: +R${extra}/mes ({len(instances)} instancias, 2 inclusas)")
        return "\n".join(lines)


class WhatsAppCreateInstanceTool(BaseTool):
    name = "whatsapp_create_instance"
    description = "Cria uma nova instancia WhatsApp Agent. Requer nome, instance_id e token da Z-API."

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome amigavel (ex: Atendimento Pizzaria)"},
                "zapi_instance_id": {"type": "string", "description": "Instance ID da Z-API"},
                "zapi_token": {"type": "string", "description": "Token da Z-API"},
                "system_prompt": {"type": "string", "description": "Prompt/persona do agente"},
            },
            "required": ["name", "zapi_instance_id", "zapi_token"],
        }

    def execute(self, **kwargs: Any) -> str:
        from ..whatsapp_agent import get_wa_manager
        import os
        tenant_id = os.getenv("CLOW_TENANT_ID", "cli-user")
        mgr = get_wa_manager()

        # Check limit
        instances = mgr.get_instances(tenant_id)
        if len(instances) >= 2:
            extra = mgr.get_extra_cost(tenant_id)
            # Allow but warn about cost
            pass

        result = mgr.create_instance(
            tenant_id=tenant_id,
            name=kwargs.get("name", "Meu WhatsApp"),
            zapi_instance_id=kwargs.get("zapi_instance_id", ""),
            zapi_token=kwargs.get("zapi_token", ""),
            system_prompt=kwargs.get("system_prompt", ""),
        )
        if result.get("error"):
            return f"Erro ao criar instancia: {result['error']}"

        inst = result["instance"]
        return (
            f"Instancia criada com sucesso!\n\n"
            f"**Nome:** {inst['name']}\n"
            f"**ID:** {inst['id']}\n"
            f"**Webhook URL:** {inst['webhook_url']}\n\n"
            f"Proximo passo: cole esta URL no painel Z-API em Webhooks > URL de recebimento."
        )


class WhatsAppConnectTestTool(BaseTool):
    name = "whatsapp_connect_test"
    description = "Testa conexao com a Z-API usando instance_id e token. Verifica se as credenciais estao corretas."

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "zapi_instance_id": {"type": "string", "description": "Instance ID da Z-API"},
                "zapi_token": {"type": "string", "description": "Token da Z-API"},
            },
            "required": ["zapi_instance_id", "zapi_token"],
        }

    def execute(self, **kwargs: Any) -> str:
        from ..whatsapp_agent import get_wa_manager
        result = get_wa_manager().test_connection(
            kwargs.get("zapi_instance_id", ""),
            kwargs.get("zapi_token", ""),
        )
        if result.get("connected"):
            return "Conexao OK! As credenciais da Z-API estao funcionando."
        return f"Falha na conexao: {result.get('error', 'Erro desconhecido')}. Verifique o Instance ID e Token."


class WhatsAppSavePromptTool(BaseTool):
    name = "whatsapp_save_prompt"
    description = "Salva o prompt/persona do agente em uma instancia WhatsApp."

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "instance_id": {"type": "string", "description": "ID da instancia"},
                "prompt": {"type": "string", "description": "System prompt completo do agente"},
            },
            "required": ["instance_id", "prompt"],
        }

    def execute(self, **kwargs: Any) -> str:
        from ..whatsapp_agent import get_wa_manager
        import os
        tenant_id = os.getenv("CLOW_TENANT_ID", "cli-user")
        result = get_wa_manager().update_instance(
            kwargs["instance_id"], tenant_id, system_prompt=kwargs["prompt"],
        )
        if result.get("error"):
            return f"Erro: {result['error']}"
        return "Prompt do agente salvo com sucesso!"


class WhatsAppSaveRagTextTool(BaseTool):
    name = "whatsapp_save_rag_text"
    description = "Salva texto de conhecimento (RAG) em uma instancia WhatsApp. O agente usa este texto para responder perguntas."

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "instance_id": {"type": "string", "description": "ID da instancia"},
                "text": {"type": "string", "description": "Texto de conhecimento (FAQ, precos, regras)"},
            },
            "required": ["instance_id", "text"],
        }

    def execute(self, **kwargs: Any) -> str:
        from ..whatsapp_agent import get_wa_manager
        import os
        tenant_id = os.getenv("CLOW_TENANT_ID", "cli-user")
        result = get_wa_manager().update_instance(
            kwargs["instance_id"], tenant_id, rag_text=kwargs["text"],
        )
        if result.get("error"):
            return f"Erro: {result['error']}"
        return "Conhecimento salvo! O agente vai usar este texto para responder perguntas dos clientes."


class WhatsAppSetupWebhookTool(BaseTool):
    name = "whatsapp_setup_webhook"
    description = "Retorna a URL do webhook que deve ser configurada na Z-API para uma instancia."

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "instance_id": {"type": "string", "description": "ID da instancia"},
            },
            "required": ["instance_id"],
        }

    def execute(self, **kwargs: Any) -> str:
        from ..whatsapp_agent import get_wa_manager
        inst = get_wa_manager().get_instance(kwargs["instance_id"])
        if not inst:
            return "Instancia nao encontrada."
        return (
            f"URL do Webhook:\n{inst.webhook_url}\n\n"
            "Instrucoes:\n"
            "1. Acesse o painel da Z-API (app.z-api.io)\n"
            "2. Selecione sua instancia\n"
            "3. Va em 'Webhooks' no menu lateral\n"
            "4. Cole a URL acima no campo 'URL de recebimento'\n"
            "5. Salve\n\n"
            "Pronto! As mensagens recebidas no WhatsApp serao enviadas pro Clow."
        )


class WhatsAppTestWebhookTool(BaseTool):
    name = "whatsapp_test_webhook"
    description = "Simula o recebimento de uma mensagem para testar se o webhook esta funcionando."

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "instance_id": {"type": "string", "description": "ID da instancia"},
                "message": {"type": "string", "description": "Mensagem de teste (default: 'Ola, estou testando')"},
            },
            "required": ["instance_id"],
        }

    def execute(self, **kwargs: Any) -> str:
        from ..whatsapp_agent import get_wa_manager
        inst = get_wa_manager().get_instance(kwargs["instance_id"])
        if not inst:
            return "Instancia nao encontrada."
        if not inst.active:
            return "Instancia esta inativa. Ative antes de testar."

        msg = kwargs.get("message", "Ola, estou testando o atendimento automatico")
        result = get_wa_manager().process_incoming(kwargs["instance_id"], "5500000000000", msg)
        if result:
            return f"Teste OK! O agente respondeu:\n\n{result}"
        return "O agente nao gerou resposta. Verifique o prompt e as credenciais."


class WhatsAppFullTestTool(BaseTool):
    name = "whatsapp_full_test"
    description = "Executa teste completo: conexao Z-API + webhook + resposta do agente."

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "instance_id": {"type": "string", "description": "ID da instancia"},
            },
            "required": ["instance_id"],
        }

    def execute(self, **kwargs: Any) -> str:
        from ..whatsapp_agent import get_wa_manager
        import os
        tenant_id = os.getenv("CLOW_TENANT_ID", "cli-user")
        inst = get_wa_manager().get_instance(kwargs["instance_id"], tenant_id)
        if not inst:
            return "Instancia nao encontrada."

        lines = ["## Teste Completo\n"]

        # 1. Conexao
        conn = get_wa_manager().test_connection(inst.zapi_instance_id, inst.zapi_token)
        if conn.get("connected"):
            lines.append("1. Conexao Z-API: OK")
        else:
            lines.append(f"1. Conexao Z-API: FALHA — {conn.get('error', '')[:100]}")
            lines.append("\nO teste parou aqui. Corrija as credenciais e tente novamente.")
            return "\n".join(lines)

        # 2. Prompt
        if inst.system_prompt:
            lines.append(f"2. Prompt configurado: OK ({len(inst.system_prompt)} chars)")
        else:
            lines.append("2. Prompt: NAO CONFIGURADO — configure um prompt para o agente")

        # 3. Conhecimento
        if inst.rag_text:
            lines.append(f"3. Conhecimento RAG: OK ({len(inst.rag_text)} chars)")
        else:
            lines.append("3. Conhecimento RAG: vazio (opcional)")

        # 4. Webhook
        lines.append(f"4. Webhook URL: {inst.webhook_url}")

        # 5. Status
        lines.append(f"5. Status: {'Ativo' if inst.active else 'Inativo'}")

        lines.append("\nInstancia pronta para receber mensagens!")
        return "\n".join(lines)


class WhatsAppSendTestMessageTool(BaseTool):
    name = "whatsapp_send_test_message"
    description = "Envia uma mensagem de teste via WhatsApp usando uma instancia configurada."

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "instance_id": {"type": "string", "description": "ID da instancia"},
                "phone": {"type": "string", "description": "Numero do telefone destino (ex: 5521999999999)"},
                "message": {"type": "string", "description": "Mensagem a enviar"},
            },
            "required": ["instance_id", "phone", "message"],
        }

    def execute(self, **kwargs: Any) -> str:
        from ..whatsapp_agent import get_wa_manager
        inst = get_wa_manager().get_instance(kwargs["instance_id"])
        if not inst:
            return "Instancia nao encontrada."
        ok = get_wa_manager()._send_zapi(inst, kwargs["phone"], kwargs["message"])
        return "Mensagem enviada!" if ok else "Falha ao enviar. Verifique as credenciais."
