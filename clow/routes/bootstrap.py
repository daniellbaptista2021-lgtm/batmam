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

    # ── Permissions API (Ep.07) ──

    @app.get('/api/v1/system/permissions', tags=['system'])
    async def get_permissions_state(request: _Req):
        sess = _get_user_session(request)
        if not sess or not sess.get('is_admin'):
            return _JR({'error': 'Acesso negado'}, status_code=403)
        from ..permissions import get_permission_mode, get_denial_stats, PERMISSION_MODES
        return _JR({
            'mode': get_permission_mode(),
            'modes_available': list(PERMISSION_MODES.keys()),
            'denial_stats': get_denial_stats(),
        })

    @app.post('/api/v1/system/permissions/mode', tags=['system'])
    async def set_permissions_mode(request: _Req):
        sess = _get_user_session(request)
        if not sess or not sess.get('is_admin'):
            return _JR({'error': 'Acesso negado'}, status_code=403)
        body = await request.json()
        from ..permissions import set_permission_mode, PERMISSION_MODES
        mode = body.get('mode', '')
        if mode not in PERMISSION_MODES:
            return _JR({'error': f'Mode invalido. Use: {list(PERMISSION_MODES.keys())}'}, status_code=400)
        return _JR(set_permission_mode(mode))

    # ── Plugins API (Ep.04) ──

    @app.get("/api/v1/system/plugins", tags=["system"])
    async def get_plugins(request: _Req):
        """Get plugin system stats and loaded plugins (admin only)."""
        sess = _get_user_session(request)
        if not sess or not sess.get("is_admin"):
            return _JR({"error": "Acesso negado"}, status_code=403)
        import os as _os
        from ..plugins import PluginManager
        mgr = PluginManager()
        mgr.discover(_os.getcwd())
        return _JR({"stats": mgr.get_stats(), "plugins": mgr.list_plugins()})

    @app.get("/api/v1/system/plugins/list", tags=["system"])
    async def list_plugins(request: _Req):
        """List all discovered plugins with details (admin only)."""
        sess = _get_user_session(request)
        if not sess or not sess.get("is_admin"):
            return _JR({"error": "Acesso negado"}, status_code=403)
        import os as _os
        from ..plugins import PluginManager
        mgr = PluginManager()
        mgr.load_all(cwd=_os.getcwd())
        return _JR({"plugins": mgr.list_plugins()})

    # -- Coordinator API (Ep.03) --

    @app.get("/api/v1/system/coordinator", tags=["system"])
    async def get_coordinator_status(request: _Req):
        """Get coordinator status (admin only)."""
        sess = _get_user_session(request)
        if not sess or not sess.get("is_admin"):
            return _JR({"error": "Acesso negado"}, status_code=403)
        from ..coordinator import get_coordinator, is_coordinator_mode
        if not is_coordinator_mode():
            return _JR({"mode": "normal", "message": "Coordinator mode not active"})
        return _JR(get_coordinator().get_status())

    @app.post("/api/v1/system/coordinator/mode", tags=["system"])
    async def toggle_coordinator_mode(request: _Req):
        """Toggle coordinator mode on/off (admin only)."""
        sess = _get_user_session(request)
        if not sess or not sess.get("is_admin"):
            return _JR({"error": "Acesso negado"}, status_code=403)
        body = await request.json()
        from ..coordinator import set_coordinator_mode, is_coordinator_mode
        set_coordinator_mode(body.get("enabled", False))
        return _JR({"coordinator_mode": is_coordinator_mode()})

    @app.get("/api/v1/system/coordinator/workers", tags=["system"])
    async def list_coordinator_workers(request: _Req):
        """List all coordinator workers (admin only)."""
        sess = _get_user_session(request)
        if not sess or not sess.get("is_admin"):
            return _JR({"error": "Acesso negado"}, status_code=403)
        from ..coordinator import get_coordinator
        return _JR({"workers": get_coordinator().list_workers()})
