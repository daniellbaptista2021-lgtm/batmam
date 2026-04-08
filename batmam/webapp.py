"""Web App scaffold do Batmam — FastAPI + WebSocket.

Para rodar:
  pip install fastapi uvicorn
  batmam --web [--port 8080]

Ou diretamente:
  uvicorn batmam.webapp:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse
    from fastapi.staticfiles import StaticFiles
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from . import config


def create_app() -> "FastAPI":
    """Cria a aplicacao FastAPI."""
    if not HAS_FASTAPI:
        raise ImportError(
            "FastAPI nao instalado. Instale com: pip install fastapi uvicorn"
        )

    app = FastAPI(title="Batmam Web", version="0.1.0")

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return WEB_UI_HTML

    @app.get("/api/status")
    async def status():
        return {
            "status": "ok",
            "model": config.BATMAM_MODEL,
            "version": "0.1.0",
        }

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()

        from .agent import Agent

        # Callback assincronos para streaming
        loop = asyncio.get_event_loop()
        send_queue: asyncio.Queue = asyncio.Queue()

        def on_text_delta(delta: str):
            asyncio.run_coroutine_threadsafe(
                send_queue.put({"type": "text_delta", "content": delta}),
                loop,
            )

        def on_text_done(text: str):
            asyncio.run_coroutine_threadsafe(
                send_queue.put({"type": "text_done", "content": text}),
                loop,
            )

        def on_tool_call(name: str, args: dict):
            asyncio.run_coroutine_threadsafe(
                send_queue.put({"type": "tool_call", "name": name, "args": args}),
                loop,
            )

        def on_tool_result(name: str, status: str, output: str):
            asyncio.run_coroutine_threadsafe(
                send_queue.put({
                    "type": "tool_result",
                    "name": name,
                    "status": status,
                    "output": output[:2000],
                }),
                loop,
            )

        agent = Agent(
            cwd=os.getcwd(),
            model=config.BATMAM_MODEL,
            on_text_delta=on_text_delta,
            on_text_done=on_text_done,
            on_tool_call=on_tool_call,
            on_tool_result=on_tool_result,
            ask_confirmation=lambda m: True,  # Auto-approve no web
            auto_approve=True,
        )

        # Task para enviar mensagens da fila para o websocket
        async def send_loop():
            while True:
                msg = await send_queue.get()
                try:
                    await websocket.send_json(msg)
                except Exception:
                    break

        send_task = asyncio.create_task(send_loop())

        try:
            while True:
                data = await websocket.receive_text()
                try:
                    msg = json.loads(data)
                except json.JSONDecodeError:
                    msg = {"type": "message", "content": data}

                if msg.get("type") == "message":
                    content = msg.get("content", "")
                    if content:
                        # Roda agente em thread separada
                        result = await asyncio.to_thread(agent.run_turn, content)
                        await websocket.send_json({
                            "type": "turn_complete",
                            "content": result,
                        })

        except WebSocketDisconnect:
            pass
        finally:
            send_task.cancel()

    return app


# HTML embutido para o web UI
WEB_UI_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Batmam Web</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #1a1a2e;
            color: #e0e0e0;
            font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
            height: 100vh;
            display: flex;
            flex-direction: column;
        }
        #header {
            background: #16213e;
            padding: 12px 20px;
            border-bottom: 2px solid #FFD700;
            display: flex;
            align-items: center;
            gap: 12px;
        }
        #header h1 { color: #FFD700; font-size: 1.3em; }
        #header .model { color: #87CEEB; font-size: 0.85em; }
        #messages {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 16px;
        }
        .msg { padding: 12px 16px; border-radius: 8px; max-width: 85%; line-height: 1.5; }
        .msg.user {
            background: #2a2a4a;
            border-left: 3px solid #FFD700;
            align-self: flex-end;
            color: #FFD700;
        }
        .msg.assistant {
            background: #1e3a5f;
            border-left: 3px solid #87CEEB;
            align-self: flex-start;
            white-space: pre-wrap;
        }
        .msg.tool {
            background: #1a2a1a;
            border-left: 3px solid #4CAF50;
            font-size: 0.85em;
            color: #a0a0a0;
            align-self: flex-start;
        }
        .msg.streaming { opacity: 0.8; }
        #input-area {
            background: #16213e;
            padding: 16px 20px;
            border-top: 1px solid #333;
            display: flex;
            gap: 12px;
        }
        #input {
            flex: 1;
            background: #1a1a2e;
            border: 1px solid #444;
            color: #FFD700;
            padding: 12px 16px;
            border-radius: 8px;
            font-family: inherit;
            font-size: 1em;
            outline: none;
        }
        #input:focus { border-color: #FFD700; }
        #send {
            background: #FFD700;
            color: #1a1a2e;
            border: none;
            padding: 12px 24px;
            border-radius: 8px;
            font-weight: bold;
            cursor: pointer;
            font-family: inherit;
        }
        #send:hover { background: #FFC107; }
        #send:disabled { opacity: 0.5; cursor: not-allowed; }
    </style>
</head>
<body>
    <div id="header">
        <h1>Batmam Web</h1>
        <span class="model" id="model-info">Conectando...</span>
    </div>
    <div id="messages"></div>
    <div id="input-area">
        <input type="text" id="input" placeholder="Digite sua mensagem..." autocomplete="off" />
        <button id="send">Enviar</button>
    </div>

    <script>
        const messages = document.getElementById('messages');
        const input = document.getElementById('input');
        const sendBtn = document.getElementById('send');
        const modelInfo = document.getElementById('model-info');
        let ws = null;
        let currentAssistantMsg = null;

        function connect() {
            const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${proto}//${location.host}/ws`);

            ws.onopen = () => { modelInfo.textContent = 'Conectado'; };
            ws.onclose = () => {
                modelInfo.textContent = 'Desconectado — reconectando...';
                setTimeout(connect, 2000);
            };

            ws.onmessage = (e) => {
                const data = JSON.parse(e.data);
                switch(data.type) {
                    case 'text_delta':
                        if (!currentAssistantMsg) {
                            currentAssistantMsg = addMessage('', 'assistant streaming');
                        }
                        currentAssistantMsg.textContent += data.content;
                        messages.scrollTop = messages.scrollHeight;
                        break;
                    case 'text_done':
                        if (currentAssistantMsg) {
                            currentAssistantMsg.classList.remove('streaming');
                        }
                        currentAssistantMsg = null;
                        break;
                    case 'tool_call':
                        addMessage(`> ${data.name}  ${JSON.stringify(data.args).slice(0,100)}`, 'tool');
                        break;
                    case 'tool_result':
                        const icon = data.status === 'success' ? '✓' : '✗';
                        addMessage(`${icon} ${data.name}`, 'tool');
                        break;
                    case 'turn_complete':
                        sendBtn.disabled = false;
                        input.disabled = false;
                        input.focus();
                        break;
                }
            };
        }

        function addMessage(text, cls) {
            const div = document.createElement('div');
            div.className = `msg ${cls}`;
            div.textContent = text;
            messages.appendChild(div);
            messages.scrollTop = messages.scrollHeight;
            return div;
        }

        function send() {
            const text = input.value.trim();
            if (!text || !ws) return;
            addMessage(text, 'user');
            ws.send(JSON.stringify({ type: 'message', content: text }));
            input.value = '';
            sendBtn.disabled = true;
            input.disabled = true;
        }

        sendBtn.onclick = send;
        input.onkeydown = (e) => { if (e.key === 'Enter') send(); };

        // Fetch status
        fetch('/api/status').then(r => r.json()).then(d => {
            modelInfo.textContent = `Modelo: ${d.model}`;
        });

        connect();
    </script>
</body>
</html>
"""


# Shortcut para rodar
app = create_app() if HAS_FASTAPI else None


def run_web(host: str = "0.0.0.0", port: int = 8080) -> None:
    """Roda o servidor web."""
    try:
        import uvicorn
    except ImportError:
        print("Instale: pip install fastapi uvicorn")
        return

    application = create_app()
    print(f"\n  Batmam Web rodando em http://{host}:{port}\n")
    uvicorn.run(application, host=host, port=port, log_level="warning")
