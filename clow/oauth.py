"""OAuth 2.0 com PKCE (Proof Key for Code Exchange) do Clow.

Implementa fluxo OAuth com PKCE S256 para integracao segura com
servicos externos (GitHub, Google, etc.) sem expor client_secret.

Fluxo:
1. Gera code_verifier + code_challenge (S256)
2. Abre navegador para authorization URL
3. Recebe callback com authorization code
4. Troca code + verifier por access token
5. Persiste credencial em ~/.clow/credentials/

Configuracao em settings.json:

{
  "oauth": {
    "github": {
      "client_id": "xxx",
      "auth_url": "https://github.com/login/oauth/authorize",
      "token_url": "https://github.com/login/oauth/access_token",
      "scopes": ["repo", "read:user"],
      "redirect_uri": "http://localhost:9876/callback"
    }
  }
}
"""

from __future__ import annotations
import hashlib
import base64
import secrets
import json
import time
import os
import tempfile
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs
from dataclasses import dataclass
from . import config
from .logging import log_action


CREDENTIALS_DIR = config.CLOW_HOME / "credentials"
CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class OAuthCredential:
    """Credencial OAuth persistida."""
    provider: str
    access_token: str
    refresh_token: str = ""
    token_type: str = "bearer"
    expires_at: float = 0.0
    scopes: list[str] | None = None

    @property
    def is_expired(self) -> bool:
        if self.expires_at <= 0:
            return False  # Sem expiracao definida
        return time.time() >= self.expires_at

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_type": self.token_type,
            "expires_at": self.expires_at,
            "scopes": self.scopes or [],
        }

    @classmethod
    def from_dict(cls, data: dict) -> OAuthCredential:
        return cls(
            provider=data.get("provider", ""),
            access_token=data.get("access_token", ""),
            refresh_token=data.get("refresh_token", ""),
            token_type=data.get("token_type", "bearer"),
            expires_at=data.get("expires_at", 0.0),
            scopes=data.get("scopes"),
        )


@dataclass
class PKCEChallenge:
    """Par code_verifier + code_challenge para PKCE."""
    code_verifier: str
    code_challenge: str
    method: str = "S256"


def generate_pkce() -> PKCEChallenge:
    """Gera par PKCE com S256.

    code_verifier: 43-128 caracteres aleatorios URL-safe
    code_challenge: SHA256(verifier) em base64url sem padding
    """
    # Gera 32 bytes = 43 chars em base64url
    verifier_bytes = secrets.token_bytes(32)
    code_verifier = base64url_encode(verifier_bytes)

    # SHA256 do verifier
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64url_encode(digest)

    return PKCEChallenge(
        code_verifier=code_verifier,
        code_challenge=code_challenge,
        method="S256",
    )


def base64url_encode(data: bytes) -> str:
    """Base64url encoding sem padding (RFC 7636)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def build_authorization_url(
    auth_url: str,
    client_id: str,
    redirect_uri: str,
    scopes: list[str],
    pkce: PKCEChallenge,
    state: str | None = None,
) -> str:
    """Constroi a URL de autorizacao com PKCE."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "code_challenge": pkce.code_challenge,
        "code_challenge_method": pkce.method,
    }
    if state:
        params["state"] = state
    else:
        params["state"] = secrets.token_hex(16)

    return f"{auth_url}?{urlencode(params)}"


def exchange_code_for_token(
    token_url: str,
    client_id: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> OAuthCredential | None:
    """Troca authorization code + verifier por access token."""
    try:
        import requests
    except ImportError:
        log_action("oauth_error", "requests nao instalado", level="error")
        return None

    try:
        resp = requests.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            },
            headers={"Accept": "application/json"},
            timeout=30,
        )

        if resp.status_code != 200:
            log_action("oauth_error", f"Token exchange failed: {resp.status_code}", level="error")
            return None

        data = resp.json()
        expires_in = data.get("expires_in", 0)
        expires_at = time.time() + expires_in if expires_in else 0.0

        return OAuthCredential(
            provider="",
            access_token=data.get("access_token", ""),
            refresh_token=data.get("refresh_token", ""),
            token_type=data.get("token_type", "bearer"),
            expires_at=expires_at,
            scopes=data.get("scope", "").split() if data.get("scope") else None,
        )

    except Exception as e:
        log_action("oauth_error", f"Token exchange error: {e}", level="error")
        return None


def refresh_access_token(
    token_url: str,
    client_id: str,
    refresh_token: str,
) -> OAuthCredential | None:
    """Renova access token usando refresh token."""
    try:
        import requests
    except ImportError:
        return None

    try:
        resp = requests.post(
            token_url,
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": refresh_token,
            },
            headers={"Accept": "application/json"},
            timeout=30,
        )

        if resp.status_code != 200:
            return None

        data = resp.json()
        expires_in = data.get("expires_in", 0)
        expires_at = time.time() + expires_in if expires_in else 0.0

        return OAuthCredential(
            provider="",
            access_token=data.get("access_token", ""),
            refresh_token=data.get("refresh_token", refresh_token),
            token_type=data.get("token_type", "bearer"),
            expires_at=expires_at,
            scopes=data.get("scope", "").split() if data.get("scope") else None,
        )

    except Exception:
        return None


# ── Persistencia de credenciais ─────────────────────────────────

def save_credential(cred: OAuthCredential) -> None:
    """Salva credencial de forma atomica em ~/.clow/credentials/."""
    cred_file = CREDENTIALS_DIR / f"{cred.provider}.json"

    # Escrita atomica via arquivo temporario
    fd, tmp_path = tempfile.mkstemp(
        dir=str(CREDENTIALS_DIR),
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(cred.to_dict(), f, indent=2)
        # Renomeia atomicamente
        Path(tmp_path).replace(cred_file)
        # Restringe permissoes: somente o dono pode ler/escrever
        os.chmod(cred_file, 0o600)
        log_action("oauth_saved", f"Credential saved: {cred.provider}")
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def load_credential(provider: str) -> OAuthCredential | None:
    """Carrega credencial salva para um provider."""
    cred_file = CREDENTIALS_DIR / f"{provider}.json"
    if not cred_file.exists():
        return None

    try:
        with open(cred_file) as f:
            data = json.load(f)
        cred = OAuthCredential.from_dict(data)
        cred.provider = provider
        return cred
    except (json.JSONDecodeError, OSError):
        return None


def delete_credential(provider: str) -> bool:
    """Remove credencial salva."""
    cred_file = CREDENTIALS_DIR / f"{provider}.json"
    if cred_file.exists():
        cred_file.unlink()
        return True
    return False


def list_credentials() -> list[dict]:
    """Lista todas as credenciais salvas (sem tokens)."""
    result = []
    for cred_file in CREDENTIALS_DIR.glob("*.json"):
        try:
            with open(cred_file) as f:
                data = json.load(f)
            result.append({
                "provider": cred_file.stem,
                "has_token": bool(data.get("access_token")),
                "expired": OAuthCredential.from_dict(data).is_expired,
                "scopes": data.get("scopes", []),
            })
        except (json.JSONDecodeError, OSError):
            continue
    return result


def parse_callback_params(url: str) -> dict[str, str]:
    """Extrai parametros de callback URL (code, state, error)."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    return {k: v[0] for k, v in params.items()}
