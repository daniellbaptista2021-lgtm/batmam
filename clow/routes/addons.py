"""Addons Routes — gating de produtos premium opcionais (System Clow, etc)."""

from __future__ import annotations

from fastapi import Request as _Req
from fastapi.responses import JSONResponse as _JR


SYSTEM_CLOW_URL = "https://system-clow.pvcorretor01.com.br/"


def register_addon_routes(app) -> None:
    from .auth import _get_user_session

    @app.get("/api/v1/addons/system-clow/status", tags=["addons"])
    async def system_clow_status(request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..database import get_db
        with get_db() as db:
            row = db.execute(
                "SELECT has_system_clow FROM users WHERE id=?",
                (sess["user_id"],),
            ).fetchone()
        active = bool(row[0]) if row and row[0] is not None else False
        return _JR({
            "active": active,
            "url": SYSTEM_CLOW_URL if active else None,
            "message": None if active else "Nao autorizado — contrate o System Clow",
        })
