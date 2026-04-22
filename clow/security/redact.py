"""Secret redaction for logs, tool outputs, and message history.

Used to prevent leaking credentials/tokens into:
- log streams (journalctl, file handlers)
- tool_result content sent back to the LLM
- session message history persisted to disk/DB

Design goals:
- Zero false negatives on well-known patterns (Bearer, sk-*, EAA*, Z-API hex)
- Automatically redact every VALUE of any variable in .env / process env
- Safe to call on any stringifiable object
"""
from __future__ import annotations
import os
import re
from pathlib import Path
from typing import Any

REDACTED = "***REDACTED***"

# Known secret-shaped patterns (token types we see in this stack)
_STATIC_PATTERNS = [
    # Access-token query/body (?access_token=...  access_token=...)
    (re.compile(r"(?i)(access[_-]?token\s*[=:]\s*)([^&\s\"\',}]+)"), r"\1" + REDACTED),
    # Bearer <token>
    (re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._\-]{16,}"), r"\1" + REDACTED),
    # api_access_token header (Chatwoot Platform API)
    (re.compile(r"(?i)(api[_-]access[_-]?token\s*[=:]\s*)([^&\s\"\',}]+)"), r"\1" + REDACTED),
    # Client-Token header (Z-API)
    (re.compile(r"(?i)(Client[_-]?Token\s*[=:]\s*)([^&\s\"\',}]+)"), r"\1" + REDACTED),
    # OpenAI / DeepSeek api keys: sk-... (20+ chars)
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b"), REDACTED),
    # Meta Graph tokens: EAA... (Facebook long-lived)
    (re.compile(r"\bEAA[A-Za-z0-9]{40,}\b"), REDACTED),
    # Stripe keys: sk_live_, sk_test_, pk_live_, pk_test_, rk_live_
    (re.compile(r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b"), REDACTED),
    # Stripe price IDs são públicos, nao redact
    # Chatwoot user/platform tokens (22-char Base64-ish)
    (re.compile(r"(?i)(chatwoot[_-][a-z_]*token\s*[=:]\s*)([A-Za-z0-9_\-]{16,})"), r"\1" + REDACTED),
    # GitHub PATs
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), REDACTED),
    # Slack tokens
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b"), REDACTED),
    # AWS access keys
    (re.compile(r"\bAKIA[A-Z0-9]{16}\b"), REDACTED),
    # Generic cookie value (session cookies)
    (re.compile(r"(?i)(cw_d_session_info\s*=\s*)([^;\s]+)"), r"\1" + REDACTED),
    (re.compile(r"(?i)(_chatwoot_session\s*=\s*)([^;\s]+)"), r"\1" + REDACTED),
    (re.compile(r"(?i)(clow_session\s*=\s*)([^;\s]+)"), r"\1" + REDACTED),
]


def _load_env_values() -> set[str]:
    """Return the SET of values of any sensitive variable in .env / process env.
    Any string in this set is redacted on sight."""
    values: set[str] = set()
    env_files = [
        "/root/.clow/app/.env",
        "/root/clow/.env",
    ]
    for path in env_files:
        try:
            p = Path(path)
            if not p.exists():
                continue
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip("\"'")
                if not val or len(val) < 8:
                    continue
                # Only redact if key looks sensitive
                if _is_sensitive_key(key):
                    values.add(val)
        except Exception:
            continue
    # Also add from current process env (for anything overridden at runtime)
    for k, v in os.environ.items():
        if v and len(v) >= 8 and _is_sensitive_key(k):
            values.add(v)
    return values


_SENSITIVE_KEY_PATTERNS = (
    "token", "secret", "key", "password", "pass", "client_token",
    "api_key", "access_token", "private", "credential",
)


def _is_sensitive_key(key: str) -> bool:
    k = key.lower()
    # Allowlist: keys that are named like secrets but are actually public
    if k in {"clow_max_tokens", "clow_model", "chatwoot_url", "chatwoot_external_url",
             "system_clow_url", "deepseek_base_url", "deepseek_model",
             "deepseek_reasoner_model", "stripe_webhook_endpoint"}:
        return False
    return any(p in k for p in _SENSITIVE_KEY_PATTERNS)


# Load once at import time, refresh lazily
_env_values: set[str] = set()
_env_loaded: bool = False


def _ensure_env_values() -> set[str]:
    global _env_loaded, _env_values
    if not _env_loaded:
        try:
            _env_values = _load_env_values()
        except Exception:
            _env_values = set()
        _env_loaded = True
    return _env_values


def refresh_env_values() -> None:
    """Force re-read of .env values. Call after rotating secrets."""
    global _env_loaded
    _env_loaded = False
    _ensure_env_values()


def redact(value: Any) -> str:
    """Redact any secrets in a string. Safe on any input type."""
    if value is None:
        return ""
    if not isinstance(value, str):
        try:
            value = str(value)
        except Exception:
            return REDACTED

    out = value

    # 1) Pattern-based (token shapes)
    for pat, repl in _STATIC_PATTERNS:
        try:
            out = pat.sub(repl, out)
        except Exception:
            continue

    # 2) Value-based (any known sensitive value from .env)
    env_vals = _ensure_env_values()
    for v in env_vals:
        if v and v in out:
            out = out.replace(v, REDACTED)

    return out


def redact_dict(d: dict) -> dict:
    """Deep-redact every string value in a dict (returns new dict)."""
    result = {}
    for k, v in d.items():
        if isinstance(v, str):
            result[k] = redact(v)
        elif isinstance(v, dict):
            result[k] = redact_dict(v)
        elif isinstance(v, list):
            result[k] = [redact(item) if isinstance(item, str)
                         else redact_dict(item) if isinstance(item, dict)
                         else item for item in v]
        else:
            result[k] = v
    return result
