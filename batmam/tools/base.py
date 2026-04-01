"""Base para todas as ferramentas do Batmam."""

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
    """Cria registro com todas as ferramentas padrão."""
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

    registry = ToolRegistry()
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
    return registry
