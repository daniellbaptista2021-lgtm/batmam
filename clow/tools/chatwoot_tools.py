"""Chatwoot CRM Tools — permite o agente configurar e gerenciar o CRM completo."""

import json
import urllib.request
import urllib.error
from .base import BaseTool


def _cw_request(base_url: str, token: str, path: str, method: str = "GET",
                data: dict = None, account_id: int = 1) -> dict | list | None:
    """Faz request autenticado na API do Chatwoot."""
    url = f"{base_url.rstrip('/')}/api/v1/accounts/{account_id}/{path}"
    headers = {"api_access_token": token, "Content-Type": "application/json"}
    body = json.dumps(data).encode() if data else None
    try:
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}


def _get_cw_config(tenant_id: str) -> dict | None:
    """Carrega config Chatwoot do tenant."""
    from ..chatwoot import get_crm_config
    cfg = get_crm_config(tenant_id)
    if not cfg or not cfg.chatwoot_url or not cfg.chatwoot_api_token:
        return None
    return {"url": cfg.chatwoot_url, "token": cfg.chatwoot_api_token,
            "account_id": cfg.chatwoot_account_id}


# ═══════════════════════════════════════════════════
# SETUP
# ═══════════════════════════════════════════════════

class ChatwootSetupTool(BaseTool):
    name = "chatwoot_setup"
    description = "Configura conexao com Chatwoot CRM. Forneca URL, email e senha do admin."
    def get_schema(self) -> dict:
        return {
        "type": "object",
        "properties": {
            "chatwoot_url": {"type": "string", "description": "URL do Chatwoot (ex: https://app.chatwoot.com)"},
            "email": {"type": "string", "description": "Email do admin do Chatwoot"},
            "password": {"type": "string", "description": "Senha do admin do Chatwoot"},
        },
        "required": ["chatwoot_url", "email", "password"],
    }

    def execute(self, **kwargs) -> str:
        import os
        tenant_id = kwargs.pop("tenant_id", os.getenv("CLOW_TENANT_ID", "cli-user"))
        from ..chatwoot import save_crm_config
        result = save_crm_config(
            tenant_id=tenant_id,
            url=kwargs["chatwoot_url"],
            email=kwargs["email"],
            password=kwargs["password"],
        )
        if result.get("success"):
            return f"CRM Chatwoot configurado com sucesso! Token: {result.get('token', '')[:10]}..."
        return f"Erro ao configurar: {result.get('error', 'desconhecido')}"


class ChatwootTestConnectionTool(BaseTool):
    name = "chatwoot_test_connection"
    description = "Testa se a conexao com Chatwoot esta funcionando."
    def get_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    def execute(self, **kwargs) -> str:
        import os
        tenant_id = kwargs.pop("tenant_id", os.getenv("CLOW_TENANT_ID", "cli-user"))
        cfg = _get_cw_config(tenant_id)
        if not cfg:
            return "CRM nao configurado. Use chatwoot_setup primeiro."
        profile = _cw_request(cfg["url"], cfg["token"], "profile",
                              account_id=cfg["account_id"])
        if isinstance(profile, dict) and profile.get("error"):
            return f"Erro de conexao: {profile['error']}"
        name = profile.get("name", "") if isinstance(profile, dict) else ""
        return f"Conexao OK! Logado como: {name}"


# ═══════════════════════════════════════════════════
# LABELS (ETIQUETAS)
# ═══════════════════════════════════════════════════

class ChatwootListLabelsTool(BaseTool):
    name = "chatwoot_list_labels"
    description = "Lista todas as etiquetas/labels do CRM Chatwoot."
    def get_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    def execute(self, **kwargs) -> str:
        import os
        tenant_id = kwargs.pop("tenant_id", os.getenv("CLOW_TENANT_ID", "cli-user"))
        cfg = _get_cw_config(tenant_id)
        if not cfg:
            return "CRM nao configurado."
        labels = _cw_request(cfg["url"], cfg["token"], "labels", account_id=cfg["account_id"])
        if isinstance(labels, dict) and labels.get("error"):
            return f"Erro: {labels['error']}"
        if isinstance(labels, dict):
            labels = labels.get("payload", labels.get("data", []))
        if not labels:
            return "Nenhuma etiqueta encontrada."
        lines = [f"- {l.get('title', l.get('name', '?'))} (cor: {l.get('color', '?')})" for l in labels if isinstance(l, dict)]
        return f"Etiquetas ({len(lines)}):\n" + "\n".join(lines)


class ChatwootCreateLabelTool(BaseTool):
    name = "chatwoot_create_label"
    description = "Cria uma nova etiqueta/label no CRM."
    def get_schema(self) -> dict:
        return {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Nome da etiqueta"},
            "description": {"type": "string", "description": "Descricao da etiqueta"},
            "color": {"type": "string", "description": "Cor hex (ex: #FF0000). Opcional."},
            "show_on_sidebar": {"type": "boolean", "description": "Mostrar na sidebar. Default: true"},
        },
        "required": ["title"],
    }

    def execute(self, **kwargs) -> str:
        import os
        tenant_id = kwargs.pop("tenant_id", os.getenv("CLOW_TENANT_ID", "cli-user"))
        cfg = _get_cw_config(tenant_id)
        if not cfg:
            return "CRM nao configurado."
        data = {"title": kwargs["title"]}
        if kwargs.get("description"):
            data["description"] = kwargs["description"]
        if kwargs.get("color"):
            data["color"] = kwargs["color"]
        data["show_on_sidebar"] = kwargs.get("show_on_sidebar", True)
        result = _cw_request(cfg["url"], cfg["token"], "labels", method="POST",
                             data=data, account_id=cfg["account_id"])
        if isinstance(result, dict) and result.get("error"):
            return f"Erro: {result['error']}"
        return f"Etiqueta '{kwargs['title']}' criada com sucesso!"


# ═══════════════════════════════════════════════════
# CONTACTS
# ═══════════════════════════════════════════════════

class ChatwootSearchContactTool(BaseTool):
    name = "chatwoot_search_contact"
    description = "Busca contatos no CRM por nome, email ou telefone."
    def get_schema(self) -> dict:
        return {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Termo de busca (nome, email ou telefone)"},
        },
        "required": ["query"],
    }

    def execute(self, **kwargs) -> str:
        import os
        tenant_id = kwargs.pop("tenant_id", os.getenv("CLOW_TENANT_ID", "cli-user"))
        cfg = _get_cw_config(tenant_id)
        if not cfg:
            return "CRM nao configurado."
        result = _cw_request(cfg["url"], cfg["token"],
                             f"search?q={kwargs['query']}&include_count=true",
                             account_id=cfg["account_id"])
        contacts = []
        if isinstance(result, dict):
            contacts = result.get("payload", result.get("contacts", []))
            if isinstance(contacts, dict):
                contacts = contacts.get("contacts", [])
        if not contacts:
            return "Nenhum contato encontrado."
        lines = []
        for c in contacts[:10]:
            name = c.get("name", "?")
            phone = c.get("phone_number", "")
            email = c.get("email", "")
            lines.append(f"- {name} | {phone} | {email} (id: {c.get('id', '?')})")
        return f"Contatos ({len(contacts)}):\n" + "\n".join(lines)


class ChatwootCreateContactTool(BaseTool):
    name = "chatwoot_create_contact"
    description = "Cria um novo contato no CRM."
    def get_schema(self) -> dict:
        return {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Nome do contato"},
            "email": {"type": "string", "description": "Email (opcional)"},
            "phone": {"type": "string", "description": "Telefone com DDD (ex: +5521999999999)"},
        },
        "required": ["name"],
    }

    def execute(self, **kwargs) -> str:
        import os
        tenant_id = kwargs.pop("tenant_id", os.getenv("CLOW_TENANT_ID", "cli-user"))
        cfg = _get_cw_config(tenant_id)
        if not cfg:
            return "CRM nao configurado."
        data = {"name": kwargs["name"]}
        if kwargs.get("email"):
            data["email"] = kwargs["email"]
        if kwargs.get("phone"):
            data["phone_number"] = kwargs["phone"]
        result = _cw_request(cfg["url"], cfg["token"], "contacts", method="POST",
                             data=data, account_id=cfg["account_id"])
        if isinstance(result, dict) and result.get("error"):
            return f"Erro: {result['error']}"
        return f"Contato '{kwargs['name']}' criado! ID: {result.get('id', '?')}"


# ═══════════════════════════════════════════════════
# CONVERSATIONS
# ═══════════════════════════════════════════════════

class ChatwootListConversationsTool(BaseTool):
    name = "chatwoot_list_conversations"
    description = "Lista conversas do CRM por status (open, resolved, pending)."
    def get_schema(self) -> dict:
        return {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["open", "resolved", "pending"], "description": "Filtro por status"},
            "page": {"type": "integer", "description": "Pagina (default: 1)"},
        },
        "required": [],
    }

    def execute(self, **kwargs) -> str:
        import os
        tenant_id = kwargs.pop("tenant_id", os.getenv("CLOW_TENANT_ID", "cli-user"))
        cfg = _get_cw_config(tenant_id)
        if not cfg:
            return "CRM nao configurado."
        status = kwargs.get("status", "open")
        page = kwargs.get("page", 1)
        result = _cw_request(cfg["url"], cfg["token"],
                             f"conversations?status={status}&page={page}",
                             account_id=cfg["account_id"])
        convs = []
        if isinstance(result, dict):
            convs = result.get("data", result.get("payload", []))
            if isinstance(convs, dict):
                convs = convs.get("conversations", convs.get("data", []))
        if not convs:
            return f"Nenhuma conversa {status}."
        lines = []
        for c in convs[:15]:
            cid = c.get("id", "?")
            contact = c.get("meta", {}).get("sender", {}).get("name", "?")
            inbox = c.get("inbox_id", "?")
            lines.append(f"- #{cid} | {contact} | inbox:{inbox}")
        total = result.get("data", {}).get("meta", {}).get("all_count", len(convs)) if isinstance(result, dict) else len(convs)
        return f"Conversas {status} ({total}):\n" + "\n".join(lines)


class ChatwootAssignConversationTool(BaseTool):
    name = "chatwoot_assign_conversation"
    description = "Atribui uma conversa a um agente."
    def get_schema(self) -> dict:
        return {
        "type": "object",
        "properties": {
            "conversation_id": {"type": "integer", "description": "ID da conversa"},
            "agent_id": {"type": "integer", "description": "ID do agente"},
        },
        "required": ["conversation_id", "agent_id"],
    }

    def execute(self, **kwargs) -> str:
        import os
        tenant_id = kwargs.pop("tenant_id", os.getenv("CLOW_TENANT_ID", "cli-user"))
        cfg = _get_cw_config(tenant_id)
        if not cfg:
            return "CRM nao configurado."
        result = _cw_request(cfg["url"], cfg["token"],
                             f"conversations/{kwargs['conversation_id']}/assignments",
                             method="POST", data={"assignee_id": kwargs["agent_id"]},
                             account_id=cfg["account_id"])
        if isinstance(result, dict) and result.get("error"):
            return f"Erro: {result['error']}"
        return f"Conversa #{kwargs['conversation_id']} atribuida ao agente {kwargs['agent_id']}."


class ChatwootAddLabelToConversationTool(BaseTool):
    name = "chatwoot_label_conversation"
    description = "Adiciona etiquetas a uma conversa."
    def get_schema(self) -> dict:
        return {
        "type": "object",
        "properties": {
            "conversation_id": {"type": "integer", "description": "ID da conversa"},
            "labels": {"type": "array", "items": {"type": "string"}, "description": "Lista de etiquetas"},
        },
        "required": ["conversation_id", "labels"],
    }

    def execute(self, **kwargs) -> str:
        import os
        tenant_id = kwargs.pop("tenant_id", os.getenv("CLOW_TENANT_ID", "cli-user"))
        cfg = _get_cw_config(tenant_id)
        if not cfg:
            return "CRM nao configurado."
        result = _cw_request(cfg["url"], cfg["token"],
                             f"conversations/{kwargs['conversation_id']}/labels",
                             method="POST", data={"labels": kwargs["labels"]},
                             account_id=cfg["account_id"])
        if isinstance(result, dict) and result.get("error"):
            return f"Erro: {result['error']}"
        return f"Etiquetas {kwargs['labels']} adicionadas a conversa #{kwargs['conversation_id']}."


# ═══════════════════════════════════════════════════
# INBOXES
# ═══════════════════════════════════════════════════

class ChatwootListInboxesTool(BaseTool):
    name = "chatwoot_list_inboxes"
    description = "Lista todos os canais de atendimento (inboxes) do CRM."
    def get_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    def execute(self, **kwargs) -> str:
        import os
        tenant_id = kwargs.pop("tenant_id", os.getenv("CLOW_TENANT_ID", "cli-user"))
        cfg = _get_cw_config(tenant_id)
        if not cfg:
            return "CRM nao configurado."
        result = _cw_request(cfg["url"], cfg["token"], "inboxes", account_id=cfg["account_id"])
        inboxes = result.get("payload", result) if isinstance(result, dict) else result
        if isinstance(inboxes, dict) and inboxes.get("error"):
            return f"Erro: {inboxes['error']}"
        if not inboxes or not isinstance(inboxes, list):
            return "Nenhuma inbox encontrada."
        lines = [f"- {ib.get('name', '?')} (tipo: {ib.get('channel_type', '?')}, id: {ib.get('id', '?')})" for ib in inboxes]
        return f"Inboxes ({len(lines)}):\n" + "\n".join(lines)


# ═══════════════════════════════════════════════════
# AGENTS & TEAMS
# ═══════════════════════════════════════════════════

class ChatwootListAgentsTool(BaseTool):
    name = "chatwoot_list_agents"
    description = "Lista todos os agentes/atendentes do CRM."
    def get_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    def execute(self, **kwargs) -> str:
        import os
        tenant_id = kwargs.pop("tenant_id", os.getenv("CLOW_TENANT_ID", "cli-user"))
        cfg = _get_cw_config(tenant_id)
        if not cfg:
            return "CRM nao configurado."
        result = _cw_request(cfg["url"], cfg["token"], "agents", account_id=cfg["account_id"])
        if isinstance(result, dict) and result.get("error"):
            return f"Erro: {result['error']}"
        agents = result if isinstance(result, list) else result.get("payload", [])
        if not agents:
            return "Nenhum agente encontrado."
        lines = [f"- {a.get('name', '?')} ({a.get('email', '?')}) | role: {a.get('role', '?')} | id: {a.get('id', '?')}" for a in agents]
        return f"Agentes ({len(lines)}):\n" + "\n".join(lines)


class ChatwootCreateTeamTool(BaseTool):
    name = "chatwoot_create_team"
    description = "Cria uma equipe no CRM."
    def get_schema(self) -> dict:
        return {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Nome da equipe"},
            "description": {"type": "string", "description": "Descricao"},
        },
        "required": ["name"],
    }

    def execute(self, **kwargs) -> str:
        import os
        tenant_id = kwargs.pop("tenant_id", os.getenv("CLOW_TENANT_ID", "cli-user"))
        cfg = _get_cw_config(tenant_id)
        if not cfg:
            return "CRM nao configurado."
        data = {"name": kwargs["name"]}
        if kwargs.get("description"):
            data["description"] = kwargs["description"]
        result = _cw_request(cfg["url"], cfg["token"], "teams", method="POST",
                             data=data, account_id=cfg["account_id"])
        if isinstance(result, dict) and result.get("error"):
            return f"Erro: {result['error']}"
        return f"Equipe '{kwargs['name']}' criada! ID: {result.get('id', '?')}"


# ═══════════════════════════════════════════════════
# AUTOMATIONS
# ═══════════════════════════════════════════════════

class ChatwootCreateAutomationTool(BaseTool):
    name = "chatwoot_create_automation"
    description = "Cria uma automacao no CRM (ex: atribuir agente automaticamente, adicionar etiqueta, enviar webhook)."
    def get_schema(self) -> dict:
        return {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Nome da automacao"},
            "description": {"type": "string", "description": "Descricao"},
            "event_name": {"type": "string", "enum": ["conversation_created", "conversation_updated", "message_created", "conversation_opened"], "description": "Evento que dispara a automacao"},
            "conditions": {"type": "array", "description": "Condicoes (ex: [{\"attribute_key\": \"status\", \"filter_operator\": \"equal_to\", \"values\": [\"open\"]}])"},
            "actions": {"type": "array", "description": "Acoes (ex: [{\"action_name\": \"assign_team\", \"action_params\": [1]}, {\"action_name\": \"add_label\", \"action_params\": [\"vip\"]}])"},
        },
        "required": ["name", "event_name", "actions"],
    }

    def execute(self, **kwargs) -> str:
        import os
        tenant_id = kwargs.pop("tenant_id", os.getenv("CLOW_TENANT_ID", "cli-user"))
        cfg = _get_cw_config(tenant_id)
        if not cfg:
            return "CRM nao configurado."
        data = {
            "automation_rule": {
                "name": kwargs["name"],
                "description": kwargs.get("description", ""),
                "event_name": kwargs["event_name"],
                "conditions": kwargs.get("conditions", []),
                "actions": kwargs["actions"],
            }
        }
        result = _cw_request(cfg["url"], cfg["token"], "automation_rules", method="POST",
                             data=data, account_id=cfg["account_id"])
        if isinstance(result, dict) and result.get("error"):
            return f"Erro: {result['error']}"
        return f"Automacao '{kwargs['name']}' criada!"


class ChatwootListAutomationsTool(BaseTool):
    name = "chatwoot_list_automations"
    description = "Lista todas as automacoes do CRM."
    def get_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    def execute(self, **kwargs) -> str:
        import os
        tenant_id = kwargs.pop("tenant_id", os.getenv("CLOW_TENANT_ID", "cli-user"))
        cfg = _get_cw_config(tenant_id)
        if not cfg:
            return "CRM nao configurado."
        result = _cw_request(cfg["url"], cfg["token"], "automation_rules",
                             account_id=cfg["account_id"])
        if isinstance(result, dict) and result.get("error"):
            return f"Erro: {result['error']}"
        rules = result.get("payload", result) if isinstance(result, dict) else result
        if not rules or not isinstance(rules, list):
            return "Nenhuma automacao encontrada."
        lines = [f"- {r.get('name', '?')} | evento: {r.get('event_name', '?')} | ativa: {r.get('active', '?')}" for r in rules]
        return f"Automacoes ({len(lines)}):\n" + "\n".join(lines)


# ═══════════════════════════════════════════════════
# REPORTS
# ═══════════════════════════════════════════════════

class ChatwootReportTool(BaseTool):
    name = "chatwoot_report"
    description = "Gera relatorio resumido do CRM: conversas abertas, contatos, agentes, inboxes."
    def get_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    def execute(self, **kwargs) -> str:
        import os
        tenant_id = kwargs.pop("tenant_id", os.getenv("CLOW_TENANT_ID", "cli-user"))
        cfg = _get_cw_config(tenant_id)
        if not cfg:
            return "CRM nao configurado."
        url, token, aid = cfg["url"], cfg["token"], cfg["account_id"]
        open_c = _cw_request(url, token, "conversations?status=open&page=1", account_id=aid)
        resolved = _cw_request(url, token, "conversations?status=resolved&page=1", account_id=aid)
        contacts = _cw_request(url, token, "contacts?page=1", account_id=aid)
        agents = _cw_request(url, token, "agents", account_id=aid)
        inboxes = _cw_request(url, token, "inboxes", account_id=aid)
        labels = _cw_request(url, token, "labels", account_id=aid)

        def _count(r):
            if isinstance(r, dict):
                m = r.get("data", {}).get("meta", {})
                return m.get("all_count", len(r.get("data", r.get("payload", []))))
            return len(r) if isinstance(r, list) else 0

        n_agents = len(agents) if isinstance(agents, list) else len(agents.get("payload", [])) if isinstance(agents, dict) else 0
        n_inboxes = len(inboxes.get("payload", inboxes)) if isinstance(inboxes, (dict, list)) else 0
        n_labels = len(labels.get("payload", labels)) if isinstance(labels, (dict, list)) else 0

        return (f"=== Relatorio CRM ===\n"
                f"Conversas abertas: {_count(open_c)}\n"
                f"Conversas resolvidas: {_count(resolved)}\n"
                f"Contatos: {_count(contacts)}\n"
                f"Agentes: {n_agents}\n"
                f"Inboxes: {n_inboxes}\n"
                f"Etiquetas: {n_labels}")
