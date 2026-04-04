"""Teleport — serializa e transporta sessoes entre interfaces.

Exporta estado completo (messages, checkpoints, configs, modelo)
e importa em qualquer interface (CLI, webapp, PWA, Chrome Extension).
Codigos de 6 digitos temporarios para transfer rapido.
"""

from __future__ import annotations
import gzip
import json
import os
import random
import string
import time
from pathlib import Path
from typing import Any

from . import config
from .session import load_session, save_session
from .checkpoints import list_checkpoints
from .models import Session
from .logging import log_action

# Store de codigos temporarios (codigo -> {session_data, expires_at})
_teleport_codes: dict[str, dict] = {}

TELEPORT_CODE_TTL = 300  # 5 minutos


def export_session(session_id: str) -> dict[str, Any]:
    """Exporta estado completo de uma sessao como dict serializavel.

    Inclui: messages, checkpoints, modelo, cwd, tokens, configs.
    """
    session = load_session(session_id)
    if not session:
        return {"error": f"Sessao '{session_id}' nao encontrada"}

    checkpoints = list_checkpoints(session_id)

    exported = {
        "version": "1.0",
        "type": "clow_teleport",
        "exported_at": time.time(),
        "exported_at_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
        "session": {
            "id": session.id,
            "cwd": session.cwd,
            "model": session.model,
            "created_at": session.created_at,
            "total_tokens_in": session.total_tokens_in,
            "total_tokens_out": session.total_tokens_out,
            "messages": session.messages,
        },
        "checkpoints": checkpoints,
        "config_snapshot": {
            "model": config.CLOW_MODEL,
            "model_heavy": config.CLOW_MODEL_HEAVY,
            "provider": config.CLOW_PROVIDER,
            "max_tokens": config.MAX_TOKENS,
            "temperature": config.TEMPERATURE,
        },
    }

    log_action("teleport_export", f"session={session_id}", session_id=session_id)
    return exported


def export_session_compressed(session_id: str) -> bytes:
    """Exporta sessao como JSON compactado com gzip."""
    data = export_session(session_id)
    json_bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return gzip.compress(json_bytes)


def import_session(data: dict[str, Any]) -> dict[str, Any]:
    """Importa sessao de dados exportados. Cria nova sessao com novo ID.

    Returns dict com novo session_id e status.
    """
    if data.get("type") != "clow_teleport":
        return {"error": "Formato invalido — nao e um export do Clow Teleport"}

    session_data = data.get("session", {})
    if not session_data.get("messages"):
        return {"error": "Sessao vazia — sem mensagens"}

    # Cria nova sessao com os dados importados
    session = Session(
        messages=session_data["messages"],
        total_tokens_in=session_data.get("total_tokens_in", 0),
        total_tokens_out=session_data.get("total_tokens_out", 0),
        created_at=session_data.get("created_at", time.time()),
        cwd=session_data.get("cwd", os.getcwd()),
        model=session_data.get("model", config.CLOW_MODEL),
    )

    # Salva
    filepath = save_session(session)

    log_action(
        "teleport_import",
        f"new_session={session.id} from={session_data.get('id', 'unknown')}",
        session_id=session.id,
    )

    return {
        "success": True,
        "session_id": session.id,
        "original_id": session_data.get("id", ""),
        "messages_count": len(session.messages),
        "tokens_in": session.total_tokens_in,
        "tokens_out": session.total_tokens_out,
        "imported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def import_session_compressed(data: bytes) -> dict[str, Any]:
    """Importa de dados compactados."""
    try:
        json_bytes = gzip.decompress(data)
        parsed = json.loads(json_bytes.decode("utf-8"))
        return import_session(parsed)
    except Exception as e:
        return {"error": f"Falha ao descomprimir: {e}"}


# ── Codigo Temporario de 6 Digitos ────────────────────────────

def generate_teleport_code(session_id: str) -> dict[str, Any]:
    """Gera codigo de 6 digitos para transfer rapido (expira em 5 min)."""
    # Limpa expirados
    _cleanup_expired_codes()

    # Exporta sessao
    data = export_session(session_id)
    if "error" in data:
        return data

    # Gera codigo unico de 6 digitos
    code = _generate_unique_code()

    _teleport_codes[code] = {
        "session_data": data,
        "expires_at": time.time() + TELEPORT_CODE_TTL,
        "created_at": time.time(),
        "source_session": session_id,
    }

    log_action("teleport_code", f"code={code} session={session_id}", session_id=session_id)

    return {
        "code": code,
        "expires_in": TELEPORT_CODE_TTL,
        "expires_at_iso": time.strftime(
            "%H:%M:%S", time.localtime(time.time() + TELEPORT_CODE_TTL)
        ),
        "session_id": session_id,
    }


def redeem_teleport_code(code: str) -> dict[str, Any]:
    """Resgata codigo de teleport e importa a sessao."""
    _cleanup_expired_codes()

    code = code.strip().upper()
    entry = _teleport_codes.get(code)

    if not entry:
        return {"error": "Codigo invalido ou expirado"}

    if time.time() > entry["expires_at"]:
        del _teleport_codes[code]
        return {"error": "Codigo expirado"}

    # Importa
    result = import_session(entry["session_data"])

    # Remove codigo apos uso (single-use)
    del _teleport_codes[code]

    if result.get("success"):
        result["teleported_from"] = entry["source_session"]
        log_action("teleport_redeem", f"code={code}", session_id=result["session_id"])

    return result


def get_code_info(code: str) -> dict[str, Any] | None:
    """Retorna info de um codigo sem resgatar."""
    code = code.strip().upper()
    entry = _teleport_codes.get(code)
    if not entry or time.time() > entry["expires_at"]:
        return None
    return {
        "code": code,
        "source_session": entry["source_session"],
        "expires_in": int(entry["expires_at"] - time.time()),
        "messages_count": len(entry["session_data"].get("session", {}).get("messages", [])),
    }


def list_active_codes() -> list[dict]:
    """Lista codigos ativos (nao expirados)."""
    _cleanup_expired_codes()
    return [
        {
            "code": code,
            "source_session": entry["source_session"],
            "expires_in": int(entry["expires_at"] - time.time()),
        }
        for code, entry in _teleport_codes.items()
    ]


def _generate_unique_code() -> str:
    """Gera codigo unico de 6 caracteres alfanumericos maiusculos."""
    for _ in range(100):
        code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if code not in _teleport_codes:
            return code
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


def _cleanup_expired_codes() -> None:
    """Remove codigos expirados."""
    now = time.time()
    expired = [c for c, e in _teleport_codes.items() if now > e["expires_at"]]
    for c in expired:
        del _teleport_codes[c]
