"""Bootstrap inspection routes."""
from __future__ import annotations
from fastapi import Request as _Req
from fastapi.responses import JSONResponse as _JR


def register_bootstrap_routes(app) -> None:
    from .auth import _get_user_session

    @app.get("/api/v1/system/state", tags=["system"])
    async def get_system_state(request: _Req):
        """Inspect bootstrap state (admin only)."""
        sess = _get_user_session(request)
        if not sess or not sess.get("is_admin"):
            return _JR({"error": "Acesso negado"}, status_code=403)
        from ..bootstrap import get_state, get_startup_report
        return _JR({
            "state": get_state().to_dict(),
            "startup": get_startup_report(),
        })

    @app.get("/api/v1/system/startup-profile", tags=["system"])
    async def get_startup_profile(request: _Req):
        """Get startup performance profile (admin only)."""
        sess = _get_user_session(request)
        if not sess or not sess.get("is_admin"):
            return _JR({"error": "Acesso negado"}, status_code=403)
        from ..bootstrap import get_startup_report
        return _JR(get_startup_report())
