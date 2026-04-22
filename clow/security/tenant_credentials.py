"""Tenant credentials — armazenamento criptografado por user_id.

Cada tenant pode ter suas proprias credenciais (Meta Ads, Z-API, etc)
guardadas em formato Fernet (criptografia simetrica AES-128-CBC + HMAC).

Chave: CLOW_FERNET_KEY no .env (server-side only, NUNCA exposta).

Uso:
    from clow.security.tenant_credentials import set_secret, get_secret
    set_secret(user_id, "meta_ads", access_token, scope={"act_ids": ["123"]})
    token = get_secret(user_id, "meta_ads")  # decifra on-demand
"""
from __future__ import annotations
import os
import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from ..database import get_db


_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    """Lazy-init do Fernet. Levanta se chave nao existir."""
    global _fernet
    if _fernet is not None:
        return _fernet
    key = os.getenv("CLOW_FERNET_KEY")
    if not key:
        raise RuntimeError(
            "CLOW_FERNET_KEY nao setada. Gere com: "
            "python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())' "
            "e adicione ao .env"
        )
    _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def _ensure_table() -> None:
    """Cria tabela se nao existir. Idempotente."""
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS tenant_credentials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                encrypted_token BLOB NOT NULL,
                scope_json TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, provider)
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_tc_user_provider ON tenant_credentials(user_id, provider)")
        db.commit()


def set_secret(user_id: str, provider: str, token: str, scope: dict[str, Any] | None = None) -> None:
    """Salva (ou atualiza) credencial criptografada para o tenant."""
    if not user_id or not provider or not token:
        raise ValueError("user_id, provider e token sao obrigatorios")
    _ensure_table()
    f = _get_fernet()
    encrypted = f.encrypt(token.encode("utf-8"))
    scope_json = json.dumps(scope or {})
    with get_db() as db:
        db.execute("""
            INSERT INTO tenant_credentials (user_id, provider, encrypted_token, scope_json)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, provider) DO UPDATE SET
                encrypted_token=excluded.encrypted_token,
                scope_json=excluded.scope_json,
                updated_at=CURRENT_TIMESTAMP
        """, (user_id, provider, encrypted, scope_json))
        db.commit()


def get_secret(user_id: str, provider: str) -> str | None:
    """Retorna o token decifrado, ou None se nao existir."""
    if not user_id or not provider:
        return None
    _ensure_table()
    with get_db() as db:
        row = db.execute(
            "SELECT encrypted_token FROM tenant_credentials WHERE user_id=? AND provider=?",
            (user_id, provider),
        ).fetchone()
    if not row:
        return None
    try:
        return _get_fernet().decrypt(row[0]).decode("utf-8")
    except InvalidToken:
        return None


def get_scope(user_id: str, provider: str) -> dict[str, Any]:
    """Retorna o escopo (ex: act_ids permitidas) sem decifrar token."""
    _ensure_table()
    with get_db() as db:
        row = db.execute(
            "SELECT scope_json FROM tenant_credentials WHERE user_id=? AND provider=?",
            (user_id, provider),
        ).fetchone()
    if not row or not row[0]:
        return {}
    try:
        return json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return {}


def delete_secret(user_id: str, provider: str) -> bool:
    """Remove credencial. Retorna True se removeu, False se nao existia."""
    _ensure_table()
    with get_db() as db:
        cur = db.execute(
            "DELETE FROM tenant_credentials WHERE user_id=? AND provider=?",
            (user_id, provider),
        )
        db.commit()
        return cur.rowcount > 0


def list_providers(user_id: str) -> list[str]:
    """Lista os providers que o tenant configurou (sem expor tokens)."""
    _ensure_table()
    with get_db() as db:
        rows = db.execute(
            "SELECT provider FROM tenant_credentials WHERE user_id=? ORDER BY provider",
            (user_id,),
        ).fetchall()
    return [r[0] for r in rows]
