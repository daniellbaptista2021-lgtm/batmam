"""Server-Sent Events streaming for HTTP chat endpoint."""
import asyncio
import json
import logging
from typing import AsyncGenerator

logger = logging.getLogger(__name__)


async def sse_stream(agent, user_message: str) -> AsyncGenerator[str, None]:
    """Stream agent response as SSE events.

    Yields: 'data: {"type": "...", "content": "..."}\n\n'
    """
    chunks = []
    tools = []
    done = asyncio.Event()
    error_msg = ""

    def on_delta(d):
        chunks.append(d)

    def on_done(t):
        done.set()

    def on_tool_call(n, a):
        tools.append({"type": "tool_call", "name": n, "args": a})

    def on_tool_result(n, s, o):
        tools.append({"type": "tool_result", "name": n, "status": s, "output": o[:500]})

    agent.on_text_delta = on_delta
    agent.on_text_done = on_done
    agent.on_tool_call = on_tool_call
    agent.on_tool_result = on_tool_result

    loop = asyncio.get_event_loop()

    async def _run():
        nonlocal error_msg
        try:
            await loop.run_in_executor(None, agent.run_turn, user_message)
        except Exception as e:
            error_msg = str(e)
        finally:
            done.set()

    asyncio.create_task(_run())

    yield f"data: {json.dumps({'type': 'thinking_start'})}\n\n"

    idx = 0
    while not done.is_set() or idx < len(chunks) or tools:
        while idx < len(chunks):
            yield f"data: {json.dumps({'type': 'text_delta', 'content': chunks[idx]})}\n\n"
            idx += 1
        while tools:
            yield f"data: {json.dumps(tools.pop(0))}\n\n"
        if not done.is_set():
            await asyncio.sleep(0.05)

    # Flush
    while idx < len(chunks):
        yield f"data: {json.dumps({'type': 'text_delta', 'content': chunks[idx]})}\n\n"
        idx += 1

    if error_msg:
        yield f"data: {json.dumps({'type': 'error', 'content': error_msg})}\n\n"

    yield f"data: {json.dumps({'type': 'text_done'})}\n\n"
    yield f"data: {json.dumps({'type': 'turn_complete'})}\n\n"
    yield "data: [DONE]\n\n"
