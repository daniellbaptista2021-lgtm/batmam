"""Gerenciador de credenciais encriptadas por usuario."""
from __future__ import annotations
import json
import hashlib
from pathlib import Path
from cryptography.fernet import Fernet

CRED_DIR = Path.home() / ".clow" / "users"

# Schemas de campos por servico
SCHEMAS: dict[str, list[dict]] = {
    "meta": [
        {"key": "app_id", "label": "App ID", "secret": False},
        {"key": "app_secret", "label": "App Secret", "secret": True},
        {"key": "access_token", "label": "Access Token", "secret": True},
        {"key": "ad_account_id", "label": "Ad Account ID (ex: act_123)", "secret": False},
    ],
    "google": [
        {"key": "credentials_json", "label": "Service Account JSON (cole o conteudo)", "secret": True},
    ],
    "supabase": [
        {"key": "url", "label": "Project URL (ex: https://xxx.supabase.co)", "secret": False},
        {"key": "service_key", "label": "Service Role Key", "secret": True},
    ],
    "postgres": [
        {"key": "host", "label": "Host", "secret": False},
        {"key": "port", "label": "Porta", "secret": False},
        {"key": "user", "label": "Usuario", "secret": False},
        {"key": "password", "label": "Senha", "secret": True},
        {"key": "database", "label": "Database", "secret": False},
    ],
    "redis": [
        {"key": "host", "label": "Host", "secret": False},
        {"key": "port", "label": "Porta", "secret": False},
        {"key": "password", "label": "Senha (opcional)", "secret": True},
    ],
    "n8n": [
        {"key": "url", "label": "URL do n8n (ex: https://n8n.exemplo.com)", "secret": False},
        {"key": "api_key", "label": "API Key", "secret": True},
    ],
    "zapi": [
        {"key": "instance_id", "label": "Instance ID", "secret": False},
        {"key": "token", "label": "Token", "secret": True},
    ],
    "gdrive": [
        {"key": "credentials_json", "label": "Service Account JSON", "secret": True},
    ],
    "openai": [
        {"key": "api_key", "label": "API Key", "secret": True},
    ],
    "github": [
        {"key": "token", "label": "Personal Access Token", "secret": True},
    ],
    "vercel": [
        {"key": "token", "label": "Vercel Token", "secret": True},
    ],
    "stripe": [
        {"key": "api_key", "label": "Secret Key (sk_...)", "secret": True},
    ],
    "mercadopago": [
        {"key": "access_token", "label": "Access Token", "secret": True},
    ],
}


def _user_dir(user_id: str) -> Path:
    safe_id = hashlib.sha256(user_id.encode()).hexdigest()[:16]
    d = CRED_DIR / safe_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get_key(user_id: str) -> bytes:
    """Gera chave Fernet deterministica por usuario."""
    raw = hashlib.sha256(f"clow_cred_{user_id}_salt_x7k".encode()).digest()
    import base64
    return base64.urlsafe_b64encode(raw)


def save_credential(user_id: str, service: str, data: dict) -> None:
    key = _get_key(user_id)
    f = Fernet(key)
    encrypted = f.encrypt(json.dumps(data).encode())
    path = _user_dir(user_id) / f"{service}.enc"
    path.write_bytes(encrypted)


def load_credential(user_id: str, service: str) -> dict | None:
    path = _user_dir(user_id) / f"{service}.enc"
    if not path.exists():
        return None
    key = _get_key(user_id)
    f = Fernet(key)
    try:
        decrypted = f.decrypt(path.read_bytes())
        return json.loads(decrypted)
    except Exception:
        return None


def delete_credential(user_id: str, service: str) -> bool:
    path = _user_dir(user_id) / f"{service}.enc"
    if path.exists():
        path.unlink()
        return True
    return False


def list_credentials(user_id: str) -> list[str]:
    d = _user_dir(user_id)
    return [p.stem for p in d.glob("*.enc")]


def get_schema(service: str) -> list[dict] | None:
    return SCHEMAS.get(service)


def list_services() -> list[str]:
    return sorted(SCHEMAS.keys())
