"""Live Pair Programming — spectator mode com SSE.

Permite assistir sessoes do Clow em tempo real via Server-Sent Events.
Suporta: tool_call, tool_result, text_delta, file_diff, thinking.
URL compartilhavel com controle remoto (approve) para usuarios autorizados.
"""

from __future__ import annotations
import json
import queue
import threading
import time
import uuid
from typing import Any

from . import config
from .logging import log_action

# Registry global de sessoes ativas com espectadores
_sessions: dict[str, "SpectatorSession"] = {}
_lock = threading.Lock()


class SpectatorSession:
    """Sessao de spectator — coleta e distribui eventos SSE."""

    def __init__(self, session_id: str, share_token: str | None = None):
        self.session_id = session_id
        self.share_token = share_token or uuid.uuid4().hex[:12]
        self.created_at = time.time()
        self._subscribers: list[queue.Queue] = []
        self._events: list[dict] = []  # Buffer de eventos recentes
        self._lock = threading.Lock()
        self._pending_approval: dict[str, threading.Event] = {}
        self._approval_results: dict[str, bool] = {}
        self.max_buffer = 200

    def subscribe(self) -> queue.Queue:
        """Registra um novo subscriber e retorna sua queue."""
        q: queue.Queue = queue.Queue(maxsize=100)
        with self._lock:
            self._subscribers.append(q)
            # Envia eventos recentes pro novo subscriber
            for event in self._events[-50:]:
                try:
                    q.put_nowait(event)
                except queue.Full:
                    break
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Emite evento para todos os subscribers."""
        event = {
            "type": event_type,
            "timestamp": time.time(),
            "data": data,
        }

        with self._lock:
            self._events.append(event)
            if len(self._events) > self.max_buffer:
                self._events = self._events[-self.max_buffer:]

            dead_queues = []
            for q in self._subscribers:
                try:
                    q.put_nowait(event)
                except queue.Full:
                    dead_queues.append(q)

            for q in dead_queues:
                self._subscribers.remove(q)

    def request_approval(self, prompt: str, timeout: float = 300) -> bool:
        """Pede aprovacao via spectator (quando agente precisa de confirmacao).

        Bloqueia ate receber resposta ou timeout.
        """
        approval_id = uuid.uuid4().hex[:8]
        event = threading.Event()

        with self._lock:
            self._pending_approval[approval_id] = event

        self.emit("approval_request", {
            "approval_id": approval_id,
            "prompt": prompt,
        })

        # Espera resposta
        approved = event.wait(timeout=timeout)

        with self._lock:
            result = self._approval_results.pop(approval_id, False)
            self._pending_approval.pop(approval_id, None)

        return result if approved else False

    def resolve_approval(self, approval_id: str, approved: bool) -> bool:
        """Resolve um pedido de aprovacao."""
        with self._lock:
            event = self._pending_approval.get(approval_id)
            if not event:
                return False
            self._approval_results[approval_id] = approved
            event.set()
        self.emit("approval_resolved", {"approval_id": approval_id, "approved": approved})
        return True

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "share_token": self.share_token,
            "created_at": self.created_at,
            "subscribers": self.subscriber_count,
            "events_buffered": len(self._events),
        }


# ── Registry Functions ────────────────────────────────────────

def create_spectator(session_id: str) -> SpectatorSession:
    """Cria ou retorna spectator session."""
    with _lock:
        if session_id not in _sessions:
            spectator = SpectatorSession(session_id)
            _sessions[session_id] = spectator
            log_action("spectator_create", f"session={session_id}", session_id=session_id)
        return _sessions[session_id]


def get_spectator(session_id: str) -> SpectatorSession | None:
    with _lock:
        return _sessions.get(session_id)


def get_spectator_by_token(token: str) -> SpectatorSession | None:
    with _lock:
        for s in _sessions.values():
            if s.share_token == token:
                return s
    return None


def list_spectators() -> list[dict]:
    with _lock:
        return [s.to_dict() for s in _sessions.values()]


def remove_spectator(session_id: str) -> bool:
    with _lock:
        if session_id in _sessions:
            del _sessions[session_id]
            return True
    return False


# ── Agent Callbacks (para emitir eventos) ─────────────────────

def make_spectator_callbacks(session_id: str) -> dict[str, Any]:
    """Cria callbacks para integrar com o Agent e emitir eventos SSE.

    Retorna dict com funcoes on_text_delta, on_tool_call, on_tool_result
    que podem ser passadas ao Agent.
    """
    spectator = get_spectator(session_id)
    if not spectator:
        spectator = create_spectator(session_id)

    def on_text_delta(text: str) -> None:
        spectator.emit("text_delta", {"text": text})

    def on_tool_call(name: str, args: dict) -> None:
        spectator.emit("tool_call", {
            "name": name,
            "arguments": {k: str(v)[:200] for k, v in args.items()},
        })

    def on_tool_result(name: str, status: str, output: str) -> None:
        spectator.emit("tool_result", {
            "name": name,
            "status": status,
            "output": output[:500],
        })

    def on_text_done(text: str) -> None:
        spectator.emit("text_done", {"text": text[:1000]})

    return {
        "on_text_delta": on_text_delta,
        "on_tool_call": on_tool_call,
        "on_tool_result": on_tool_result,
        "on_text_done": on_text_done,
    }


def emit_file_diff(session_id: str, filepath: str, before: str, after: str) -> None:
    """Emite evento de diff de arquivo."""
    spectator = get_spectator(session_id)
    if spectator:
        spectator.emit("file_diff", {
            "file": filepath,
            "before": before[:2000],
            "after": after[:2000],
        })


def emit_thinking(session_id: str, active: bool) -> None:
    """Emite evento de thinking (Extended Thinking)."""
    spectator = get_spectator(session_id)
    if spectator:
        spectator.emit("thinking", {"active": active})


def format_sse(event: dict) -> str:
    """Formata evento para Server-Sent Events."""
    event_type = event.get("type", "message")
    data = json.dumps(event, ensure_ascii=False)
    return f"event: {event_type}\ndata: {data}\n\n"
