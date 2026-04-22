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

def test_zapi_connection(instance_id: str, token: str, client_token: str = "") -> dict:
    """Testa credenciais Z-API. client_token = Account Security Token (Z-API exige em todo request)."""
    if not instance_id:
        return {"ok": False, "error": "Informe o Instance ID."}
    if not token:
        return {"ok": False, "error": "Informe o Token da instancia."}
    if not client_token:
        return {"ok": False, "error": "Informe o Client-Token (Account Security Token). Pegue em app.z-api.io > Account > Security Token."}
    url = f"https://api.z-api.io/instances/{instance_id}/token/{token}/status"
    result = _api("GET", url, headers={"Client-Token": client_token})
    # _api retorna {"error": int_code, "message": body_str} em HTTP error
    err_code = result.get("error")
    msg = str(result.get("message") or "").lower()
    err_text = str(err_code or "").lower() if not isinstance(err_code, int) else ""
    full_text = msg + " " + err_text
    # Z-API responde "You are already connected" quando a instancia ja esta
    # pareada e online. Isso e SUCESSO, nao erro.
    if "already connected" in full_text:
        return {"ok": True, "status": "connected", "raw": result, "note": "Instancia ja conectada ao WhatsApp."}
    if "instance not found" in full_text:
        return {"ok": False, "error": "Instance ID nao encontrado. Confira no painel app.z-api.io > Instances. Atencao: confunde-se O com 0."}
    if "client-token" in full_text or "client_token" in full_text:
        return {"ok": False, "error": "Client-Token invalido. Pegue o correto em app.z-api.io > Account > Security Token."}
    if (isinstance(err_code, int) and err_code in (401, 403)) or "unauthorized" in full_text:
        return {"ok": False, "error": "Token da instancia invalido ou sem permissao."}
    if err_code:
        # outras falhas — mostra mensagem da Z-API se houver
        body = result.get("message") or str(err_code)
        return {"ok": False, "error": "Z-API: " + str(body)[:200]}
    connected = bool(result.get("connected", False))
    if not connected:
        return {"ok": False, "status": "disconnected", "error": "Instancia existe mas o WhatsApp nao esta pareado. Escaneie o QR no painel da Z-API.", "raw": result}
    return {"ok": True, "status": "connected", "raw": result}


def register_zapi_webhook(instance_id: str, token: str, client_token: str, webhook_url: str) -> dict:
    """Configura URL de webhook on-message-received na Z-API."""
    if not (instance_id and token and client_token and webhook_url):
        return {"ok": False, "error": "missing_args"}
    url = f"https://api.z-api.io/instances/{instance_id}/token/{token}/update-webhook-received"
    result = _api("POST", url, data={"value": webhook_url}, headers={"Client-Token": client_token, "Content-Type": "application/json"})
    if result.get("error"):
        return {"ok": False, "error": result["error"]}
    return {"ok": True, "webhook_url": webhook_url}


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
    """Full provisioning: creates an isolated Chatwoot account + admin user
    for this Clow customer. The Chatwoot password is returned **only on the
    first successful provisioning call**, so the frontend can show it once
    and the customer must save it. Subsequent calls return
    ``password_delivered=True`` without leaking the password again.
    """
    from ..database import (
        get_chatwoot_connection_by_user, create_chatwoot_connection,
        update_chatwoot_connection,
    )

    existing = get_chatwoot_connection_by_user(user_id)
    if existing and existing.get("chatwoot_account_id"):
        return {
            "ok": True,
            "already_provisioned": True,
            "chatwoot_account_id": existing["chatwoot_account_id"],
            "chatwoot_login_email": email,
            "chatwoot_login_url": _cw_external_url(),
            "password_delivered": bool(existing.get("password_delivered_at")),
        }

    # 1. Create Chatwoot account (isolated tenant — never the admin's account)
    account = create_chatwoot_account(name or email.split("@")[0])
    if not account or not account.get("id"):
        return {"error": "Falha ao criar conta no Chatwoot", "detail": str(account)}

    account_id = account["id"]
    if int(account_id) == int(os.getenv("CHATWOOT_ADMIN_ACCOUNT_ID", "1")):
        # Defensive guard: the Platform API should never hand back the admin
        # account, but if it ever does (misconfig), refuse to bind a customer
        # to it instead of leaking the admin's inboxes.
        logger.error(f"provision_user: refusing to bind user {user_id} to admin account_id={account_id}")
        return {"error": "Conta Chatwoot retornou ID do admin (configuracao invalida). Contato suporte."}

    # 2. Create Chatwoot user with random password
    cw_user = create_chatwoot_user(email, name or email.split("@")[0], account_id)
    if not cw_user:
        return {"error": "Falha ao criar usuario no Chatwoot"}

    cw_password = cw_user.get("chatwoot_password", "")
    cw_user_id_int = cw_user.get("chatwoot_user_id") or 0

    # 3. Persist connection (with password kept temporarily for one-shot reveal)
    create_chatwoot_connection(
        user_id=user_id,
        chatwoot_url=_cw_url(),
        chatwoot_token=cw_user["chatwoot_user_token"],
        chatwoot_account_id=account_id,
        chatwoot_user_token=cw_user["chatwoot_user_token"],
        chatwoot_user_id=cw_user_id_int,
        chatwoot_password_temp=cw_password,
    )

    # 4. Best-effort: deliver credentials by email if SMTP is configured
    email_sent = _deliver_credentials_email(email, name, cw_password)

    # 5. Mark as delivered immediately so we never expose this password again
    #    via the API. The frontend gets it ONCE in this response.
    try:
        from ..database import mark_chatwoot_password_delivered
        mark_chatwoot_password_delivered(user_id)
    except Exception as e:
        logger.warning(f"provision_user: mark_password_delivered failed: {e}")

    return {
        "ok": True,
        "chatwoot_account_id": account_id,
        "chatwoot_login_email": email,
        "chatwoot_login_password": cw_password,  # one-time reveal
        "chatwoot_login_url": _cw_external_url(),
        "password_delivered": True,
        "email_sent": email_sent,
        "warning": "Salve esta senha agora. Ela nao sera exibida novamente.",
    }


# ── Credentials delivery (email) ─────────────────────────────────

def _deliver_credentials_email(to_email: str, name: str, password: str) -> bool:
    """Send Chatwoot credentials via SMTP if configured. Returns True on success."""
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_pass = os.getenv("SMTP_PASSWORD", "").strip()
    smtp_from = os.getenv("SMTP_FROM", smtp_user).strip()
    if not (smtp_host and smtp_user and smtp_pass and to_email):
        return False
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.utils import formataddr

        cw_url = _cw_external_url()
        body = (
            f"Ola{(' ' + name) if name else ''},\n\n"
            f"Sua conta no CRM esta pronta. Acesse o painel para gerenciar\n"
            f"suas conversas do WhatsApp:\n\n"
            f"  Link:  {cw_url}\n"
            f"  Login: {to_email}\n"
            f"  Senha: {password}\n\n"
            f"Por seguranca, troque a senha apos o primeiro acesso.\n"
        )
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = "Suas credenciais do CRM (Chatwoot)"
        msg["From"] = formataddr(("Clow", smtp_from))
        msg["To"] = to_email

        port = int(os.getenv("SMTP_PORT", "587"))
        with smtplib.SMTP(smtp_host, port, timeout=15) as s:
            s.starttls()
            s.login(smtp_user, smtp_pass)
            s.sendmail(smtp_from, [to_email], msg.as_string())
        return True
    except Exception as e:
        logger.warning(f"_deliver_credentials_email failed: {e}")
        return False
