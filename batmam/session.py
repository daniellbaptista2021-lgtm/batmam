"""Gerenciamento de sessões do Batmam."""

from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Any
from .config import SESSIONS_DIR
from .models import Session


def save_session(session: Session) -> Path:
    """Salva sessão em disco."""
    filepath = SESSIONS_DIR / f"{session.id}.json"

    data = {
        "id": session.id,
        "created_at": session.created_at,
        "saved_at": time.time(),
        "cwd": session.cwd,
        "model": session.model,
        "total_tokens_in": session.total_tokens_in,
        "total_tokens_out": session.total_tokens_out,
        "messages": session.messages,
    }

    filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return filepath


def load_session(session_id: str) -> Session | None:
    """Carrega sessão do disco."""
    filepath = SESSIONS_DIR / f"{session_id}.json"

    if not filepath.exists():
        return None

    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
    except Exception:
        return None

    session = Session(
        id=data["id"],
        messages=data.get("messages", []),
        total_tokens_in=data.get("total_tokens_in", 0),
        total_tokens_out=data.get("total_tokens_out", 0),
        created_at=data.get("created_at", 0),
        cwd=data.get("cwd", ""),
        model=data.get("model", ""),
    )
    return session


def list_sessions() -> list[dict[str, Any]]:
    """Lista todas as sessões salvas."""
    sessions = []

    for filepath in sorted(SESSIONS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            sessions.append({
                "id": data["id"],
                "created_at": data.get("created_at", 0),
                "saved_at": data.get("saved_at", 0),
                "cwd": data.get("cwd", ""),
                "model": data.get("model", ""),
                "messages": len(data.get("messages", [])),
                "tokens_in": data.get("total_tokens_in", 0),
                "tokens_out": data.get("total_tokens_out", 0),
            })
        except Exception:
            continue

    return sessions


def delete_session(session_id: str) -> bool:
    """Deleta uma sessão."""
    filepath = SESSIONS_DIR / f"{session_id}.json"
    if filepath.exists():
        filepath.unlink()
        return True
    return False
