"""Admin API routes: stats, users, create-user, missions."""

from __future__ import annotations
import asyncio
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .auth import _get_user_session
from ..database import (
    get_admin_stats, list_users, update_user, create_user,
    save_message,
)


# Mission progress tracking (shared state)
_mission_progress: dict[str, list] = {}  # mission_id -> [events]


def register_admin_routes(app: FastAPI) -> None:
    """Register admin and missions routes."""

    # ── API: Admin ───────────────────────────────────────────────────

    @app.get("/api/v1/admin/stats")
    async def api_admin_stats(request: Request):
        sess = _get_user_session(request)
        if not sess or not sess.get("is_admin"):
            return JSONResponse({"error": "Acesso negado"}, status_code=403)
        return JSONResponse(get_admin_stats())

    @app.get("/api/v1/admin/users")
    async def api_admin_users(request: Request):
        sess = _get_user_session(request)
        if not sess or not sess.get("is_admin"):
            return JSONResponse({"error": "Acesso negado"}, status_code=403)
        return JSONResponse({"users": list_users()})

    @app.post("/api/v1/admin/users/{user_id}")
    async def api_admin_update_user(user_id: str, request: Request):
        sess = _get_user_session(request)
        if not sess or not sess.get("is_admin"):
            return JSONResponse({"error": "Acesso negado"}, status_code=403)
        body = await request.json()
        update_user(user_id, **body)
        return JSONResponse({"ok": True})

    @app.post("/api/v1/admin/create-user")
    async def api_admin_create_user(request: Request):
        sess = _get_user_session(request)
        if not sess or not sess.get("is_admin"):
            return JSONResponse({"error": "Acesso negado"}, status_code=403)
        body = await request.json()
        email = body.get("email", "").strip().lower()
        password = body.get("password", "")
        name = body.get("name", "")
        plan = body.get("plan", "free")
        if not email or len(password) < 6:
            return JSONResponse({"error": "Email e senha (min 6 chars) obrigatorios"}, status_code=400)
        user = create_user(email, password, name)
        if not user:
            return JSONResponse({"error": "Email ja cadastrado"}, status_code=400)
        if plan != "free":
            update_user(user["id"], plan=plan)
        return JSONResponse({"ok": True, "user": user})


    @app.delete("/api/v1/admin/users/{user_id}")
    async def api_admin_delete_user(user_id: str, request: Request):
        sess = _get_user_session(request)
        if not sess or not sess.get("is_admin"):
            return JSONResponse({"error": "Acesso negado"}, status_code=403)
        # Defesa: nunca permite admin deletar a si mesmo nem o user_id=1
        if user_id == sess.get("user_id"):
            return JSONResponse({"error": "Voce nao pode apagar sua propria conta admin"}, status_code=400)
        from ..database import delete_user_cascade
        try:
            result = delete_user_cascade(user_id)
        except Exception as _e:
            logger.exception("api_admin_delete_user exception: %s", _e)
            return JSONResponse({"error": str(_e)}, status_code=500)
        if not result.get("ok"):
            return JSONResponse(result, status_code=400)
        return JSONResponse(result)

    # ── API: Missions ────────────────────────────────────────────────

    @app.post("/api/v1/missions/plan")
    async def api_mission_plan(request: Request):
        sess = _get_user_session(request)
        if not sess:
            return JSONResponse({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        description = body.get("description", "").strip()
        if not description:
            return JSONResponse({"error": "Descricao vazia"}, status_code=400)

        from ..agents.mission_engine import plan_mission
        loop = asyncio.get_event_loop()
        try:
            plan = await loop.run_in_executor(None, plan_mission, description)
            return JSONResponse({"plan": plan})
        except Exception as e:
            return JSONResponse({"error": str(e)[:300]}, status_code=500)

    @app.post("/api/v1/missions/start")
    async def api_mission_start(request: Request):
        sess = _get_user_session(request)
        if not sess:
            return JSONResponse({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        description = body.get("description", "")
        plan_data = body.get("plan", {})
        title = plan_data.get("title", description[:60])
        steps = plan_data.get("steps", [])

        if not steps:
            return JSONResponse({"error": "Plano sem etapas"}, status_code=400)

        from ..database import create_mission
        mission_id = create_mission(sess["user_id"], title, description, steps)
        _mission_progress[mission_id] = []

        async def on_progress(mid, event_type, data):
            _mission_progress.setdefault(mid, []).append({
                "type": event_type, "data": data, "time": time.time()
            })

        from ..agents.mission_engine import execute_mission
        asyncio.create_task(execute_mission(mission_id, sess["user_id"], on_progress))

        return JSONResponse({"mission_id": mission_id, "title": title, "total_steps": len(steps)})

    @app.get("/api/v1/missions/{mission_id}/progress")
    async def api_mission_progress(mission_id: str, request: Request):
        sess = _get_user_session(request)
        if not sess:
            return JSONResponse({"error": "Nao autenticado"}, status_code=401)

        after = float(request.query_params.get("after", "0"))
        events = _mission_progress.get(mission_id, [])
        new_events = [e for e in events if e["time"] > after]

        from ..database import get_mission
        mission = get_mission(mission_id)
        status = mission["status"] if mission else "unknown"

        return JSONResponse({"status": status, "events": new_events})

    @app.get("/api/v1/missions")
    async def api_list_missions(request: Request):
        sess = _get_user_session(request)
        if not sess:
            return JSONResponse({"error": "Nao autenticado"}, status_code=401)
        from ..database import list_missions
        return JSONResponse({"missions": list_missions(sess["user_id"])})

    @app.get("/api/v1/missions/{mission_id}")
    async def api_get_mission(mission_id: str, request: Request):
        sess = _get_user_session(request)
        if not sess:
            return JSONResponse({"error": "Nao autenticado"}, status_code=401)
        from ..database import get_mission
        m = get_mission(mission_id)
        if not m:
            return JSONResponse({"error": "Missao nao encontrada"}, status_code=404)
        return JSONResponse({"mission": m})
