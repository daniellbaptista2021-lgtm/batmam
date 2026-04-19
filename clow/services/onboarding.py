"""Onboarding service — provisions Chatwoot accounts + Evolution instances per user."""

import json
import logging
import os
import secrets
import time
import uuid
from urllib.request import urlopen, Request
from urllib.error import HTTPError

logger = logging.getLogger("clow.services.onboarding")

# ── Config ───────────────────────────────────────────────────

def _cw_url():
    return os.getenv("CHATWOOT_URL", "http://localhost:3000").rstrip("/")

def _cw_external_url():
    return os.getenv("CHATWOOT_EXTERNAL_URL", _cw_url()).rstrip("/")

def _cw_platform_token():
    return os.getenv("CHATWOOT_PLATFORM_TOKEN", "")





def _api(method, url, data=None, headers=None, timeout=20):
    """Generic HTTP helper."""
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    body = json.dumps(data).encode() if data else None
    req = Request(url, data=body, headers=hdrs, method=method)
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as e:
        body_text = e.read().decode() if e.fp else ""
        logger.error(f"API {method} {url}: {e.code} {body_text[:300]}")
        return {"error": e.code, "message": body_text[:300]}
    except Exception as e:
        logger.error(f"API error {method} {url}: {e}")
        return {"error": str(e)}


# ── Chatwoot Platform API ────────────────────────────────────

def create_chatwoot_account(user_name: str) -> dict | None:
    """Create a new Chatwoot account via Platform API."""
    token = _cw_platform_token()
    if not token:
        return None
    url = f"{_cw_url()}/platform/api/v1/accounts"
    result = _api("POST", url, {"name": user_name}, {"api_access_token": token})
    if result.get("id"):
        return result
    logger.error(f"create_chatwoot_account failed: {result}")
    return None


def create_chatwoot_user(email: str, name: str, account_id: int) -> dict | None:
    """Create user in Chatwoot and associate with account."""
    token = _cw_platform_token()
    if not token:
        return None
    # Create user
    password = secrets.token_urlsafe(16)
    url = f"{_cw_url()}/platform/api/v1/users"
    user = _api("POST", url, {
        "name": name,
        "email": email,
        "password": password,
    }, {"api_access_token": token})

    if not user.get("id"):
        logger.error(f"create_chatwoot_user failed: {user}")
        return None

    # Associate user with account as administrator
    assoc_url = f"{_cw_url()}/platform/api/v1/accounts/{account_id}/account_users"
    _api("POST", assoc_url, {
        "user_id": user["id"],
        "role": "administrator",
    }, {"api_access_token": token})

    # Get user token for API access
    user_token = user.get("access_token", "")
    return {
        "chatwoot_user_id": user["id"],
        "chatwoot_user_token": user_token,
        "chatwoot_password": password,
    }


# ── WhatsApp Connection Tests ────────────────────────────────

def test_zapi_connection(instance_id: str, token: str) -> dict:
    """Test Z-API credentials by checking instance status."""
    url = f"https://api.z-api.io/instances/{instance_id}/token/{token}/status"
    result = _api("GET", url)
    connected = result.get("connected", False)
    return {"ok": connected, "status": "connected" if connected else "disconnected", "raw": result}


def test_meta_connection(phone_number_id: str, access_token: str) -> dict:
    """Test Meta WhatsApp Business API credentials."""
    url = f"https://graph.facebook.com/v18.0/{phone_number_id}?access_token={access_token}"
    result = _api("GET", url)
    if result.get("id"):
        return {"ok": True, "status": "connected", "phone": result.get("display_phone_number", ""), "name": result.get("verified_name", "")}
    return {"ok": False, "status": "error", "error": result.get("error", {}).get("message", str(result))}


# ── Chatwoot Inbox Creation ───────────────────────────────────

def create_chatwoot_inbox(chatwoot_url: str, chatwoot_token: str, account_id: int,
                           inbox_name: str, webhook_token: str) -> dict | None:
    """Create an API inbox in the user's Chatwoot account."""
    clow_url = os.getenv("CLOW_EXTERNAL_URL", "https://clow.pvcorretor01.com.br")
    url = f"{chatwoot_url}/api/v1/accounts/{account_id}/inboxes"
    result = _api("POST", url, {
        "name": inbox_name,
        "channel": {
            "type": "api",
            "webhook_url": f"{clow_url}/api/v1/chatwoot/webhook/{webhook_token}",
        },
    }, {"api_access_token": chatwoot_token})
    if result.get("id"):
        return result
    logger.error(f"create_chatwoot_inbox failed: {result}")
    return result


def register_chatwoot_webhook(chatwoot_url: str, chatwoot_token: str,
                               account_id: int, webhook_token: str) -> dict:
    """Register Clow bot webhook in user's Chatwoot account."""
    clow_url = os.getenv("CLOW_EXTERNAL_URL", "https://clow.pvcorretor01.com.br")
    webhook_url = f"{clow_url}/api/v1/chatwoot/webhook/{webhook_token}"
    url = f"{chatwoot_url}/api/v1/accounts/{account_id}/webhooks"
    # Check if already exists
    existing = _api("GET", url, headers={"api_access_token": chatwoot_token})
    hooks = existing.get("payload", {}).get("webhooks", [])
    for h in hooks:
        if webhook_token in h.get("url", ""):
            return {"ok": True, "webhook_id": h["id"], "already_existed": True}
    return _api("POST", url, {
        "url": webhook_url,
        "subscriptions": ["message_created", "conversation_updated"],
    }, {"api_access_token": chatwoot_token})


# ── Bot Webhook ──────────────────────────────────────────────

def register_bot_webhook(chatwoot_url: str, chatwoot_token: str,
                          account_id: int, webhook_token: str) -> dict:
    """Register Clow bot webhook in user's Chatwoot account."""
    clow_url = os.getenv("CLOW_EXTERNAL_URL", "https://clow.pvcorretor01.com.br")
    webhook_url = f"{clow_url}/api/v1/chatwoot/webhook/{webhook_token}"
    url = f"{chatwoot_url}/api/v1/accounts/{account_id}/webhooks"
    return _api("POST", url, {
        "url": webhook_url,
        "subscriptions": ["message_created", "conversation_updated"],
    }, {"api_access_token": chatwoot_token})


# ── Full Onboarding Flow ─────────────────────────────────────

def provision_user(user_id: str, email: str, name: str) -> dict:
    """Full provisioning: Chatwoot account + user + save connection.
    Returns dict with connection info or error.
    """
    from ..database import (
        get_chatwoot_connection_by_user, create_chatwoot_connection,
        update_chatwoot_connection,
    )

    # Check if already provisioned
    existing = get_chatwoot_connection_by_user(user_id)
    if existing and existing.get("chatwoot_account_id"):
        return {"ok": True, "connection": existing, "already_provisioned": True}

    # 1. Create Chatwoot account
    account = create_chatwoot_account(name or email.split("@")[0])
    if not account or not account.get("id"):
        return {"error": "Falha ao criar conta no Chatwoot", "detail": str(account)}

    account_id = account["id"]

    # 2. Create Chatwoot user
    cw_user = create_chatwoot_user(email, name or email.split("@")[0], account_id)
    if not cw_user:
        return {"error": "Falha ao criar usuario no Chatwoot"}

    # 3. Save connection
    cw_user_id_int = cw_user.get("chatwoot_user_id") or 0
    if existing:
        update_chatwoot_connection(user_id,
            chatwoot_url=_cw_url(),
            chatwoot_token=cw_user["chatwoot_user_token"],
            chatwoot_account_id=account_id,
        )
        conn = get_chatwoot_connection_by_user(user_id)
    else:
        conn = create_chatwoot_connection(
            user_id=user_id,
            chatwoot_url=_cw_url(),
            chatwoot_token=cw_user["chatwoot_user_token"],
            chatwoot_account_id=account_id,
        )
    # Persiste chatwoot_user_id (pra SSO)
    try:
        from ..database import get_db
        with get_db() as db:
            db.execute(
                "UPDATE chatwoot_connections SET chatwoot_user_id=? WHERE user_id=?",
                (cw_user_id_int, user_id),
            )
            db.commit()
    except Exception as e:
        logger.warning(f"provision_user: cw_user_id update failed: {e}")

    return {
        "ok": True,
        "connection": conn,
        "chatwoot_account_id": account_id,
        "chatwoot_login_email": email,
        "chatwoot_login_password": cw_user.get("chatwoot_password", ""),
        "chatwoot_login_url": "/app/login",
    }
