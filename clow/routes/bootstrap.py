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

    @app.get("/api/v1/system/context", tags=["system"])
    async def analyze_context_endpoint(request: _Req):
        """Analyze current context breakdown (admin only)."""
        sess = _get_user_session(request)
        if not sess or not sess.get("is_admin"):
            return _JR({"error": "Acesso negado"}, status_code=403)
        from ..context_assembly import analyze_context
        return _JR(analyze_context([], sess.get("cwd", "")))

    # ── Swarm API ──

    @app.get("/api/v1/system/swarm", tags=["system"])
    async def get_swarm_status_endpoint(request: _Req):
        sess = _get_user_session(request)
        if not sess or not sess.get("is_admin"):
            return _JR({"error": "Acesso negado"}, status_code=403)
        from ..swarm import get_swarm_status
        return _JR(get_swarm_status())

    @app.post("/api/v1/system/swarm/teams", tags=["system"])
    async def create_swarm_team(request: _Req):
        sess = _get_user_session(request)
        if not sess or not sess.get("is_admin"):
            return _JR({"error": "Acesso negado"}, status_code=403)
        body = await request.json()
        from ..swarm import create_team
        team = create_team(body.get("name", "team"), body.get("description", ""))
        return _JR({"name": team.name, "lead": team.lead_agent_id})

    @app.post("/api/v1/system/swarm/teams/{team_name}/spawn", tags=["system"])
    async def spawn_swarm_teammate(team_name: str, request: _Req):
        sess = _get_user_session(request)
        if not sess or not sess.get("is_admin"):
            return _JR({"error": "Acesso negado"}, status_code=403)
        body = await request.json()
        from ..swarm import spawn_teammate
        try:
            agent_id = spawn_teammate(
                team_name, body.get("name", "worker"),
                body.get("prompt", ""), body.get("agent_type", "general-purpose"),
            )
            return _JR({"agent_id": agent_id})
        except ValueError as e:
            return _JR({"error": str(e)}, status_code=404)

    @app.delete("/api/v1/system/swarm/teams/{team_name}", tags=["system"])
    async def delete_swarm_team(team_name: str, request: _Req):
        sess = _get_user_session(request)
        if not sess or not sess.get("is_admin"):
            return _JR({"error": "Acesso negado"}, status_code=403)
        from ..swarm import delete_team
        return _JR({"deleted": delete_team(team_name)})
