"""Remote Triggers do Batmam.

Servidor HTTP simples que permite disparar agentes remotamente.
Roda em background na porta configurada.

Uso:
  POST /trigger {"prompt": "...", "cwd": "/path", "model": "gpt-4.1"}
  GET /status
  GET /triggers  (lista triggers configurados)
"""

from __future__ import annotations
import json
import threading
import time
import uuid
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
from dataclasses import dataclass, field
from typing import Any
from . import config


@dataclass
class TriggerResult:
    """Resultado de uma execucao de trigger."""
    id: str
    prompt: str
    status: str  # running, completed, error
    output: str = ""
    started_at: float = field(default_factory=time.time)
    completed_at: float = 0


class TriggerStore:
    """Armazena resultados de triggers."""

    def __init__(self) -> None:
        self._results: dict[str, TriggerResult] = {}
        self._lock = threading.Lock()

    def create(self, prompt: str) -> TriggerResult:
        result = TriggerResult(
            id=uuid.uuid4().hex[:12],
            prompt=prompt,
            status="running",
        )
        with self._lock:
            self._results[result.id] = result
        return result

    def complete(self, result_id: str, output: str, status: str = "completed") -> None:
        with self._lock:
            if result_id in self._results:
                self._results[result_id].output = output[-2000:]
                self._results[result_id].status = status
                self._results[result_id].completed_at = time.time()

    def get(self, result_id: str) -> TriggerResult | None:
        return self._results.get(result_id)

    def list_recent(self, limit: int = 20) -> list[TriggerResult]:
        results = sorted(self._results.values(), key=lambda r: r.started_at, reverse=True)
        return results[:limit]


_store = TriggerStore()


class TriggerHandler(BaseHTTPRequestHandler):
    """Handler HTTP para triggers."""

    def log_message(self, format, *args):
        pass  # Silencia logs

    def do_GET(self):
        if self.path == "/status":
            self._json_response({"status": "ok", "uptime": "running"})
        elif self.path == "/triggers":
            results = _store.list_recent()
            self._json_response({
                "triggers": [
                    {
                        "id": r.id,
                        "prompt": r.prompt[:100],
                        "status": r.status,
                        "started_at": r.started_at,
                        "completed_at": r.completed_at,
                    }
                    for r in results
                ]
            })
        elif self.path.startswith("/result/"):
            result_id = self.path.split("/")[-1]
            result = _store.get(result_id)
            if result:
                self._json_response({
                    "id": result.id,
                    "status": result.status,
                    "output": result.output,
                    "prompt": result.prompt,
                })
            else:
                self._json_response({"error": "not found"}, 404)
        else:
            self._json_response({"error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/trigger":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                self._json_response({"error": "invalid json"}, 400)
                return

            prompt = data.get("prompt", "")
            if not prompt:
                self._json_response({"error": "prompt required"}, 400)
                return

            cwd = data.get("cwd", "")
            model = data.get("model", config.BATMAM_MODEL)

            result = _store.create(prompt)

            # Executa em background
            thread = threading.Thread(
                target=_execute_trigger,
                args=(result.id, prompt, cwd, model),
                daemon=True,
            )
            thread.start()

            self._json_response({
                "id": result.id,
                "status": "running",
                "check_url": f"/result/{result.id}",
            })
        else:
            self._json_response({"error": "not found"}, 404)

    def _json_response(self, data: dict, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode("utf-8"))


def _execute_trigger(result_id: str, prompt: str, cwd: str, model: str) -> None:
    """Executa o prompt via batmam CLI."""
    try:
        cmd = ["batmam", "-y", "-m", model, prompt]
        result = subprocess.run(
            cmd,
            cwd=cwd or None,
            capture_output=True,
            text=True,
            timeout=600,
        )
        output = result.stdout or result.stderr or "(sem saida)"
        _store.complete(result_id, output, "completed")
    except Exception as e:
        _store.complete(result_id, str(e), "error")


_server: HTTPServer | None = None
_server_thread: threading.Thread | None = None


def start_trigger_server(port: int = 7777) -> None:
    """Inicia o servidor de triggers em background."""
    global _server, _server_thread

    if _server is not None:
        return

    _server = HTTPServer(("0.0.0.0", port), TriggerHandler)
    _server_thread = threading.Thread(target=_server.serve_forever, daemon=True)
    _server_thread.start()


def stop_trigger_server() -> None:
    """Para o servidor de triggers."""
    global _server, _server_thread
    if _server:
        _server.shutdown()
        _server = None
        _server_thread = None


def get_trigger_store() -> TriggerStore:
    return _store
