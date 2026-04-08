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
    """Registro de tools focado: WhatsApp + CRM + Sites + Design."""
    from .write import WriteTool
    from .read import ReadTool
    from .web_search import WebSearchTool
    from .web_fetch import WebFetchTool
    from .spreadsheet import SpreadsheetTool

    registry = ToolRegistry()

    # Core (3) — minimo necessario
    registry.register(WriteTool())
    registry.register(ReadTool())
    registry.register(SpreadsheetTool())

    # Web (2) — pesquisa para criar conteudo
    registry.register(WebSearchTool())
    registry.register(WebFetchTool())

    # WhatsApp (9) — automacao de atendimento
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

    # CRM Chatwoot (15) — gerenciar leads e conversas
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

    # Design (2) — criar artes e templates
    from .canva_tools import CanvaTemplateTool, DesignGeneratorTool
    registry.register(CanvaTemplateTool())
    registry.register(DesignGeneratorTool())

    return registry