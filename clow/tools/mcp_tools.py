"""MCP Tools - list and read MCP resources."""

from __future__ import annotations
from typing import Any
from .base import BaseTool


class ListMcpResourcesTool(BaseTool):
    """List available MCP resources and servers."""

    name = "list_mcp_resources"
    description = (
        "List all available MCP (Model Context Protocol) servers and their "
        "tools. Shows server name, transport type, status, and available tools."
    )
    requires_confirmation = False
    _is_read_only = True
    _is_concurrency_safe = True
    _is_destructive = False
    _search_hint = "mcp resources servers list protocol"
    _aliases = ["mcp_list", "list_mcp"]

    def get_schema(self) -> dict:
        return {"type": "object", "properties": {}}

    def execute(self, **kwargs: Any) -> str:
        try:
            from ..mcp import MCPManager, MCPServerConfig
            from .. import config

            # Load MCP config from settings
            settings = config.load_settings()
            mcp_servers = settings.get("mcp_servers", {})

            if not mcp_servers:
                return "No MCP servers configured. Add servers to ~/.clow/settings.json under 'mcp_servers'."

            lines = [f"MCP Servers ({len(mcp_servers)}):"]
            for name, cfg_data in mcp_servers.items():
                cfg = MCPServerConfig.from_dict(name, cfg_data)
                transport = cfg.transport
                enabled = "enabled" if cfg.enabled else "disabled"
                if transport == "stdio":
                    detail = f"command: {cfg.command}"
                else:
                    detail = f"url: {cfg.url}"
                lines.append(f"  - {name} [{transport}] ({enabled}) {detail}")

            return "\n".join(lines)
        except ImportError:
            return "[ERROR] MCP module not available."
        except Exception as e:
            return f"[ERROR] Failed to list MCP resources: {e}"


class ReadMcpResourceTool(BaseTool):
    """Read content from an MCP resource by calling an MCP tool."""

    name = "read_mcp_resource"
    description = (
        "Read content from an MCP server by calling one of its tools. "
        "Specify the server name and tool name with arguments."
    )
    requires_confirmation = False
    _is_read_only = True
    _is_concurrency_safe = True
    _is_destructive = False
    _search_hint = "mcp read resource call tool"
    _aliases = ["mcp_call", "call_mcp"]

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "server_name": {
                    "type": "string",
                    "description": "Name of the MCP server.",
                },
                "tool_name": {
                    "type": "string",
                    "description": "Name of the tool to call on the MCP server.",
                },
                "arguments": {
                    "type": "object",
                    "description": "Arguments to pass to the MCP tool.",
                },
            },
            "required": ["server_name", "tool_name"],
        }

    def execute(self, **kwargs: Any) -> str:
        server_name = kwargs.get("server_name", "")
        tool_name = kwargs.get("tool_name", "")
        arguments = kwargs.get("arguments", {})

        if not server_name or not tool_name:
            return "[ERROR] server_name and tool_name are required."

        try:
            from ..mcp import MCPManager, MCPServerConfig
            from .. import config

            settings = config.load_settings()
            mcp_servers = settings.get("mcp_servers", {})

            if server_name not in mcp_servers:
                available = ", ".join(mcp_servers.keys()) if mcp_servers else "(none)"
                return f"[ERROR] MCP server '{server_name}' not found. Available: {available}"

            cfg = MCPServerConfig.from_dict(server_name, mcp_servers[server_name])

            # Determine server type and create
            if cfg.transport == "stdio":
                from ..mcp import MCPServer
                server = MCPServer(cfg)
            elif cfg.transport == "sse":
                from ..mcp import MCPSSEServer
                server = MCPSSEServer(cfg)
            else:
                from ..mcp import MCPHTTPServer
                server = MCPHTTPServer(cfg)

            if not server.start():
                return f"[ERROR] Failed to start MCP server '{server_name}'."

            try:
                result = server.call_tool(tool_name, arguments or {})
                return result
            finally:
                server.stop()

        except ImportError as e:
            return f"[ERROR] MCP module not available: {e}"
        except Exception as e:
            return f"[ERROR] MCP call failed: {e}"
