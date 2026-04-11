"""Bridge API Routes — Remote Control Protocol."""

from __future__ import annotations
import json
import time

from fastapi import Request as _Req
from fastapi.responses import JSONResponse as _JR, StreamingResponse


def register_bridge_routes(app) -> None:
    from .auth import _get_user_session

    @app.post("/api/v1/bridge/sessions", tags=["bridge"])
    async def create_bridge_session(request: _Req):
        """Create a new bridge session."""
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..bridge import create_session
        try:
            bridge_sess = create_session(sess["user_id"])
            return _JR({
                "session_id": bridge_sess.id,
                "environment_id": bridge_sess.environment_id,
                "worker_url": f"/api/v1/bridge/{bridge_sess.id}/poll",
            })
        except RuntimeError as e:
            return _JR({"error": str(e)}, status_code=429)

    @app.get("/api/v1/bridge/sessions", tags=["bridge"])
    async def list_bridge_sessions(request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..bridge import list_sessions
        return _JR({"sessions": list_sessions(sess["user_id"])})

    @app.delete("/api/v1/bridge/{session_id}", tags=["bridge"])
    async def close_bridge_session(session_id: str, request: _Req):
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..bridge import close_session
        return _JR({"closed": close_session(session_id)})

    @app.post("/api/v1/bridge/{session_id}/send", tags=["bridge"])
    async def send_to_bridge(session_id: str, request: _Req):
        """Web UI sends message to remote CLI."""
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        from ..bridge import send_to_worker
        try:
            msg_id = send_to_worker(
                session_id,
                body.get("type", "user_input"),
                body.get("content", ""),
                body.get("data", {}),
            )
            return _JR({"message_id": msg_id})
        except ValueError as e:
            return _JR({"error": str(e)}, status_code=404)

    @app.get("/api/v1/bridge/{session_id}/poll", tags=["bridge"])
    async def poll_bridge(session_id: str, request: _Req):
        """CLI worker polls for pending work (long-poll)."""
        from ..bridge import poll_for_work
        timeout = float(request.query_params.get("timeout", "10"))
        import asyncio
        messages = await asyncio.get_event_loop().run_in_executor(
            None, poll_for_work, session_id, min(timeout, 30)
        )
        return _JR({"messages": messages})

    @app.post("/api/v1/bridge/{session_id}/respond", tags=["bridge"])
    async def bridge_respond(session_id: str, request: _Req):
        """CLI worker sends response back to web UI."""
        body = await request.json()
        from ..bridge import send_to_web
        try:
            msg_id = send_to_web(
                session_id,
                body.get("type", "assistant_response"),
                body.get("content", ""),
                body.get("data", {}),
            )
            return _JR({"message_id": msg_id})
        except ValueError as e:
            return _JR({"error": str(e)}, status_code=404)

    @app.get("/api/v1/bridge/{session_id}/events", tags=["bridge"])
    async def bridge_events(session_id: str, request: _Req):
        """SSE stream of events for web UI."""
        from ..bridge import get_events, get_session
        after = float(request.query_params.get("after", "0"))

        async def event_stream():
            nonlocal after
            while True:
                session = get_session(session_id)
                if not session or not session.is_alive():
                    yield f"data: {json.dumps({'type': 'session_closed'})}\n\n"
                    break
                events = get_events(session_id, after)
                for event in events:
                    yield f"data: {json.dumps(event)}\n\n"
                    after = max(after, event.get("timestamp", 0))
                import asyncio
                await asyncio.sleep(1)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.put("/api/v1/bridge/{session_id}/heartbeat", tags=["bridge"])
    async def bridge_heartbeat(session_id: str):
        """Worker heartbeat."""
        from ..bridge import heartbeat
        return _JR(heartbeat(session_id))

    @app.post("/api/v1/bridge/{session_id}/control", tags=["bridge"])
    async def bridge_control(session_id: str, request: _Req):
        """Server-initiated control (model change, permission mode, interrupt)."""
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        from ..bridge import send_to_worker
        try:
            msg_id = send_to_worker(session_id, "control", "", body)
            return _JR({"message_id": msg_id})
        except ValueError as e:
            return _JR({"error": str(e)}, status_code=404)
