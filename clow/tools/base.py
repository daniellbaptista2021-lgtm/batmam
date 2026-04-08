"""Base para todas as ferramentas do Clow v0.2.0.

Registro de 33 tools: 10 core + 4 task + 10 integracoes + 9 WhatsApp
(whatsapp, http, supabase, n8n, docker, git_advanced, scraper, image_gen, pdf, spreadsheet)
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

    def names(self) -> list[str]:
        return list(self._tools.keys())


def create_default_registry() -> ToolRegistry:
    """Cria registro com todas as 33 ferramentas."""
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
    from .image_gen import ImageGenTool
    from .pdf_tool import PdfTool
    from .spreadsheet import SpreadsheetTool

    registry = ToolRegistry()
    # Core tools (10 originais)
    registry.register(BashTool())
    registry.register(ReadTool())
    registry.register(WriteTool())
    registry.register(EditTool())
    registry.register(GlobTool())
    registry.register(GrepTool())
    registry.register(AgentTool())
    registry.register(WebSearchTool())
    registry.register(WebFetchTool())
    registry.register(NotebookEditTool())
    # Task tools (4)
    registry.register(TaskCreateTool())
    registry.register(TaskUpdateTool())
    registry.register(TaskListTool())
    registry.register(TaskGetTool())
    # Novas tools (10)
    registry.register(WhatsAppSendTool())
    registry.register(HttpRequestTool())
    registry.register(SupabaseQueryTool())
    registry.register(N8nWorkflowTool())
    registry.register(DockerManageTool())
    registry.register(GitAdvancedTool())
    registry.register(ScraperTool())
    registry.register(ImageGenTool())
    registry.register(PdfTool())
    registry.register(SpreadsheetTool())
    # WhatsApp Agent tools (9)
    from .whatsapp_agent_tools import (
        WhatsAppListInstancesTool, WhatsAppCreateInstanceTool, WhatsAppConnectTestTool,
        WhatsAppSavePromptTool, WhatsAppSaveRagTextTool, WhatsAppSetupWebhookTool,
        WhatsAppTestWebhookTool, WhatsAppFullTestTool, WhatsAppSendTestMessageTool,
    )
    registry.register(WhatsAppListInstancesTool())
    registry.register(WhatsAppCreateInstanceTool())
    registry.register(WhatsAppConnectTestTool())
    registry.register(WhatsAppSavePromptTool())
    registry.register(WhatsAppSaveRagTextTool())
    registry.register(WhatsAppSetupWebhookTool())
    registry.register(WhatsAppTestWebhookTool())
    registry.register(WhatsAppFullTestTool())
    registry.register(WhatsAppSendTestMessageTool())
# Chatwoot CRM tools (15)    from .chatwoot_tools import (        ChatwootSetupTool, ChatwootTestConnectionTool,        ChatwootListLabelsTool, ChatwootCreateLabelTool,        ChatwootSearchContactTool, ChatwootCreateContactTool,        ChatwootListConversationsTool, ChatwootAssignConversationTool,        ChatwootAddLabelToConversationTool,        ChatwootListInboxesTool, ChatwootListAgentsTool,        ChatwootCreateTeamTool, ChatwootCreateAutomationTool,        ChatwootListAutomationsTool, ChatwootReportTool,    )    registry.register(ChatwootSetupTool())    registry.register(ChatwootTestConnectionTool())    registry.register(ChatwootListLabelsTool())    registry.register(ChatwootCreateLabelTool())    registry.register(ChatwootSearchContactTool())    registry.register(ChatwootCreateContactTool())    registry.register(ChatwootListConversationsTool())    registry.register(ChatwootAssignConversationTool())    registry.register(ChatwootAddLabelToConversationTool())    registry.register(ChatwootListInboxesTool())    registry.register(ChatwootListAgentsTool())    registry.register(ChatwootCreateTeamTool())    registry.register(ChatwootCreateAutomationTool())    registry.register(ChatwootListAutomationsTool())    registry.register(ChatwootReportTool())
    # Chatwoot CRM tools (15)
    from .chatwoot_tools import (
        ChatwootSetupTool, ChatwootTestConnectionTool,
        ChatwootListLabelsTool, ChatwootCreateLabelTool,
        ChatwootSearchContactTool, ChatwootCreateContactTool,
        ChatwootListConversationsTool, ChatwootAssignConversationTool,
        ChatwootAddLabelToConversationTool,
        ChatwootListInboxesTool, ChatwootListAgentsTool,
        ChatwootCreateTeamTool, ChatwootCreateAutomationTool,
        ChatwootListAutomationsTool, ChatwootReportTool,
    )
    registry.register(ChatwootSetupTool())
    registry.register(ChatwootTestConnectionTool())
    registry.register(ChatwootListLabelsTool())
    registry.register(ChatwootCreateLabelTool())
    registry.register(ChatwootSearchContactTool())
    registry.register(ChatwootCreateContactTool())
    registry.register(ChatwootListConversationsTool())
    registry.register(ChatwootAssignConversationTool())
    registry.register(ChatwootAddLabelToConversationTool())
    registry.register(ChatwootListInboxesTool())
    registry.register(ChatwootListAgentsTool())
    registry.register(ChatwootCreateTeamTool())
    registry.register(ChatwootCreateAutomationTool())
    registry.register(ChatwootListAutomationsTool())
    registry.register(ChatwootReportTool())
    return registry
