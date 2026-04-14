"""WebSocket endpoint for real-time chat."""

from __future__ import annotations
import asyncio
import os
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .auth import (
    _get_api_keys, _verify_api_key, _validate_session,
    _ws_rate_limiter,
)
from .chat import _build_multimodal_message, _greeting_reply, _is_plain_greeting
from ..webapp import track_action
from ..rate_limit import limiter as user_limiter
from ..rag import get_context_for_prompt as _rag_context
from ..database import check_message_limit


def register_ws_routes(app: FastAPI) -> None:
    """Register the WebSocket endpoint."""

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        ws_cookie = websocket.cookies.get("clow_session", "")
        ws_sess = _validate_session(ws_cookie)
        if not ws_sess:
            api_key = websocket.query_params.get("api_key", "")
            keys = _get_api_keys()
            if keys and not _verify_api_key(api_key):
                await websocket.close(code=4001, reason="Nao autenticado")
                return
            elif not keys and not ws_cookie:
                await websocket.close(code=4001, reason="Nao autenticado")
                return

        ws_is_admin = ws_sess.get("is_admin", False) if ws_sess else False
        ws_user_id = ws_sess.get("user_id", "") if ws_sess else ""

        client_ip = websocket.client.host if websocket.client else "unknown"
        if not _ws_rate_limiter.is_allowed(client_ip):
            await websocket.close(code=4029, reason="Rate limit excedido")
            return

        await websocket.accept()

        from ..agent import Agent

        loop = asyncio.get_event_loop()
        agents_by_conv: dict[str, Any] = {}
        draft_agent: Any = None
        send_queue: asyncio.Queue = asyncio.Queue()

        def on_text_delta(delta: str):
            asyncio.run_coroutine_threadsafe(
                send_queue.put({"type": "text_delta", "content": delta}),
                loop,
            )

        def on_text_done(text: str):
            asyncio.run_coroutine_threadsafe(
                send_queue.put({"type": "text_done"}),
                loop,
            )

        def on_tool_call(name: str, args: dict):
            track_action("tool_call", f"{name}", "running")
            asyncio.run_coroutine_threadsafe(
                send_queue.put({"type": "tool_call", "name": name, "args": args}),
                loop,
            )

        def on_tool_result(name: str, status: str, output: str):
            track_action("tool_result", f"{name}: {status}", status)
            asyncio.run_coroutine_threadsafe(
                send_queue.put({"type": "tool_result", "name": name, "status": status, "output": output[:2000]}),
                loop,
            )

        def build_agent() -> Any:
            if ws_is_admin:
                return Agent(
                    cwd=os.getcwd(),
                    on_text_delta=on_text_delta,
                    on_text_done=on_text_done,
                    on_tool_call=on_tool_call,
                    on_tool_result=on_tool_result,
                    auto_approve=True,
                )
            return Agent(
                cwd=os.getcwd(),
                on_text_delta=on_text_delta,
                on_text_done=on_text_done,
                on_tool_call=on_tool_call,
                on_tool_result=on_tool_result,
                auto_approve=False,
                ask_confirmation=lambda _: False,
            )

        async def send_loop():
            try:
                while True:
                    msg = await send_queue.get()
                    await websocket.send_json(msg)
            except Exception:
                pass

        sender_task = asyncio.create_task(send_loop())

        try:
            while True:
                data = await websocket.receive_json()
                if data.get("type") != "message":
                    continue

                content = data.get("content", "")
                file_data = data.get("file_data")
                conv_id = str(data.get("conversation_id", "") or "").strip()

                if not content and not file_data:
                    continue

                ws_plan = ws_sess.get("plan", "lite") if ws_sess else "lite"
                rl_ok, _ = user_limiter.check(client_ip, ws_user_id, "admin" if ws_is_admin else ws_plan)
                if not rl_ok:
                    await websocket.send_json({"type": "error", "content": "Rate limit atingido. Aguarde alguns minutos."})
                    await websocket.send_json({"type": "turn_complete"})
                    continue

                if ws_user_id and not ws_is_admin:
                    msg_allowed, msg_reason = check_message_limit(ws_user_id)
                    if not msg_allowed:
                        await websocket.send_json({"type": "error", "content": msg_reason})
                        await websocket.send_json({"type": "turn_complete"})
                        continue

                track_action("user_message", content[:60])

                if not file_data and _is_plain_greeting(content):
                    short_reply = _greeting_reply(content)
                    await websocket.send_json({"type": "text_delta", "content": short_reply})
                    await websocket.send_json({"type": "text_done"})
                    await websocket.send_json({"type": "turn_complete"})
                    continue

                await websocket.send_json({"type": "thinking_start"})

                if file_data:
                    user_msg = _build_multimodal_message(content, file_data)
                else:
                    rag_ctx = ""
                    try:
                        rag_ctx = _rag_context(content, root=os.getcwd(), max_chars=8000)
                    except Exception:
                        pass
                    user_msg = f"{rag_ctx}\n\n---\n\n{content}" if rag_ctx else content

                try:
                    if conv_id:
                        agent = agents_by_conv.get(conv_id)
                        if agent is None:
                            agent = build_agent()
                            agents_by_conv[conv_id] = agent
                    else:
                        agent = draft_agent
                        if agent is None:
                            agent = build_agent()
                            draft_agent = agent

                    result = await loop.run_in_executor(None, agent.run_turn, user_msg)
                    track_action("agent_response", result[:60] if result else "")
                except Exception as e:
                    await websocket.send_json({"type": "thinking_end"})
                    await websocket.send_json({"type": "error", "content": str(e)})
                    track_action("agent_error", str(e)[:60], "error")

                await websocket.send_json({"type": "turn_complete"})

        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            sender_task.cancel()
