"""Base para todas as ferramentas do Clow v0.2.0.

Registro de 32 tools: 10 core + 4 task + 9 integracoes + 9 WhatsApp
(whatsapp, http, supabase, n8n, docker, git_advanced, scraper, pdf, spreadsheet)

Tool System (Claude Code Ep.02):
- Behavioral flags (isReadOnly, isConcurrencySafe, isDestructive)
- buildTool() factory with fail-closed defaults
- Tool filtering pipeline (deny -> mode -> sort)
- ToolSearch/deferred loading support
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Callable


class BaseTool(ABC):
    """Tool interface with behavioral flags (Claude Code architecture).

    Every tool declares behavioral flags that determine:
    - Whether it needs permission (isReadOnly)
    - Whether it can run in parallel (isConcurrencySafe)
    - Whether it's irreversible (isDestructive)

    Defaults are fail-closed: assume NOT safe, NOT read-only, NOT destructive.
    """

    name: str = ""
    description: str = ""
    requires_confirmation: bool = False

    # Behavioral flags (Claude Code pattern — fail-closed defaults)
    _is_read_only: bool = False          # Assume writes (safer)
    _is_concurrency_safe: bool = False   # Assume NOT safe (serialize)
    _is_destructive: bool = False        # Assume not destructive
    _is_enabled: bool = True
    _search_hint: str = ""               # Keyword for ToolSearch discovery
    _aliases: list[str] = []             # Legacy name support

    def is_read_only(self, **kwargs) -> bool:
        """Is this tool call read-only? Input-dependent.
        Read-only tools skip permission checks.
        """
        return self._is_read_only

    def is_concurrency_safe(self, **kwargs) -> bool:
        """Can this tool run in parallel with others?
        Fail-closed: defaults to False (serialize).
        """
        return self._is_concurrency_safe

    def is_destructive(self, **kwargs) -> bool:
        """Is this action irreversible (delete, overwrite)?"""
        return self._is_destructive

    def is_enabled(self) -> bool:
        """Is this tool currently enabled?"""
        return self._is_enabled

    def check_permissions(self, **kwargs) -> dict:
        """Tool-specific permission check. Returns {behavior: 'allow'|'ask'|'deny'}."""
        return {"behavior": "allow"}

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

    # ── Tool filtering pipeline (Claude Code Ep.02) ──

    def filter_by_deny_rules(self, denied_names: set[str]) -> list[BaseTool]:
        """Filter out denied tools."""
        return [t for t in self._tools.values() if t.name not in denied_names]

    def filter_by_mode(self, mode: str = "default") -> list[BaseTool]:
        """Filter tools by permission mode."""
        if mode == "plan":
            return [t for t in self._tools.values() if t.is_read_only()]
        return list(self._tools.values())

    def get_read_only_tools(self) -> list[str]:
        """Get names of all read-only tools."""
        return [t.name for t in self._tools.values() if t.is_read_only()]

    def get_concurrency_safe_tools(self) -> list[str]:
        """Get names of tools safe for parallel execution."""
        return [t.name for t in self._tools.values() if t.is_concurrency_safe()]

    def get_destructive_tools(self) -> list[str]:
        """Get names of destructive tools."""
        return [t.name for t in self._tools.values() if t.is_destructive()]

    def get_enabled_tools(self) -> list[BaseTool]:
        """Get only enabled tools."""
        return [t for t in self._tools.values() if t.is_enabled()]

    def filter_pipeline(
        self,
        denied_names: set[str] | None = None,
        mode: str = "default",
        sort_key: str = "name",
    ) -> list[BaseTool]:
        """Full filtering pipeline: deny -> mode -> sort.

        1. Remove denied tools
        2. Filter by mode (plan = read-only only)
        3. Sort by key
        """
        tools = list(self._tools.values())

        # Step 1: Deny filter
        if denied_names:
            tools = [t for t in tools if t.name not in denied_names]

        # Step 2: Mode filter
        if mode == "plan":
            tools = [t for t in tools if t.is_read_only()]

        # Step 3: Sort
        if sort_key == "name":
            tools.sort(key=lambda t: t.name)
        elif sort_key == "read_first":
            tools.sort(key=lambda t: (not t.is_read_only(), t.name))

        return tools

    def search(self, query: str) -> list[BaseTool]:
        """ToolSearch -- find tools by name, alias, or search hint."""
        query_lower = query.lower()
        results = []
        for tool in self._tools.values():
            # Match by name
            if query_lower in tool.name.lower():
                results.append(tool)
                continue
            # Match by alias
            if hasattr(tool, "_aliases") and any(
                query_lower in alias.lower() for alias in tool._aliases
            ):
                results.append(tool)
                continue
            # Match by search hint
            if hasattr(tool, "_search_hint") and query_lower in tool._search_hint.lower():
                results.append(tool)
                continue
            # Match by description
            if query_lower in tool.description.lower():
                results.append(tool)
                continue
        return results


def build_tool(
    name: str,
    description: str,
    schema: dict,
    execute_fn: Callable[..., str],
    is_read_only: bool = False,
    is_concurrency_safe: bool = False,
    is_destructive: bool = False,
    requires_confirmation: bool = False,
    search_hint: str = "",
    aliases: list[str] | None = None,
) -> BaseTool:
    """Factory function with fail-closed defaults (Claude Code pattern).

    A tool that forgets isConcurrencySafe defaults to False (serialize).
    A tool that forgets isReadOnly defaults to False (requires permission).
    """

    class DynamicTool(BaseTool):
        def get_schema(self) -> dict:
            return self._schema

        def execute(self, **kwargs: Any) -> str:
            return self._execute_fn(**kwargs)

    tool = DynamicTool()
    tool.name = name
    tool.description = description
    tool._schema = schema
    tool._execute_fn = execute_fn
    tool._is_read_only = is_read_only
    tool._is_concurrency_safe = is_concurrency_safe
    tool._is_destructive = is_destructive
    tool.requires_confirmation = requires_confirmation
    tool._search_hint = search_hint
    tool._aliases = aliases or []

    return tool


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
