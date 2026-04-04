"""WebSocket endpoint for real-time chat."""

from __future__ import annotations
import asyncio
import os
import logging
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .auth import (
    _get_api_keys, _verify_api_key, _validate_session,
    _ws_rate_limiter,
)
from .chat import _build_multimodal_message, _should_generate_image, _process_image_request
from ..webapp import track_action
from ..rate_limit import limiter as user_limiter
from ..rag import get_context_for_prompt as _rag_context


def register_ws_routes(app: FastAPI) -> None:
    """Register the WebSocket endpoint."""

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        # Verificacao de sessao via cookie para WebSocket
        ws_cookie = websocket.cookies.get("clow_session", "")
        ws_sess = _validate_session(ws_cookie)
        if not ws_sess:
            # Fallback: API key via query param
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

        # Rate limit para WebSocket
        client_ip = websocket.client.host if websocket.client else "unknown"
        if not _ws_rate_limiter.is_allowed(client_ip):
            await websocket.close(code=4029, reason="Rate limit excedido")
            return

        await websocket.accept()

        from ..agent import Agent

        loop = asyncio.get_event_loop()

        # Cria agente com callbacks que enviam via WebSocket
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

        agent = Agent(
            cwd=os.getcwd(),
            on_text_delta=on_text_delta,
            on_text_done=on_text_done,
            on_tool_call=on_tool_call,
            on_tool_result=on_tool_result,
            auto_approve=True,
        )

        # Task para enviar mensagens da fila para o WebSocket
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
                if data.get("type") == "message":
                    content = data.get("content", "")
                    file_data = data.get("file_data")
                    ws_model = data.get("model", "haiku")

                    if not content and not file_data:
                        continue

                    # Rate limit per user
                    ws_plan = ws_sess.get("plan", "free") if ws_sess else "free"
                    rl_ok, _ = user_limiter.check(client_ip, ws_user_id, "admin" if ws_is_admin else ws_plan)
                    if not rl_ok:
                        await websocket.send_json({"type": "error", "content": "Rate limit atingido. Aguarde alguns minutos."})
                        await websocket.send_json({"type": "turn_complete"})
                        continue

                    track_action("user_message", content[:60])

                    # Envia thinking
                    await websocket.send_json({"type": "thinking_start"})

                    # ── Detecta e processa pedido de imagem ──
                    if _should_generate_image(content) and not file_data:
                        await websocket.send_json({"type": "thinking_end"})

                        # Gera imagem
                        try:
                            filepath, filename, response_html = await _process_image_request(content, agent)
                            await websocket.send_json({"type": "text_delta", "content": response_html})
                            await websocket.send_json({"type": "text_done"})
                            track_action("image_generated", filename or "failed")
                        except Exception as e:
                            await websocket.send_json({"type": "error", "content": f"Erro ao gerar imagem: {str(e)}"})
                            track_action("image_error", str(e)[:60], "error")

                        # Finaliza turno
                        await websocket.send_json({"type": "turn_complete"})
                        continue

                    # Monta mensagem multimodal se tem arquivo
                    if file_data:
                        user_msg = _build_multimodal_message(content, file_data)
                    else:
                        # Enrich with RAG context
                        rag_ctx = ""
                        try:
                            rag_ctx = _rag_context(content, root=os.getcwd(), max_chars=8000)
                        except Exception:
                            pass
                        user_msg = f"{rag_ctx}\n\n---\n\n{content}" if rag_ctx else content

                    # Executa agente em thread separada (chat normal)
                    try:
                        result = await loop.run_in_executor(
                            None, agent.run_turn, user_msg
                        )
                        track_action("agent_response", result[:60] if result else "")
                    except Exception as e:
                        await websocket.send_json({"type": "thinking_end"})
                        await websocket.send_json({"type": "error", "content": str(e)})
                        track_action("agent_error", str(e)[:60], "error")

                    # Finaliza turno
                    await websocket.send_json({"type": "turn_complete"})

        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            sender_task.cancel()
