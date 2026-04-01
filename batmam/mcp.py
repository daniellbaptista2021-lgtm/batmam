"""MCP (Model Context Protocol) Client do Batmam.

Conecta a servidores MCP via stdio ou SSE e registra ferramentas dinamicamente.
Configuração em ~/.batmam/settings.json:

{
  "mcp_servers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user"],
      "env": {}
    },
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {"GITHUB_TOKEN": "ghp_xxx"}
    }
  }
}
"""

from __future__ import annotations
import subprocess
import json
import threading
import queue
import os
import sys
from typing import Any
from dataclasses import dataclass, field
from .tools.base import BaseTool, ToolRegistry
from . import config


@dataclass
class MCPServerConfig:
    """Configuração de um servidor MCP."""
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True

    @classmethod
    def from_dict(cls, name: str, data: dict) -> MCPServerConfig:
        return cls(
            name=name,
            command=data.get("command", ""),
            args=data.get("args", []),
            env=data.get("env", {}),
            enabled=data.get("enabled", True),
        )


class MCPServer:
    """Conexão a um servidor MCP via stdio (JSON-RPC)."""

    def __init__(self, cfg: MCPServerConfig) -> None:
        self.cfg = cfg
        self.process: subprocess.Popen | None = None
        self.tools: list[dict] = []
        self._request_id = 0
        self._lock = threading.Lock()
        self._responses: dict[int, Any] = {}
        self._reader_thread: threading.Thread | None = None
        self._running = False

    def start(self) -> bool:
        """Inicia o processo do servidor MCP."""
        if not self.cfg.command:
            return False

        env = {**os.environ, **self.cfg.env}

        try:
            cmd = [self.cfg.command] + self.cfg.args
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                bufsize=0,
            )
            self._running = True

            # Thread para ler respostas
            self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
            self._reader_thread.start()

            # Inicializa protocolo
            return self._initialize()

        except Exception as e:
            self._running = False
            return False

    def stop(self) -> None:
        """Para o servidor MCP."""
        self._running = False
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None

    def _initialize(self) -> bool:
        """Envia initialize e lista tools."""
        # Initialize
        resp = self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "batmam", "version": "0.1.0"},
        })

        if resp is None:
            return False

        # Notifica initialized
        self._send_notification("notifications/initialized", {})

        # Lista tools
        tools_resp = self._send_request("tools/list", {})
        if tools_resp and "tools" in tools_resp:
            self.tools = tools_resp["tools"]

        return True

    def call_tool(self, name: str, arguments: dict) -> str:
        """Chama uma ferramenta MCP."""
        resp = self._send_request("tools/call", {
            "name": name,
            "arguments": arguments,
        })

        if resp is None:
            return "[ERROR] Sem resposta do servidor MCP."

        if "content" in resp:
            parts = []
            for item in resp["content"]:
                if item.get("type") == "text":
                    parts.append(item.get("text", ""))
                elif item.get("type") == "image":
                    parts.append(f"[imagem: {item.get('mimeType', 'unknown')}]")
            return "\n".join(parts) if parts else "(sem conteúdo)"

        return json.dumps(resp, indent=2)

    def _send_request(self, method: str, params: dict, timeout: float = 30) -> dict | None:
        """Envia JSON-RPC request e espera resposta."""
        with self._lock:
            self._request_id += 1
            req_id = self._request_id

        msg = json.dumps({
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        })

        try:
            if self.process and self.process.stdin:
                self.process.stdin.write(msg + "\n")
                self.process.stdin.flush()
        except Exception:
            return None

        # Espera resposta
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if req_id in self._responses:
                    resp = self._responses.pop(req_id)
                    if "error" in resp:
                        return None
                    return resp.get("result", resp)
            time.sleep(0.05)

        return None

    def _send_notification(self, method: str, params: dict) -> None:
        """Envia notificação (sem esperar resposta)."""
        msg = json.dumps({
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        })
        try:
            if self.process and self.process.stdin:
                self.process.stdin.write(msg + "\n")
                self.process.stdin.flush()
        except Exception:
            pass

    def _read_loop(self) -> None:
        """Thread que lê respostas do servidor."""
        while self._running and self.process and self.process.stdout:
            try:
                line = self.process.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                if "id" in data:
                    with self._lock:
                        self._responses[data["id"]] = data
            except json.JSONDecodeError:
                continue
            except Exception:
                break


class MCPToolProxy(BaseTool):
    """Proxy que expõe uma tool MCP como BaseTool do Batmam."""

    requires_confirmation = True

    def __init__(self, server: MCPServer, tool_def: dict) -> None:
        self.server = server
        self.tool_def = tool_def
        self.name = f"mcp__{server.cfg.name}__{tool_def['name']}"
        self.description = tool_def.get("description", f"MCP tool: {tool_def['name']}")

    def get_schema(self) -> dict:
        return self.tool_def.get("inputSchema", {"type": "object", "properties": {}})

    def execute(self, **kwargs: Any) -> str:
        return self.server.call_tool(self.tool_def["name"], kwargs)


class MCPManager:
    """Gerencia todos os servidores MCP."""

    def __init__(self) -> None:
        self._servers: dict[str, MCPServer] = {}

    def load_from_settings(self) -> None:
        """Carrega e inicia servidores MCP do settings.json."""
        settings = config.load_settings()
        mcp_config = settings.get("mcp_servers", {})

        for name, server_data in mcp_config.items():
            cfg = MCPServerConfig.from_dict(name, server_data)
            if cfg.enabled:
                self.add_server(cfg)

    def add_server(self, cfg: MCPServerConfig) -> bool:
        """Adiciona e inicia um servidor MCP."""
        server = MCPServer(cfg)
        if server.start():
            self._servers[cfg.name] = server
            return True
        return False

    def stop_all(self) -> None:
        """Para todos os servidores."""
        for server in self._servers.values():
            server.stop()
        self._servers.clear()

    def register_tools(self, registry: ToolRegistry) -> int:
        """Registra todas as tools MCP no registry do agente."""
        count = 0
        for server in self._servers.values():
            for tool_def in server.tools:
                proxy = MCPToolProxy(server, tool_def)
                registry.register(proxy)
                count += 1
        return count

    def get_servers(self) -> dict[str, MCPServer]:
        return dict(self._servers)

    def server_status(self) -> list[dict]:
        """Status de todos os servidores."""
        result = []
        for name, server in self._servers.items():
            result.append({
                "name": name,
                "tools": len(server.tools),
                "running": server.process is not None and server.process.poll() is None,
            })
        return result
