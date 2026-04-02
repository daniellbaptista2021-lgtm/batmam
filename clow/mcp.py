"""MCP (Model Context Protocol) Client do Clow.

Suporta 3 tipos de transporte:
  1. Stdio (padrao): processo local com JSON-RPC via stdin/stdout
  2. SSE (Server-Sent Events): servidor remoto com streaming
  3. HTTP: servidor remoto com request/response simples

Configuracao em ~/.clow/settings.json:

{
  "mcp_servers": {
    "filesystem": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user"],
      "env": {}
    },
    "remote-tools": {
      "transport": "sse",
      "url": "https://mcp.example.com/sse",
      "headers": {"Authorization": "Bearer xxx"}
    },
    "api-tools": {
      "transport": "http",
      "url": "https://mcp.example.com/api",
      "headers": {"Authorization": "Bearer xxx"}
    }
  }
}
"""

from __future__ import annotations
import subprocess
import json
import threading
import os
import time
from typing import Any
from dataclasses import dataclass, field
from .tools.base import BaseTool, ToolRegistry
from . import config


@dataclass
class MCPServerConfig:
    """Configuracao de um servidor MCP."""
    name: str
    transport: str = "stdio"        # "stdio", "sse", "http"
    command: str = ""               # Para stdio
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""                   # Para SSE e HTTP
    headers: dict[str, str] = field(default_factory=dict)
    enabled: bool = True

    @classmethod
    def from_dict(cls, name: str, data: dict) -> MCPServerConfig:
        return cls(
            name=name,
            transport=data.get("transport", "stdio"),
            command=data.get("command", ""),
            args=data.get("args", []),
            env=data.get("env", {}),
            url=data.get("url", ""),
            headers=data.get("headers", {}),
            enabled=data.get("enabled", True),
        )


class MCPServer:
    """Conexao a um servidor MCP via stdio (JSON-RPC)."""

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

            self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
            self._reader_thread.start()

            return self._initialize()

        except Exception:
            self._running = False
            return False

    def stop(self) -> None:
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
        resp = self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "clow", "version": "0.2.0"},
        })
        if resp is None:
            return False

        self._send_notification("notifications/initialized", {})

        tools_resp = self._send_request("tools/list", {})
        if tools_resp and "tools" in tools_resp:
            self.tools = tools_resp["tools"]

        return True

    def call_tool(self, name: str, arguments: dict) -> str:
        resp = self._send_request("tools/call", {
            "name": name,
            "arguments": arguments,
        })

        if resp is None:
            return "[ERROR] Sem resposta do servidor MCP."

        return _format_mcp_response(resp)

    def _send_request(self, method: str, params: dict, timeout: float = 30) -> dict | None:
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


class MCPSSEServer:
    """Conexao a um servidor MCP via Server-Sent Events (SSE)."""

    def __init__(self, cfg: MCPServerConfig) -> None:
        self.cfg = cfg
        self.tools: list[dict] = []
        self._request_id = 0
        self._endpoint_url = ""  # URL para enviar mensagens (recebida via SSE)
        self._running = False

    def start(self) -> bool:
        if not self.cfg.url:
            return False

        try:
            import requests
        except ImportError:
            return False

        try:
            # Conecta ao endpoint SSE para receber o endpoint de mensagens
            self._running = True

            # Faz initialize via HTTP POST
            resp = self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "clow", "version": "0.2.0"},
            })

            if resp is None:
                self._running = False
                return False

            # Notifica initialized
            self._send_notification("notifications/initialized", {})

            # Lista tools
            tools_resp = self._send_request("tools/list", {})
            if tools_resp and "tools" in tools_resp:
                self.tools = tools_resp["tools"]

            return True

        except Exception:
            self._running = False
            return False

    def stop(self) -> None:
        self._running = False

    def call_tool(self, name: str, arguments: dict) -> str:
        resp = self._send_request("tools/call", {
            "name": name,
            "arguments": arguments,
        })
        if resp is None:
            return "[ERROR] Sem resposta do servidor MCP SSE."
        return _format_mcp_response(resp)

    def _send_request(self, method: str, params: dict, timeout: float = 30) -> dict | None:
        try:
            import requests as req_lib
        except ImportError:
            return None

        self._request_id += 1

        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }

        headers = {
            "Content-Type": "application/json",
            **self.cfg.headers,
        }

        try:
            # Para SSE, envia POST ao endpoint base
            url = self.cfg.url.rstrip("/")
            if not url.endswith("/message"):
                url = url.rstrip("/sse") + "/message"

            resp = req_lib.post(
                url,
                json=payload,
                headers=headers,
                timeout=timeout,
            )

            if resp.status_code == 200:
                data = resp.json()
                if "error" in data:
                    return None
                return data.get("result", data)
            return None

        except Exception:
            return None

    def _send_notification(self, method: str, params: dict) -> None:
        try:
            import requests as req_lib
        except ImportError:
            return

        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }

        headers = {
            "Content-Type": "application/json",
            **self.cfg.headers,
        }

        try:
            url = self.cfg.url.rstrip("/")
            if not url.endswith("/message"):
                url = url.rstrip("/sse") + "/message"
            req_lib.post(url, json=payload, headers=headers, timeout=5)
        except Exception:
            pass


class MCPHTTPServer:
    """Conexao a um servidor MCP via HTTP simples (request/response)."""

    def __init__(self, cfg: MCPServerConfig) -> None:
        self.cfg = cfg
        self.tools: list[dict] = []
        self._request_id = 0

    def start(self) -> bool:
        if not self.cfg.url:
            return False

        try:
            import requests
        except ImportError:
            return False

        try:
            resp = self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "clow", "version": "0.2.0"},
            })

            if resp is None:
                return False

            self._send_request("notifications/initialized", {})

            tools_resp = self._send_request("tools/list", {})
            if tools_resp and "tools" in tools_resp:
                self.tools = tools_resp["tools"]

            return True

        except Exception:
            return False

    def stop(self) -> None:
        pass

    def call_tool(self, name: str, arguments: dict) -> str:
        resp = self._send_request("tools/call", {
            "name": name,
            "arguments": arguments,
        })
        if resp is None:
            return "[ERROR] Sem resposta do servidor MCP HTTP."
        return _format_mcp_response(resp)

    def _send_request(self, method: str, params: dict, timeout: float = 30) -> dict | None:
        try:
            import requests as req_lib
        except ImportError:
            return None

        self._request_id += 1

        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }

        headers = {
            "Content-Type": "application/json",
            **self.cfg.headers,
        }

        try:
            resp = req_lib.post(
                self.cfg.url,
                json=payload,
                headers=headers,
                timeout=timeout,
            )

            if resp.status_code == 200:
                data = resp.json()
                if "error" in data:
                    return None
                return data.get("result", data)
            return None

        except Exception:
            return None


def _format_mcp_response(resp: dict) -> str:
    """Formata resposta MCP padronizada."""
    if "content" in resp:
        parts = []
        for item in resp["content"]:
            if item.get("type") == "text":
                parts.append(item.get("text", ""))
            elif item.get("type") == "image":
                parts.append(f"[imagem: {item.get('mimeType', 'unknown')}]")
        return "\n".join(parts) if parts else "(sem conteudo)"
    return json.dumps(resp, indent=2)


class MCPToolProxy(BaseTool):
    """Proxy que expoe uma tool MCP como BaseTool do Clow."""

    requires_confirmation = True

    def __init__(self, server: Any, tool_def: dict, server_name: str = "") -> None:
        self.server = server
        self.tool_def = tool_def
        self.name = f"mcp__{server_name}__{tool_def['name']}"
        self.description = tool_def.get("description", f"MCP tool: {tool_def['name']}")

    def get_schema(self) -> dict:
        return self.tool_def.get("inputSchema", {"type": "object", "properties": {}})

    def execute(self, **kwargs: Any) -> str:
        return self.server.call_tool(self.tool_def["name"], kwargs)


class MCPManager:
    """Gerencia todos os servidores MCP (stdio, SSE, HTTP)."""

    def __init__(self) -> None:
        self._servers: dict[str, Any] = {}  # MCPServer | MCPSSEServer | MCPHTTPServer

    def load_from_settings(self) -> None:
        """Carrega e inicia servidores MCP do settings.json."""
        settings = config.load_settings()
        mcp_config = settings.get("mcp_servers", {})

        for name, server_data in mcp_config.items():
            cfg = MCPServerConfig.from_dict(name, server_data)
            if cfg.enabled:
                self.add_server(cfg)

    def add_server(self, cfg: MCPServerConfig) -> bool:
        """Adiciona e inicia um servidor MCP baseado no tipo de transporte."""
        if cfg.transport == "sse":
            server = MCPSSEServer(cfg)
        elif cfg.transport == "http":
            server = MCPHTTPServer(cfg)
        else:
            server = MCPServer(cfg)

        if server.start():
            self._servers[cfg.name] = server
            return True
        return False

    def stop_all(self) -> None:
        for server in self._servers.values():
            server.stop()
        self._servers.clear()

    def register_tools(self, registry: ToolRegistry) -> int:
        """Registra todas as tools MCP no registry do agente."""
        count = 0
        for name, server in self._servers.items():
            for tool_def in server.tools:
                proxy = MCPToolProxy(server, tool_def, server_name=name)
                registry.register(proxy)
                count += 1
        return count

    def get_servers(self) -> dict[str, Any]:
        return dict(self._servers)

    def server_status(self) -> list[dict]:
        result = []
        for name, server in self._servers.items():
            transport = server.cfg.transport
            running = True
            if hasattr(server, "process"):
                running = server.process is not None and server.process.poll() is None
            elif hasattr(server, "_running"):
                running = server._running

            result.append({
                "name": name,
                "transport": transport,
                "tools": len(server.tools),
                "running": running,
            })
        return result
