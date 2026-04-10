"""Base para todas as ferramentas do Clow v0.2.0.

Registro de 32 tools: 10 core + 4 task + 9 integracoes + 9 WhatsApp
(whatsapp, http, supabase, n8n, docker, git_advanced, scraper, pdf, spreadsheet)
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any


class BaseTool(ABC):
    """Classe base abstrata para ferramentas."""

    name: str = ""
    description: str = ""
    requires_confirmation: bool = False

    @abstractmethod
    def get_schema(self) -> dict:
        """Retorna o JSON Schema da ferramenta para OpenAI function calling."""
        ...

    @abstractmethod
    def execute(self, **kwargs: Any) -> str:
        """Executa a ferramenta e retorna resultado como string."""
        ...

    def to_openai_tool(self) -> dict:
        """Converte para formato OpenAI tools."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.get_schema(),
            },
        }


class ToolRegistry:
    """Registro central de ferramentas disponíveis."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def all_tools(self) -> list[BaseTool]:
        return list(self._tools.values())

    def openai_tools(self) -> list[dict]:
        return [t.to_openai_tool() for t in self._tools.values()]

    def openai_tools_filtered(self, allowed_names: set[str]) -> list[dict]:
        """Retorna tool definitions apenas para os nomes permitidos."""
        return [
            t.to_openai_tool() for t in self._tools.values()
            if t.name in allowed_names
        ]

    def names(self) -> list[str]:
        return list(self._tools.keys())


def create_default_registry() -> ToolRegistry:
    """Cria registro com todas as ferramentas do Clow.

    Core (10) + Task (4) + Integracao (10) + WhatsApp Agent (9) +
    Chatwoot CRM (15) + Canva (2) + SSH/VPS (7) + Git (1) + Database (4) +
    Meta Ads (1) + Deploy (2) = 65 tools
    """
    from .bash import BashTool
    from .read import ReadTool
    from .write import WriteTool
    from .edit import EditTool
    from .glob_tool import GlobTool
    from .grep import GrepTool
    from .agent_tool import AgentTool
    from .web_search import WebSearchTool
    from .web_fetch import WebFetchTool
    from .notebook import NotebookEditTool
    from .task_tool import TaskCreateTool, TaskUpdateTool, TaskListTool, TaskGetTool
    from .whatsapp import WhatsAppSendTool
    from .http_request import HttpRequestTool
    from .supabase_query import SupabaseQueryTool
    from .n8n_workflow import N8nWorkflowTool
    from .docker_manage import DockerManageTool
    from .git_advanced import GitAdvancedTool
    from .scraper import ScraperTool
    from .pdf_tool import PdfTool
    from .spreadsheet import SpreadsheetTool

    registry = ToolRegistry()

    # ── Core (10) ──
    for tool_cls in (BashTool, ReadTool, WriteTool, EditTool, GlobTool,
                     GrepTool, AgentTool, WebSearchTool, WebFetchTool, NotebookEditTool):
        registry.register(tool_cls())

    # ── Task (4) ──
    for tool_cls in (TaskCreateTool, TaskUpdateTool, TaskListTool, TaskGetTool):
        registry.register(tool_cls())

    # ── Integracao (10) ──
    for tool_cls in (WhatsAppSendTool, HttpRequestTool, SupabaseQueryTool,
                     N8nWorkflowTool, DockerManageTool, GitAdvancedTool,
                     ScraperTool, PdfTool, SpreadsheetTool):
        registry.register(tool_cls())

    # ── WhatsApp Agent (9) ──
    from .whatsapp_agent_tools import (
        WhatsAppListInstancesTool, WhatsAppCreateInstanceTool, WhatsAppConnectTestTool,
        WhatsAppSavePromptTool, WhatsAppSaveRagTextTool, WhatsAppSetupWebhookTool,
        WhatsAppTestWebhookTool, WhatsAppFullTestTool, WhatsAppSendTestMessageTool,
    )
    for tool_cls in (WhatsAppListInstancesTool, WhatsAppCreateInstanceTool,
                     WhatsAppConnectTestTool, WhatsAppSavePromptTool,
                     WhatsAppSaveRagTextTool, WhatsAppSetupWebhookTool,
                     WhatsAppTestWebhookTool, WhatsAppFullTestTool,
                     WhatsAppSendTestMessageTool):
        registry.register(tool_cls())

    # ── Chatwoot CRM (15) ──
    try:
        from .chatwoot_tools import (
            ChatwootSetupTool, ChatwootTestConnectionTool, ChatwootListLabelsTool,
            ChatwootCreateLabelTool, ChatwootSearchContactTool, ChatwootCreateContactTool,
            ChatwootListConversationsTool, ChatwootAssignConversationTool,
            ChatwootAddLabelToConversationTool, ChatwootListInboxesTool,
            ChatwootListAgentsTool, ChatwootCreateTeamTool,
            ChatwootCreateAutomationTool, ChatwootListAutomationsTool,
            ChatwootReportTool,
        )
        for tool_cls in (ChatwootSetupTool, ChatwootTestConnectionTool,
                         ChatwootListLabelsTool, ChatwootCreateLabelTool,
                         ChatwootSearchContactTool, ChatwootCreateContactTool,
                         ChatwootListConversationsTool, ChatwootAssignConversationTool,
                         ChatwootAddLabelToConversationTool, ChatwootListInboxesTool,
                         ChatwootListAgentsTool, ChatwootCreateTeamTool,
                         ChatwootCreateAutomationTool, ChatwootListAutomationsTool,
                         ChatwootReportTool):
            registry.register(tool_cls())
    except ImportError:
        pass

    # ── Canva/Design (2) ──
    try:
        from .canva_tools import CanvaTemplateTool, DesignGeneratorTool
        registry.register(CanvaTemplateTool())
        registry.register(DesignGeneratorTool())
    except ImportError:
        pass

    # ── SSH & VPS (7) ──
    from .ssh_vps import (
        SshConnectTool, ManageProcessTool, ConfigureNginxTool,
        ManageSslTool, MonitorResourcesTool, ManageCronTool, BackupTool,
    )
    for tool_cls in (SshConnectTool, ManageProcessTool, ConfigureNginxTool,
                     ManageSslTool, MonitorResourcesTool, ManageCronTool, BackupTool):
        registry.register(tool_cls())

    # ── Git completo (1) ──
    from .git_ops import GitOpsTool
    registry.register(GitOpsTool())

    # ── Database (4) ──
    from .database_tools import (
        QueryPostgresTool, QueryMysqlTool, QueryRedisTool, ManageMigrationsTool,
    )
    for tool_cls in (QueryPostgresTool, QueryMysqlTool, QueryRedisTool, ManageMigrationsTool):
        registry.register(tool_cls())

    # ── Meta Ads (1) ──
    from .meta_ads_tool import MetaAdsTool
    registry.register(MetaAdsTool())

    # ── Deploy (2) ──
    from .deploy_tools import DeployVercelTool, DeployVpsTool
    registry.register(DeployVercelTool())
    registry.register(DeployVpsTool())

    return registry
