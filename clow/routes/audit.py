"""Audit Routes — log de atividades + super admin."""

from __future__ import annotations

from fastapi import Request as _Req
from fastapi.responses import JSONResponse as _JR


def register_audit_routes(app) -> None:

    from .auth import _get_user_session

    def _auth(request: _Req):
        return _get_user_session(request)

    def _tenant(sess: dict) -> str:
        return sess["user_id"]

    @app.get("/api/v1/audit/logs", tags=["audit"])
    async def audit_logs(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..audit import get_logs, get_log_count
        tid = _tenant(sess)
        category = request.query_params.get("category", "")
        level = request.query_params.get("level", "")
        search = request.query_params.get("search", "")
        limit = int(request.query_params.get("limit", "100"))
        offset = int(request.query_params.get("offset", "0"))
        logs = get_logs(tid, limit=limit, offset=offset, category=category,
                        level=level, search=search)
        total = get_log_count(tid, category=category, level=level)
        return _JR({"logs": logs, "total": total})

    @app.get("/api/v1/audit/summary", tags=["audit"])
    async def audit_summary(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..audit import get_summary
        return _JR(get_summary(_tenant(sess)))

    @app.get("/api/v1/audit/errors", tags=["audit"])
    async def audit_errors(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..audit import get_recent_errors
        return _JR({"errors": get_recent_errors(_tenant(sess))})

    # ── Super Admin ──

    @app.get("/api/v1/super/tenants", tags=["super-admin"])
    async def super_tenants(request: _Req):
        key = request.headers.get("X-Super-Admin-Key", "")
        from ..audit import SUPER_ADMIN_KEY
        if key != SUPER_ADMIN_KEY:
            return _JR({"error": "Acesso negado"}, status_code=403)
        from ..audit import get_all_tenants_summary
        return _JR({"tenants": get_all_tenants_summary()})

    @app.get("/api/v1/super/audit/errors", tags=["super-admin"])
    async def super_errors(request: _Req):
        key = request.headers.get("X-Super-Admin-Key", "")
        from ..audit import SUPER_ADMIN_KEY
        if key != SUPER_ADMIN_KEY:
            return _JR({"error": "Acesso negado"}, status_code=403)
        from ..audit import get_all_errors
        limit = int(request.query_params.get("limit", "50"))
        return _JR({"errors": get_all_errors(limit)})
