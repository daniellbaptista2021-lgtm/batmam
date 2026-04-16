"""Gerenciamento de sessões do Clow — com isolamento por usuário."""

from __future__ import annotations
import hashlib
import json
import time
from pathlib import Path
from typing import Any
from .config import SESSIONS_DIR
from .models import Session


def _user_sessions_dir(user_id: str | None) -> Path:
    """Retorna diretório de sessões do usuário (ou global se user_id=None)."""
    if not user_id:
        return SESSIONS_DIR
    safe = hashlib.sha256(user_id.encode()).hexdigest()[:16]
    d = SESSIONS_DIR / safe
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_session(session: Session, user_id: str | None = None) -> Path:
    """Salva sessão em disco, isolada por usuário."""
    sessions_dir = _user_sessions_dir(user_id)
    filepath = sessions_dir / f"{session.id}.json"

    data = {
        "id": session.id,
        "user_id": user_id or "",
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


def load_session(session_id: str, user_id: str | None = None) -> Session | None:
    """Carrega sessão do disco, buscando no diretório do usuário."""
    sessions_dir = _user_sessions_dir(user_id)
    filepath = sessions_dir / f"{session_id}.json"

    # Fallback: tenta diretório global se não encontrou no do usuário
    if not filepath.exists() and user_id:
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


def list_sessions(user_id: str | None = None) -> list[dict[str, Any]]:
    """Lista sessões do usuário (ou todas se user_id=None)."""
    sessions_dir = _user_sessions_dir(user_id)
    sessions = []

    for filepath in sorted(sessions_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            sessions.append({
                "id": data["id"],
                "user_id": data.get("user_id", ""),
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


def delete_session(session_id: str, user_id: str | None = None) -> bool:
    """Deleta uma sessão do usuário."""
    sessions_dir = _user_sessions_dir(user_id)
    filepath = sessions_dir / f"{session_id}.json"

    # Fallback para diretório global
    if not filepath.exists() and user_id:
        filepath = SESSIONS_DIR / f"{session_id}.json"

    if filepath.exists():
        filepath.unlink()
        return True
    return False
