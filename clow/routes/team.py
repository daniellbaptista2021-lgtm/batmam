"""Team Routes — convites, membros, roles."""

from __future__ import annotations
from pathlib import Path

from fastapi import Request as _Req
from fastapi.responses import JSONResponse as _JR, HTMLResponse as _HR

_TPL_DIR = Path(__file__).resolve().parent.parent / "templates"


def register_team_routes(app) -> None:

    from .auth import _get_user_session

    def _auth(request: _Req):
        return _get_user_session(request)

    def _tenant(sess: dict) -> str:
        return sess["user_id"]

    @app.get("/api/v1/team/members", tags=["team"])
    async def team_members(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..users import list_members, _load_invites
        tid = _tenant(sess)
        members = list_members(tid)
        invites = [i for i in _load_invites(tid) if i.get("status") == "pending"]
        return _JR({"members": members, "pending_invites": invites})

    @app.post("/api/v1/team/invite", tags=["team"])
    async def team_invite(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        from ..users import invite_user
        result = invite_user(_tenant(sess), body.get("email", ""),
                             body.get("role", "agent"), _tenant(sess))
        if "error" in result:
            return _JR(result, status_code=400)
        return _JR(result)

    @app.put("/api/v1/team/members/{user_id}/role", tags=["team"])
    async def team_update_role(user_id: str, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        from ..users import update_role
        result = update_role(_tenant(sess), user_id, body.get("role", ""))
        if "error" in result:
            return _JR(result, status_code=400)
        return _JR(result)

    @app.delete("/api/v1/team/members/{user_id}", tags=["team"])
    async def team_remove(user_id: str, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..users import remove_user
        result = remove_user(_tenant(sess), user_id)
        if "error" in result:
            return _JR(result, status_code=400)
        return _JR(result)

    @app.get("/api/v1/user/permissions", tags=["team"])
    async def user_permissions(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..users import get_permissions, get_user_role
        tid = _tenant(sess)
        return _JR({
            "role": get_user_role(tid, tid),
            "permissions": get_permissions(tid, tid),
        })

    @app.get("/invite/{token}", tags=["team"])
    async def invite_page(token: str):
        from ..users import get_invite_by_token
        tenant_id, invite = get_invite_by_token(token)
        if not tenant_id or not invite:
            return _HR("<h1 style='text-align:center;margin-top:80px;font-family:sans-serif'>Convite invalido ou expirado.</h1>")
        tpl = _TPL_DIR / "invite.html"
        if tpl.exists():
            html = tpl.read_text(encoding="utf-8")
            html = html.replace("{{TOKEN}}", token)
            html = html.replace("{{EMAIL}}", invite.get("email", ""))
            html = html.replace("{{ROLE}}", invite.get("role", "agent"))
            return _HR(html)
        return _HR(f"<h1>Convite para {invite.get('email','')} como {invite.get('role','')}</h1>")
