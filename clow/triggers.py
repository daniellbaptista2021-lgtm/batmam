"""Remote Triggers — HTTP endpoints para disparar agentes.

Features:
  #10 — Remote Triggers HTTP
  #20 — Integração Chatwoot webhook
  #21 — Rate Limiting por IP
"""

from __future__ import annotations
import json
import uuid
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from dataclasses import dataclass, field
from typing import Callable, Any


@dataclass
class TriggerResult:
    id: str
    prompt: str
    output: str
    status: str  # "running", "completed", "error"
    started_at: float
    completed_at: float = 0.0
    source: str = "http"  # "http", "chatwoot"

    def to_dict(self) -> dict:
        return {
            "id": self.id, "prompt": self.prompt,
            "output": self.output[:1000], "status": self.status,
            "started_at": self.started_at, "completed_at": self.completed_at,
            "source": self.source,
        }


# ── Feature #21: Rate Limiter por IP ──────────────────────────

class RateLimiter:
    """Rate limiter simples por IP com sliding window."""

    def __init__(self, max_requests: int = 10, window_seconds: int = 60) -> None:
        self.max_requests = max_requests
        self.window = window_seconds
        self._requests: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def is_allowed(self, ip: str) -> bool:
        """Retorna True se o IP pode fazer mais uma request."""
        now = time.time()
        with self._lock:
            if ip not in self._requests:
                self._requests[ip] = []

            # Remove requests fora da janela
            self._requests[ip] = [t for t in self._requests[ip] if now - t < self.window]

            if len(self._requests[ip]) >= self.max_requests:
                return False

            self._requests[ip].append(now)
            return True

    def remaining(self, ip: str) -> int:
        """Quantas requests restam para o IP."""
        now = time.time()
        with self._lock:
            reqs = [t for t in self._requests.get(ip, []) if now - t < self.window]
            return max(0, self.max_requests - len(reqs))


class TriggerServer:
    """Servidor HTTP para receber triggers remotos com rate limiting e Chatwoot."""

    def __init__(self, port: int = 7777) -> None:
        self.port = port
        self._agent_factory: Callable[..., Any] | None = None
        self._results: dict[str, TriggerResult] = {}
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.running = False
        self._token = uuid.uuid4().hex[:16]
        self.rate_limiter = RateLimiter(max_requests=10, window_seconds=60)
        # Feature #20: Chatwoot config
        self._chatwoot_token: str = ""
        self._chatwoot_events: set[str] = {"message_created", "conversation_created"}

    def set_agent_factory(self, factory: Callable[..., Any]) -> None:
        self._agent_factory = factory

    def configure_chatwoot(self, token: str, events: set[str] | None = None) -> None:
        """Configura integração Chatwoot."""
        self._chatwoot_token = token
        if events:
            self._chatwoot_events = events

    @property
    def token(self) -> str:
        return self._token

    def start(self) -> str:
        """Inicia o servidor HTTP em background. Retorna info de conexão."""
        if self.running:
            return f"Trigger server já rodando na porta {self.port}"

        trigger_server = self

        class Handler(BaseHTTPRequestHandler):

            def _get_client_ip(self) -> str:
                """Extrai IP do cliente (suporta proxy via X-Forwarded-For)."""
                forwarded = self.headers.get("X-Forwarded-For", "")
                if forwarded:
                    return forwarded.split(",")[0].strip()
                return self.client_address[0]

            def _send_json(self, code: int, data: dict) -> None:
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(data).encode())

            def do_POST(self):
                client_ip = self._get_client_ip()

                # Feature #21: Rate limiting
                if not trigger_server.rate_limiter.is_allowed(client_ip):
                    remaining = trigger_server.rate_limiter.remaining(client_ip)
                    self.send_response(429)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Retry-After", "60")
                    self.send_header("X-RateLimit-Remaining", str(remaining))
                    self.end_headers()
                    self.wfile.write(b'{"error": "rate limit exceeded", "retry_after": 60}')
                    return

                if self.path == "/trigger":
                    self._handle_trigger()
                    return

                # Feature #20: Chatwoot webhook
                if self.path == "/webhook/chatwoot":
                    self._handle_chatwoot()
                    return

                self.send_response(404)
                self.end_headers()

            def _handle_trigger(self):
                # Verifica token
                auth = self.headers.get("Authorization", "")
                if auth != f"Bearer {trigger_server._token}":
                    self._send_json(401, {"error": "unauthorized"})
                    return

                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length)
                try:
                    data = json.loads(body)
                except json.JSONDecodeError:
                    self._send_json(400, {"error": "invalid json"})
                    return

                prompt = data.get("prompt", "")
                if not prompt:
                    self._send_json(400, {"error": "prompt required"})
                    return

                result_id = trigger_server._run_trigger(prompt, source="http")
                self._send_json(202, {"id": result_id, "status": "running"})

            def _handle_chatwoot(self):
                """Feature #20: Processa webhook do Chatwoot."""
                # Verifica token Chatwoot
                if trigger_server._chatwoot_token:
                    auth = self.headers.get("Authorization", "")
                    if auth != f"Bearer {trigger_server._chatwoot_token}":
                        self._send_json(401, {"error": "unauthorized"})
                        return

                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length)
                try:
                    data = json.loads(body)
                except json.JSONDecodeError:
                    self._send_json(400, {"error": "invalid json"})
                    return

                event = data.get("event", "")
                if event not in trigger_server._chatwoot_events:
                    self._send_json(200, {"status": "ignored", "event": event})
                    return

                # Extrai conteúdo da mensagem
                prompt = trigger_server._extract_chatwoot_prompt(data, event)
                if not prompt:
                    self._send_json(200, {"status": "no_content"})
                    return

                result_id = trigger_server._run_trigger(prompt, source="chatwoot")
                self._send_json(202, {"id": result_id, "status": "running", "event": event})

            def do_GET(self):
                if self.path.startswith("/trigger/"):
                    result_id = self.path.split("/")[-1]
                    result = trigger_server._results.get(result_id)
                    if result:
                        self._send_json(200, result.to_dict())
                    else:
                        self._send_json(404, {"error": "not found"})
                    return

                if self.path == "/triggers":
                    results = [r.to_dict() for r in trigger_server._results.values()]
                    self._send_json(200, {"results": results, "count": len(results)})
                    return

                if self.path == "/health":
                    self._send_json(200, {"status": "ok"})
                    return

                self.send_response(404)
                self.end_headers()

            def log_message(self, format, *args):
                pass  # Silencia logs

        self._server = HTTPServer(("0.0.0.0", self.port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="trigger-server")
        self._thread.start()
        self.running = True

        chatwoot_info = ""
        if self._chatwoot_token:
            chatwoot_info = f"\nChatwoot webhook: POST http://localhost:{self.port}/webhook/chatwoot"

        return (
            f"Trigger server iniciado na porta {self.port}\n"
            f"Token: {self._token}\n"
            f"Rate limit: {self.rate_limiter.max_requests} req/{self.rate_limiter.window}s por IP\n"
            f"Uso: curl -X POST http://localhost:{self.port}/trigger "
            f'-H "Authorization: Bearer {self._token}" '
            f'-H "Content-Type: application/json" '
            f"-d '{{\"prompt\": \"sua tarefa aqui\"}}'"
            f"{chatwoot_info}"
        )

    def stop(self) -> str:
        if not self.running or not self._server:
            return "Trigger server não está rodando."
        self._server.shutdown()
        self.running = False
        return "Trigger server parado."

    def _extract_chatwoot_prompt(self, data: dict, event: str) -> str:
        """Extrai prompt de um webhook Chatwoot."""
        if event == "message_created":
            # Ignora mensagens do bot (message_type 1 = outgoing)
            message_type = data.get("message_type")
            if message_type == 1:
                return ""
            content = data.get("content", "")
            conversation = data.get("conversation", {})
            contact = data.get("sender", {}).get("name", "Visitante")
            conv_id = conversation.get("id", "?")
            return (
                f"[Chatwoot] Mensagem de {contact} na conversa #{conv_id}:\n"
                f"{content}\n\n"
                "Responda de forma útil e profissional."
            ) if content else ""

        elif event == "conversation_created":
            conversation = data.get("conversation", data)
            contact_name = ""
            meta = conversation.get("meta", {})
            if meta:
                sender = meta.get("sender", {})
                contact_name = sender.get("name", "Visitante")
            conv_id = conversation.get("id", "?")
            messages = conversation.get("messages", [])
            first_msg = messages[0].get("content", "") if messages else "Nova conversa iniciada"
            return (
                f"[Chatwoot] Nova conversa #{conv_id} de {contact_name}:\n"
                f"{first_msg}\n\n"
                "Dê boas-vindas e ofereça ajuda."
            )

        return ""

    def _run_trigger(self, prompt: str, source: str = "http") -> str:
        result_id = uuid.uuid4().hex[:12]
        result = TriggerResult(
            id=result_id, prompt=prompt, output="",
            status="running", started_at=time.time(), source=source,
        )
        self._results[result_id] = result

        def execute():
            try:
                if self._agent_factory:
                    agent = self._agent_factory()
                    output = agent.run_turn(prompt)
                    result.output = output
                    result.status = "completed"
                else:
                    result.output = "[ERROR] Agent factory not configured"
                    result.status = "error"
            except Exception as e:
                result.output = f"[ERROR] {e}"
                result.status = "error"
            result.completed_at = time.time()

        thread = threading.Thread(target=execute, daemon=True, name=f"trigger-{result_id}")
        thread.start()
        return result_id

    def list_results(self) -> list[TriggerResult]:
        return sorted(self._results.values(), key=lambda r: r.started_at, reverse=True)


# Instância global
_trigger_server = TriggerServer()

def get_trigger_server() -> TriggerServer:
    return _trigger_server
