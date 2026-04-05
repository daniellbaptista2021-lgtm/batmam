"""API Keys — gerencia chaves para a API publica do Clow.

Cada tenant pode gerar API keys para integrar sistemas externos.
Formato: clow_key_{32_chars_random}
Armazena hash da key (nao o texto puro).
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from pathlib import Path

from . import config
from .logging import log_action

_KEYS_DIR = config.CLOW_HOME / "api_keys"
_KEYS_DIR.mkdir(parents=True, exist_ok=True)

# Index global: hash -> tenant_id (para lookup rapido)
_INDEX_PATH = _KEYS_DIR / "index.json"


def _load_index() -> dict:
    if _INDEX_PATH.exists():
        try:
            return json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_index(index: dict) -> None:
    _INDEX_PATH.write_text(json.dumps(index), encoding="utf-8")


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _tenant_keys_path(tenant_id: str) -> Path:
    d = _KEYS_DIR / tenant_id
    d.mkdir(parents=True, exist_ok=True)
    return d / "keys.json"


def _load_tenant_keys(tenant_id: str) -> list[dict]:
    path = _tenant_keys_path(tenant_id)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_tenant_keys(tenant_id: str, keys: list[dict]) -> None:
    _tenant_keys_path(tenant_id).write_text(json.dumps(keys, indent=2), encoding="utf-8")


def generate_key(tenant_id: str, name: str = "default") -> str:
    """Gera nova API key. Retorna texto puro UMA VEZ."""
    raw = f"clow_key_{secrets.token_hex(16)}"
    hashed = _hash_key(raw)

    # Salva no tenant
    keys = _load_tenant_keys(tenant_id)
    keys.append({
        "id": secrets.token_hex(4),
        "name": name,
        "hash": hashed,
        "last4": raw[-4:],
        "created_at": time.time(),
        "last_used": 0,
    })
    _save_tenant_keys(tenant_id, keys)

    # Index global
    index = _load_index()
    index[hashed] = tenant_id
    _save_index(index)

    log_action("api_key_created", f"tenant={tenant_id} name={name}")
    return raw


def validate_key(api_key: str) -> str | None:
    """Valida API key. Retorna tenant_id ou None."""
    if not api_key.startswith("clow_key_"):
        return None
    hashed = _hash_key(api_key)
    index = _load_index()
    tenant_id = index.get(hashed)
    if tenant_id:
        # Atualiza last_used
        keys = _load_tenant_keys(tenant_id)
        for k in keys:
            if k.get("hash") == hashed:
                k["last_used"] = time.time()
                break
        _save_tenant_keys(tenant_id, keys)
    return tenant_id


def revoke_key(tenant_id: str, key_id: str) -> bool:
    """Revoga uma API key."""
    keys = _load_tenant_keys(tenant_id)
    to_remove = next((k for k in keys if k.get("id") == key_id), None)
    if not to_remove:
        return False

    # Remove do index
    index = _load_index()
    h = to_remove.get("hash", "")
    if h in index:
        del index[h]
        _save_index(index)

    keys = [k for k in keys if k.get("id") != key_id]
    _save_tenant_keys(tenant_id, keys)
    log_action("api_key_revoked", f"tenant={tenant_id} id={key_id}")
    return True


def list_keys(tenant_id: str) -> list[dict]:
    """Lista API keys mascaradas."""
    keys = _load_tenant_keys(tenant_id)
    return [{"id": k["id"], "name": k.get("name", ""), "last4": k.get("last4", ""),
             "created_at": k.get("created_at"), "last_used": k.get("last_used")} for k in keys]
