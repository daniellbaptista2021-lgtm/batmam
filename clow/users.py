"""Users & Roles — gerencia equipe e permissoes por tenant.

Roles: owner (tudo), admin (configura), agent (atende), viewer (visualiza).
"""

from __future__ import annotations

import json
import secrets
import time
from pathlib import Path

from . import config
from .logging import log_action

_TEAM_DIR = config.CLOW_HOME / "teams"
_TEAM_DIR.mkdir(parents=True, exist_ok=True)

ROLES = {
    "owner": {
        "name": "Proprietario",
        "permissions": ["*"],
    },
    "admin": {
        "name": "Administrador",
        "permissions": [
            "crm.*", "whatsapp.*", "leads.*", "conversations.*",
            "settings.preferences", "settings.instances", "settings.training",
            "data.export", "data.import", "users.invite", "users.list",
            "templates.*", "results.view",
        ],
    },
    "agent": {
        "name": "Atendente",
        "permissions": [
            "crm.view", "crm.leads.view", "crm.leads.edit", "crm.leads.move",
            "conversations.view", "conversations.send",
            "settings.preferences", "results.view",
        ],
    },
    "viewer": {
        "name": "Visualizador",
        "permissions": ["crm.view", "crm.leads.view", "conversations.view", "results.view"],
    },
}

USER_LIMITS = {"byok_free": 2, "lite": 2, "starter": 3, "pro": 5, "business": 10}


def _team_path(tenant_id: str) -> Path:
    d = _TEAM_DIR / tenant_id
    d.mkdir(parents=True, exist_ok=True)
    return d / "team.json"


def _invites_path(tenant_id: str) -> Path:
    d = _TEAM_DIR / tenant_id
    d.mkdir(parents=True, exist_ok=True)
    return d / "invites.json"


def _load_team(tenant_id: str) -> list[dict]:
    path = _team_path(tenant_id)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_team(tenant_id: str, team: list[dict]) -> None:
    _team_path(tenant_id).write_text(json.dumps(team, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_invites(tenant_id: str) -> list[dict]:
    path = _invites_path(tenant_id)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_invites(tenant_id: str, invites: list[dict]) -> None:
    _invites_path(tenant_id).write_text(json.dumps(invites, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_owner(tenant_id: str, user_id: str, email: str, name: str = "") -> None:
    """Garante que o owner esta na equipe."""
    team = _load_team(tenant_id)
    if not any(m.get("user_id") == user_id for m in team):
        team.append({
            "user_id": user_id, "email": email, "name": name,
            "role": "owner", "joined_at": time.time(),
        })
        _save_team(tenant_id, team)


def list_members(tenant_id: str) -> list[dict]:
    """Lista membros da equipe."""
    return _load_team(tenant_id)


def get_user_role(tenant_id: str, user_id: str) -> str:
    """Retorna role do usuario."""
    team = _load_team(tenant_id)
    member = next((m for m in team if m.get("user_id") == user_id), None)
    if not member:
        return "owner"  # Default: se nao esta na equipe, e o dono
    return member.get("role", "owner")


def get_permissions(tenant_id: str, user_id: str) -> list[str]:
    """Retorna lista de permissoes do usuario."""
    role = get_user_role(tenant_id, user_id)
    return ROLES.get(role, ROLES["viewer"])["permissions"]


def has_permission(tenant_id: str, user_id: str, permission: str) -> bool:
    """Verifica se usuario tem permissao."""
    perms = get_permissions(tenant_id, user_id)
    if "*" in perms:
        return True
    for p in perms:
        if p == permission:
            return True
        if p.endswith(".*") and permission.startswith(p[:-2]):
            return True
    return False


def invite_user(tenant_id: str, email: str, role: str, invited_by: str) -> dict:
    """Cria convite."""
    if role not in ("admin", "agent", "viewer"):
        return {"error": "Role invalida"}
    invites = _load_invites(tenant_id)
    # Verifica se ja tem convite pendente
    if any(i.get("email") == email and i.get("status") == "pending" for i in invites):
        return {"error": "Convite ja enviado para este email"}
    token = secrets.token_urlsafe(32)
    invite = {
        "id": secrets.token_hex(6),
        "email": email,
        "role": role,
        "token": token,
        "invited_by": invited_by,
        "status": "pending",
        "created_at": time.time(),
        "expires_at": time.time() + 72 * 3600,
    }
    invites.append(invite)
    _save_invites(tenant_id, invites)
    log_action("user_invited", f"tenant={tenant_id} email={email} role={role}")
    return {
        "invite_id": invite["id"],
        "invite_url": f"https://clow.pvcorretor01.com.br/invite/{token}",
        "email": email, "role": role,
        "expires_at": invite["expires_at"],
    }


def get_invite_by_token(token: str) -> tuple[str, dict] | tuple[None, None]:
    """Busca convite pelo token. Retorna (tenant_id, invite) ou (None, None)."""
    if not _TEAM_DIR.exists():
        return None, None
    for td in _TEAM_DIR.iterdir():
        if not td.is_dir():
            continue
        invites = _load_invites(td.name)
        for inv in invites:
            if inv.get("token") == token and inv.get("status") == "pending":
                if inv.get("expires_at", 0) > time.time():
                    return td.name, inv
    return None, None


def accept_invite(token: str, user_id: str, name: str) -> dict:
    """Aceita convite e adiciona usuario a equipe."""
    tenant_id, invite = get_invite_by_token(token)
    if not tenant_id or not invite:
        return {"error": "Convite invalido ou expirado"}

    # Adiciona a equipe
    team = _load_team(tenant_id)
    team.append({
        "user_id": user_id,
        "email": invite["email"],
        "name": name,
        "role": invite["role"],
        "joined_at": time.time(),
    })
    _save_team(tenant_id, team)

    # Marca convite como aceito
    invites = _load_invites(tenant_id)
    for inv in invites:
        if inv.get("token") == token:
            inv["status"] = "accepted"
            break
    _save_invites(tenant_id, invites)

    log_action("invite_accepted", f"tenant={tenant_id} user={user_id}")
    return {"success": True, "tenant_id": tenant_id, "role": invite["role"]}


def update_role(tenant_id: str, user_id: str, new_role: str) -> dict:
    """Altera role de um usuario."""
    if new_role not in ROLES:
        return {"error": "Role invalida"}
    team = _load_team(tenant_id)
    for m in team:
        if m.get("user_id") == user_id:
            if m.get("role") == "owner":
                return {"error": "Nao pode alterar role do proprietario"}
            m["role"] = new_role
            _save_team(tenant_id, team)
            return {"success": True}
    return {"error": "Usuario nao encontrado"}


def remove_user(tenant_id: str, user_id: str) -> dict:
    """Remove usuario da equipe."""
    team = _load_team(tenant_id)
    member = next((m for m in team if m.get("user_id") == user_id), None)
    if not member:
        return {"error": "Usuario nao encontrado"}
    if member.get("role") == "owner":
        return {"error": "Nao pode remover o proprietario"}
    team = [m for m in team if m.get("user_id") != user_id]
    _save_team(tenant_id, team)
    log_action("user_removed", f"tenant={tenant_id} user={user_id}")
    return {"success": True}
