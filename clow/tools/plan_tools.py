"""Plan Mode & Tool Search tools - Claude Code architecture."""

from __future__ import annotations
from typing import Any
from .base import BaseTool


class EnterPlanModeTool(BaseTool):
    """Sets agent to plan-only mode (read-only tools only)."""

    name = "enter_plan_mode"
    description = (
        "Enter plan mode. In plan mode, only read-only tools are available. "
        "Use this when you want to analyze and plan without making changes."
    )
    requires_confirmation = False
    _is_read_only = True
    _is_concurrency_safe = True
    _is_destructive = False
    _search_hint = "plan mode read only analyze"
    _aliases = ["plan_mode"]

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Reason for entering plan mode (optional).",
                },
            },
        }

    def execute(self, **kwargs: Any) -> str:
        reason = kwargs.get("reason", "")
        import clow.tools.plan_tools as _mod
        _mod._PLAN_MODE = True
        msg = "Entered plan mode. Only read-only tools are now available."
        if reason:
            msg += f" Reason: {reason}"
        return msg


# Module-level flag
_PLAN_MODE = False


def is_plan_mode() -> bool:
    """Check if plan mode is active."""
    return _PLAN_MODE


class ExitPlanModeTool(BaseTool):
    """Exits plan mode, re-enables all tools."""

    name = "exit_plan_mode"
    description = "Exit plan mode. All tools become available again."
    requires_confirmation = False
    _is_read_only = True
    _is_concurrency_safe = True
    _is_destructive = False
    _search_hint = "exit plan mode resume"
    _aliases = ["resume_mode"]

    def get_schema(self) -> dict:
        return {"type": "object", "properties": {}}

    def execute(self, **kwargs: Any) -> str:
        import clow.tools.plan_tools as _mod
        _mod._PLAN_MODE = False
        return "Exited plan mode. All tools are now available."


class ToolSearchTool(BaseTool):
    """Search available tools by keyword."""

    name = "tool_search"
    description = (
        "Search available tools by keyword. Returns matching tool names "
        "and descriptions. Use to discover tools for a specific task."
    )
    requires_confirmation = False
    _is_read_only = True
    _is_concurrency_safe = True
    _is_destructive = False
    _search_hint = "search find discover tool"
    _aliases = ["ToolSearch", "find_tool"]
    _registry = None

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query to find tools. Matches name, description, aliases.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results. Default: 10.",
                },
            },
            "required": ["query"],
        }

    def execute(self, **kwargs: Any) -> str:
        query = kwargs.get("query", "")
        max_results = kwargs.get("max_results", 10)

        if not query:
            return "[ERROR] query is required."

        registry = self._registry
        if registry is None:
            try:
                from .base import create_default_registry
                registry = create_default_registry()
            except Exception:
                pass

        if registry is None:
            return "[ERROR] Tool registry not available."

        results = registry.search(query)[:max_results]
        if not results:
            return f"No tools found matching '{query}'."

        lines = [f"Found {len(results)} tool(s) matching '{query}':"]
        for tool in results:
            flags = []
            if tool.is_read_only():
                flags.append("read-only")
            if tool.is_concurrency_safe():
                flags.append("concurrent")
            if tool.is_destructive():
                flags.append("destructive")
            flag_str = f" [{', '.join(flags)}]" if flags else ""
            lines.append(f"  - {tool.name}{flag_str}: {tool.description[:120]}")

        return "\n".join(lines)
