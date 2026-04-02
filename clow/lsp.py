"""Integracao LSP (Language Server Protocol) do Clow.

Conecta a servidores de linguagem para obter diagnosticos em tempo real
(erros de compilacao, type errors, warnings) e enriquece o contexto
do agente com essa informacao.

Suporta qualquer LSP server via stdio (ex: pyright, tsserver, gopls, rust-analyzer).

Configuracao em ~/.clow/settings.json ou .clow/settings.json:

{
  "lsp": {
    "enabled": true,
    "servers": {
      "python": {
        "command": "pyright-langserver",
        "args": ["--stdio"],
        "file_patterns": ["*.py"]
      },
      "typescript": {
        "command": "typescript-language-server",
        "args": ["--stdio"],
        "file_patterns": ["*.ts", "*.tsx", "*.js", "*.jsx"]
      }
    }
  }
}
"""

from __future__ import annotations
import json
import subprocess
import threading
import time
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any
from . import config
from .logging import log_action


@dataclass
class LSPDiagnostic:
    """Um diagnostico LSP individual."""
    file_path: str
    line: int
    character: int
    severity: str       # "error", "warning", "info", "hint"
    message: str
    source: str = ""    # Nome do server/linter

    def format(self) -> str:
        """Formata o diagnostico para exibicao."""
        icon = {"error": "E", "warning": "W", "info": "I", "hint": "H"}.get(self.severity, "?")
        src = f" ({self.source})" if self.source else ""
        return f"[{icon}] {self.file_path}:{self.line + 1}:{self.character + 1} {self.message}{src}"


@dataclass
class LSPServerConfig:
    """Configuracao de um servidor LSP."""
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    file_patterns: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, name: str, data: dict) -> LSPServerConfig:
        return cls(
            name=name,
            command=data.get("command", ""),
            args=data.get("args", []),
            file_patterns=data.get("file_patterns", []),
            env=data.get("env", {}),
        )


SEVERITY_MAP = {
    1: "error",
    2: "warning",
    3: "info",
    4: "hint",
}


class LSPClient:
    """Cliente LSP que se conecta a um language server via stdio."""

    def __init__(self, cfg: LSPServerConfig, workspace_root: str) -> None:
        self.cfg = cfg
        self.workspace_root = workspace_root
        self.process: subprocess.Popen | None = None
        self._request_id = 0
        self._lock = threading.Lock()
        self._responses: dict[int, Any] = {}
        self._diagnostics: dict[str, list[LSPDiagnostic]] = {}
        self._reader_thread: threading.Thread | None = None
        self._running = False
        self._initialized = False

    def start(self) -> bool:
        """Inicia o servidor LSP."""
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
                env=env,
            )
            self._running = True

            self._reader_thread = threading.Thread(
                target=self._read_loop, daemon=True, name=f"lsp-{self.cfg.name}"
            )
            self._reader_thread.start()

            return self._initialize()

        except FileNotFoundError:
            log_action("lsp_not_found", f"Servidor LSP nao encontrado: {self.cfg.command}", level="warning")
            return False
        except Exception as e:
            log_action("lsp_error", f"Erro ao iniciar LSP {self.cfg.name}: {e}", level="error")
            self._running = False
            return False

    def stop(self) -> None:
        """Para o servidor LSP."""
        self._running = False
        if self.process:
            try:
                self._send_request("shutdown", {})
                self._send_notification("exit", None)
                self.process.wait(timeout=5)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None

    def _initialize(self) -> bool:
        """Envia initialize request ao servidor."""
        resp = self._send_request("initialize", {
            "processId": os.getpid(),
            "rootUri": f"file:///{self.workspace_root.replace(os.sep, '/')}",
            "capabilities": {
                "textDocument": {
                    "publishDiagnostics": {"relatedInformation": True},
                    "synchronization": {"didOpen": True, "didChange": True},
                },
            },
        })

        if resp is None:
            return False

        self._send_notification("initialized", {})
        self._initialized = True
        log_action("lsp_initialized", f"{self.cfg.name}")
        return True

    def open_file(self, file_path: str) -> None:
        """Notifica o servidor que um arquivo foi aberto."""
        if not self._initialized:
            return

        try:
            content = Path(file_path).read_text(encoding="utf-8")
        except Exception:
            return

        # Detecta languageId pela extensao
        ext = Path(file_path).suffix.lower()
        lang_map = {
            ".py": "python", ".js": "javascript", ".ts": "typescript",
            ".tsx": "typescriptreact", ".jsx": "javascriptreact",
            ".go": "go", ".rs": "rust", ".java": "java",
            ".c": "c", ".cpp": "cpp", ".h": "c", ".hpp": "cpp",
            ".rb": "ruby", ".php": "php", ".swift": "swift",
            ".kt": "kotlin", ".cs": "csharp",
        }
        language_id = lang_map.get(ext, "plaintext")

        uri = f"file:///{file_path.replace(os.sep, '/')}"
        self._send_notification("textDocument/didOpen", {
            "textDocument": {
                "uri": uri,
                "languageId": language_id,
                "version": 1,
                "text": content,
            },
        })

    def get_diagnostics(self, file_path: str | None = None) -> list[LSPDiagnostic]:
        """Retorna diagnosticos para um arquivo ou todos."""
        if file_path:
            uri = f"file:///{file_path.replace(os.sep, '/')}"
            return list(self._diagnostics.get(uri, []))

        all_diags = []
        for diags in self._diagnostics.values():
            all_diags.extend(diags)
        return all_diags

    def _send_request(self, method: str, params: dict, timeout: float = 10) -> dict | None:
        """Envia JSON-RPC request via LSP (com Content-Length header)."""
        with self._lock:
            self._request_id += 1
            req_id = self._request_id

        body = json.dumps({
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        })

        message = f"Content-Length: {len(body)}\r\n\r\n{body}"

        try:
            if self.process and self.process.stdin:
                self.process.stdin.write(message.encode("utf-8"))
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

    def _send_notification(self, method: str, params: dict | None) -> None:
        body = json.dumps({
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        })

        message = f"Content-Length: {len(body)}\r\n\r\n{body}"

        try:
            if self.process and self.process.stdin:
                self.process.stdin.write(message.encode("utf-8"))
                self.process.stdin.flush()
        except Exception:
            pass

    def _read_loop(self) -> None:
        """Le mensagens LSP do stdout (com Content-Length)."""
        while self._running and self.process and self.process.stdout:
            try:
                # Le headers
                content_length = 0
                while True:
                    line = self.process.stdout.readline()
                    if not line:
                        self._running = False
                        return
                    line_str = line.decode("utf-8", errors="replace").strip()
                    if not line_str:
                        break  # Headers acabaram
                    if line_str.lower().startswith("content-length:"):
                        try:
                            content_length = int(line_str.split(":")[1].strip())
                        except (ValueError, IndexError):
                            pass

                if content_length <= 0:
                    continue

                # Le body
                body = self.process.stdout.read(content_length)
                if not body:
                    continue

                data = json.loads(body.decode("utf-8", errors="replace"))

                # Resposta a request
                if "id" in data and "method" not in data:
                    with self._lock:
                        self._responses[data["id"]] = data

                # Notificacao de diagnosticos
                elif data.get("method") == "textDocument/publishDiagnostics":
                    self._handle_diagnostics(data.get("params", {}))

            except json.JSONDecodeError:
                continue
            except Exception:
                break

    def _handle_diagnostics(self, params: dict) -> None:
        """Processa diagnosticos recebidos do servidor."""
        uri = params.get("uri", "")
        raw_diags = params.get("diagnostics", [])

        diagnostics = []
        for d in raw_diags:
            rng = d.get("range", {}).get("start", {})
            diagnostics.append(LSPDiagnostic(
                file_path=_uri_to_path(uri),
                line=rng.get("line", 0),
                character=rng.get("character", 0),
                severity=SEVERITY_MAP.get(d.get("severity", 4), "info"),
                message=d.get("message", ""),
                source=d.get("source", self.cfg.name),
            ))

        with self._lock:
            self._diagnostics[uri] = diagnostics


class LSPManager:
    """Gerencia multiplos servidores LSP."""

    def __init__(self, workspace_root: str) -> None:
        self.workspace_root = workspace_root
        self._clients: dict[str, LSPClient] = {}

    def load_from_settings(self) -> int:
        """Carrega e inicia servidores LSP do settings.json."""
        settings = config.load_settings()
        lsp_config = settings.get("lsp", {})

        if not lsp_config.get("enabled", False):
            return 0

        servers = lsp_config.get("servers", {})
        count = 0
        for name, server_data in servers.items():
            cfg = LSPServerConfig.from_dict(name, server_data)
            client = LSPClient(cfg, self.workspace_root)
            if client.start():
                self._clients[name] = client
                count += 1

        return count

    def stop_all(self) -> None:
        for client in self._clients.values():
            client.stop()
        self._clients.clear()

    def open_file(self, file_path: str) -> None:
        """Notifica todos os servidores relevantes sobre um arquivo aberto."""
        ext = Path(file_path).suffix.lower()
        for client in self._clients.values():
            if not client.cfg.file_patterns:
                client.open_file(file_path)
                continue
            for pattern in client.cfg.file_patterns:
                if file_path.endswith(pattern.lstrip("*")):
                    client.open_file(file_path)
                    break

    def get_all_diagnostics(self) -> list[LSPDiagnostic]:
        """Retorna todos os diagnosticos de todos os servidores."""
        all_diags = []
        for client in self._clients.values():
            all_diags.extend(client.get_diagnostics())
        return all_diags

    def get_diagnostics_for_file(self, file_path: str) -> list[LSPDiagnostic]:
        """Retorna diagnosticos para um arquivo especifico."""
        all_diags = []
        for client in self._clients.values():
            all_diags.extend(client.get_diagnostics(file_path))
        return all_diags

    def get_context_summary(self, max_items: int = 20) -> str:
        """Gera resumo de diagnosticos para injetar no contexto do agente."""
        diags = self.get_all_diagnostics()
        if not diags:
            return ""

        # Prioriza erros sobre warnings
        errors = [d for d in diags if d.severity == "error"]
        warnings = [d for d in diags if d.severity == "warning"]
        others = [d for d in diags if d.severity not in ("error", "warning")]

        prioritized = (errors + warnings + others)[:max_items]

        parts = [f"LSP Diagnostics ({len(errors)} errors, {len(warnings)} warnings):"]
        for d in prioritized:
            parts.append(f"  {d.format()}")

        if len(diags) > max_items:
            parts.append(f"  ... e mais {len(diags) - max_items} diagnosticos")

        return "\n".join(parts)

    def server_status(self) -> list[dict]:
        """Status de todos os servidores LSP."""
        result = []
        for name, client in self._clients.items():
            diags = client.get_diagnostics()
            result.append({
                "name": name,
                "command": client.cfg.command,
                "running": client._initialized,
                "diagnostics": len(diags),
                "errors": sum(1 for d in diags if d.severity == "error"),
                "warnings": sum(1 for d in diags if d.severity == "warning"),
            })
        return result


def _uri_to_path(uri: str) -> str:
    """Converte file:// URI para caminho local."""
    if uri.startswith("file:///"):
        path = uri[8:]  # Remove file:///
        # Windows: file:///C:/...
        if len(path) > 1 and path[1] == ":":
            return path.replace("/", os.sep)
        return "/" + path.replace("/", os.sep)
    return uri


# ── Integracao com Agent ────────────────────────────────────────

class LSPAgentIntegration:
    """Integra LSP com o agent loop do Clow.

    - Notifica LSP quando arquivos sao editados/escritos
    - Injeta diagnosticos no contexto do agente
    - Espera breve para diagnosticos apos edicao
    """

    def __init__(self, manager: LSPManager) -> None:
        self.manager = manager
        self._notified_files: set[str] = set()

    def on_file_changed(self, file_path: str) -> None:
        """Chamado quando uma tool edita/escreve um arquivo."""
        if not self.manager._clients:
            return

        abs_path = str(Path(file_path).resolve())
        self.manager.open_file(abs_path)
        self._notified_files.add(abs_path)

        # Espera breve para o LSP processar
        import time as _time
        _time.sleep(0.5)

    def get_diagnostics_context(self, max_items: int = 15) -> str:
        """Retorna diagnosticos formatados para injetar no system prompt."""
        if not self.manager._clients:
            return ""

        summary = self.manager.get_context_summary(max_items)
        if not summary:
            return ""

        return f"\n# LSP Diagnostics (tempo real)\n{summary}"

    def get_file_diagnostics(self, file_path: str) -> list[LSPDiagnostic]:
        """Retorna diagnosticos para um arquivo especifico."""
        return self.manager.get_diagnostics_for_file(file_path)
