"""Bridge System — Remote Control Protocol (Claude Code Architecture).

Connects a web UI session to a remote Clow CLI instance.
Uses Server-Sent Events (SSE) for real-time communication.

Architecture:
- Web UI sends messages via POST /api/v1/bridge/{session_id}/send
- Remote CLI polls GET /api/v1/bridge/{session_id}/events (SSE stream)
- Heartbeat keeps connection alive
- Crash recovery via session pointer files

Modes:
- standalone: long-running bridge (like `clow remote-control`)
- repl: in-process bridge (from interactive REPL)
"""

import json
import time
import uuid
import threading
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from . import config

logger = logging.getLogger("clow.bridge")

# Session storage
_bridge_sessions: dict[str, "BridgeSession"] = {}
_lock = threading.Lock()

# Config
MAX_SESSIONS = 32
HEARTBEAT_INTERVAL = 20  # seconds
SESSION_TIMEOUT = 300     # 5 minutes without heartbeat = dead
POLL_INTERVAL_FAST = 1.0  # seconds when not at capacity
POLL_INTERVAL_SLOW = 5.0  # when at capacity
MAX_RECONNECT_ATTEMPTS = 3


@dataclass
class BridgeMessage:
    """A message in the bridge protocol."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    type: str = ""  # user_input, assistant_response, tool_use, tool_result, control, heartbeat
    content: str = ""
    data: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    delivered: bool = False


@dataclass
class BridgeSession:
    """A bridge session connecting web UI to remote CLI."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    user_id: str = ""
    environment_id: str = ""
    status: str = "idle"  # idle, running, waiting_input, disconnected
    created_at: float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)

    # Message queues
    inbound: list = field(default_factory=list)   # Web -> CLI (user prompts)
    outbound: list = field(default_factory=list)  # CLI -> Web (responses)

    # Capacity tracking
    worker_connected: bool = False
    worker_epoch: int = 0

    # Crash recovery
    pointer_path: str = ""
    reconnect_count: int = 0

    def is_alive(self) -> bool:
        return (time.time() - self.last_heartbeat) < SESSION_TIMEOUT

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "status": self.status,
            "worker_connected": self.worker_connected,
            "created_at": self.created_at,
            "last_heartbeat": self.last_heartbeat,
            "inbound_count": len(self.inbound),
            "outbound_count": len(self.outbound),
            "is_alive": self.is_alive(),
        }


# == Session Management ==

def create_session(user_id: str) -> BridgeSession:
    """Create a new bridge session."""
    with _lock:
        # Check capacity
        active = [s for s in _bridge_sessions.values() if s.is_alive()]
        if len(active) >= MAX_SESSIONS:
            raise RuntimeError(f"Max sessions ({MAX_SESSIONS}) reached")

        session = BridgeSession(user_id=user_id)
        session.environment_id = uuid.uuid4().hex[:12]
        _bridge_sessions[session.id] = session

        # Write crash recovery pointer
        pointer_dir = config.CLOW_HOME / "bridge_pointers"
        pointer_dir.mkdir(parents=True, exist_ok=True)
        pointer = pointer_dir / f"{session.id}.json"
        pointer.write_text(json.dumps({
            "session_id": session.id,
            "user_id": user_id,
            "environment_id": session.environment_id,
            "created_at": session.created_at,
        }))
        session.pointer_path = str(pointer)

        logger.info(f"Bridge session created: {session.id} for user {user_id}")
        return session


def get_session(session_id: str) -> "BridgeSession | None":
    """Get a bridge session by ID."""
    with _lock:
        return _bridge_sessions.get(session_id)


def list_sessions(user_id: str = "") -> list[dict]:
    """List active bridge sessions."""
    with _lock:
        sessions = list(_bridge_sessions.values())
    if user_id:
        sessions = [s for s in sessions if s.user_id == user_id]
    return [s.to_dict() for s in sessions if s.is_alive()]


def close_session(session_id: str) -> bool:
    """Close and cleanup a bridge session."""
    with _lock:
        session = _bridge_sessions.pop(session_id, None)
    if session:
        session.status = "disconnected"
        # Remove crash recovery pointer
        if session.pointer_path:
            try:
                Path(session.pointer_path).unlink(missing_ok=True)
            except Exception:
                pass
        logger.info(f"Bridge session closed: {session_id}")
        return True
    return False


# == Message Protocol ==

def send_to_worker(session_id: str, message_type: str, content: str, data: dict = None) -> str:
    """Send message from web UI to remote CLI worker."""
    session = get_session(session_id)
    if not session:
        raise ValueError(f"Session {session_id} not found")

    msg = BridgeMessage(
        type=message_type,
        content=content,
        data=data or {},
    )
    session.inbound.append(msg)
    session.last_activity = time.time()

    if message_type == "user_input":
        session.status = "running"

    return msg.id


def poll_for_work(session_id: str, timeout: float = 30.0) -> list[dict]:
    """CLI worker polls for pending messages (long-poll)."""
    session = get_session(session_id)
    if not session:
        return []

    session.last_heartbeat = time.time()
    session.worker_connected = True

    # Wait for messages up to timeout
    start = time.time()
    while time.time() - start < timeout:
        if session.inbound:
            with _lock:
                messages = list(session.inbound)
                session.inbound.clear()
            return [{"id": m.id, "type": m.type, "content": m.content, "data": m.data} for m in messages]
        time.sleep(0.5)

    return []  # Timeout -- no messages


def send_to_web(session_id: str, message_type: str, content: str, data: dict = None) -> str:
    """Send message from CLI worker to web UI."""
    session = get_session(session_id)
    if not session:
        raise ValueError(f"Session {session_id} not found")

    msg = BridgeMessage(
        type=message_type,
        content=content,
        data=data or {},
    )
    session.outbound.append(msg)
    session.last_activity = time.time()

    if message_type == "result":
        session.status = "idle"
    elif message_type == "control_request":
        session.status = "waiting_input"

    return msg.id


def get_events(session_id: str, after: float = 0) -> list[dict]:
    """Get outbound messages for web UI (SSE events)."""
    session = get_session(session_id)
    if not session:
        return []

    events = []
    remaining = []
    for msg in session.outbound:
        if msg.timestamp > after and not msg.delivered:
            events.append({
                "id": msg.id,
                "type": msg.type,
                "content": msg.content,
                "data": msg.data,
                "timestamp": msg.timestamp,
            })
            msg.delivered = True
        remaining.append(msg)

    # Keep only last 100 messages
    if len(remaining) > 100:
        session.outbound = remaining[-100:]

    return events


# == Heartbeat & Cleanup ==

def heartbeat(session_id: str) -> dict:
    """Worker heartbeat -- keeps session alive."""
    session = get_session(session_id)
    if not session:
        return {"error": "session_not_found"}

    session.last_heartbeat = time.time()
    session.worker_connected = True

    return {
        "status": session.status,
        "pending_messages": len(session.inbound),
    }


def cleanup_dead_sessions():
    """Remove sessions that have not heartbeated in SESSION_TIMEOUT."""
    with _lock:
        dead = [sid for sid, s in _bridge_sessions.items() if not s.is_alive()]
        for sid in dead:
            session = _bridge_sessions.pop(sid)
            if session.pointer_path:
                try:
                    Path(session.pointer_path).unlink(missing_ok=True)
                except Exception:
                    pass
            logger.info(f"Bridge session expired: {sid}")
    return len(dead)


# == Crash Recovery ==

def recover_sessions() -> int:
    """Recover sessions from pointer files after crash."""
    pointer_dir = config.CLOW_HOME / "bridge_pointers"
    if not pointer_dir.exists():
        return 0

    recovered = 0
    for pointer in pointer_dir.glob("*.json"):
        try:
            data = json.loads(pointer.read_text())
            session_id = data.get("session_id")
            if session_id and session_id not in _bridge_sessions:
                session = BridgeSession(
                    id=session_id,
                    user_id=data.get("user_id", ""),
                    environment_id=data.get("environment_id", ""),
                    created_at=data.get("created_at", time.time()),
                    pointer_path=str(pointer),
                )
                session.reconnect_count += 1
                if session.reconnect_count <= MAX_RECONNECT_ATTEMPTS:
                    _bridge_sessions[session_id] = session
                    recovered += 1
                    logger.info(f"Bridge session recovered: {session_id}")
                else:
                    pointer.unlink(missing_ok=True)
        except Exception:
            pointer.unlink(missing_ok=True)

    return recovered


# == Background Cleanup Thread ==

def _cleanup_loop():
    """Background thread that cleans dead sessions every 60s."""
    while True:
        try:
            cleanup_dead_sessions()
        except Exception:
            pass
        time.sleep(60)

_cleanup_thread = threading.Thread(target=_cleanup_loop, daemon=True, name="bridge-cleanup")
_cleanup_thread.start()
