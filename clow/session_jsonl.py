"""Session Persistence — JSONL format (Claude Code Architecture).

Append-only JSONL files for conversation persistence.
Each line is a self-contained JSON entry with type field.
Supports resume via parent-UUID chain walks.
"""

import json
import os
import time
import uuid
from pathlib import Path
from . import config

SESSIONS_DIR = config.CLOW_HOME / "sessions_jsonl"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def _session_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{session_id}.jsonl"


def append_entry(session_id: str, entry_type: str, data: dict) -> None:
    """Append a single entry to the session JSONL file."""
    entry = {
        "uuid": uuid.uuid4().hex[:12],
        "type": entry_type,
        "timestamp": time.time(),
        **data,
    }
    path = _session_path(session_id)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def append_message(session_id: str, role: str, content: str, parent_uuid: str = "") -> str:
    """Append a message entry. Returns the UUID."""
    msg_uuid = uuid.uuid4().hex[:12]
    entry = {
        "uuid": msg_uuid,
        "type": "message",
        "role": role,
        "content": content,
        "parent_uuid": parent_uuid,
        "timestamp": time.time(),
    }
    path = _session_path(session_id)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return msg_uuid


def append_tool_use(session_id: str, tool_name: str, tool_args: dict, tool_id: str, parent_uuid: str = "") -> str:
    """Append a tool use entry."""
    entry_uuid = uuid.uuid4().hex[:12]
    entry = {
        "uuid": entry_uuid,
        "type": "tool_use",
        "tool_name": tool_name,
        "tool_args": tool_args,
        "tool_id": tool_id,
        "parent_uuid": parent_uuid,
        "timestamp": time.time(),
    }
    path = _session_path(session_id)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry_uuid


def append_tool_result(session_id: str, tool_id: str, status: str, output: str, parent_uuid: str = "") -> str:
    """Append a tool result entry."""
    entry_uuid = uuid.uuid4().hex[:12]
    entry = {
        "uuid": entry_uuid,
        "type": "tool_result",
        "tool_id": tool_id,
        "status": status,
        "output": output[:5000],  # Cap output size
        "parent_uuid": parent_uuid,
        "timestamp": time.time(),
    }
    path = _session_path(session_id)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry_uuid


def append_compact(session_id: str, summary: str) -> None:
    """Append a compaction summary entry."""
    append_entry(session_id, "compact", {"summary": summary})


def append_metadata(session_id: str, key: str, value: str) -> None:
    """Append metadata entry (title, tag, etc)."""
    append_entry(session_id, "metadata", {"key": key, "value": value})


def load_session(session_id: str) -> list[dict]:
    """Load all entries from a session JSONL file."""
    path = _session_path(session_id)
    if not path.exists():
        return []
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return entries


def build_conversation_chain(entries: list[dict]) -> list[dict]:
    """Build conversation chain from JSONL entries (Claude Code parent-UUID walk).

    Walks from the latest message backwards via parent_uuid links.
    Returns messages in chronological order.
    """
    if not entries:
        return []

    # Build UUID index
    by_uuid = {e["uuid"]: e for e in entries if "uuid" in e}

    # Find latest message
    messages = [e for e in entries if e.get("type") == "message"]
    if not messages:
        return []

    latest = messages[-1]

    # Walk backwards via parent_uuid
    chain = []
    current = latest
    seen = set()
    while current and current["uuid"] not in seen:
        seen.add(current["uuid"])
        chain.append(current)
        parent_uuid = current.get("parent_uuid", "")
        current = by_uuid.get(parent_uuid) if parent_uuid else None

    chain.reverse()
    return chain


def list_sessions() -> list[dict]:
    """List all sessions with metadata."""
    sessions = []
    for path in sorted(SESSIONS_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            # Read first and last lines for metadata
            with open(path, "r", encoding="utf-8") as f:
                first_line = f.readline().strip()
                lines = f.readlines()
                last_line = lines[-1].strip() if lines else first_line

            first = json.loads(first_line) if first_line else {}
            last = json.loads(last_line) if last_line else {}

            sessions.append({
                "id": path.stem,
                "created_at": first.get("timestamp", 0),
                "updated_at": last.get("timestamp", 0),
                "size": path.stat().st_size,
            })
        except Exception:
            continue

    return sessions[:50]  # Last 50 sessions
