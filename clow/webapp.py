"""Clow Web App — FastAPI + WebSocket com UI estilo Claude Code.

Features:
  #18 — Web App (FastAPI + WebSocket com UI completa)
  #19 — Health Check + Monitoring Endpoint
  #24 — Dashboard de Metricas
  #26 — Autenticacao via API Key / Bearer Token
  #27 — Rate Limiting por IP (configurable)
  #28 — CORS configuravel
  #29 — HTTPS/TLS support (via uvicorn ssl)
"""

from __future__ import annotations
import json
import asyncio
import os
import time
import hashlib
import secrets
from collections import defaultdict
from typing import Any

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException, Depends
    from fastapi.responses import HTMLResponse, JSONResponse
    from fastapi.middleware.cors import CORSMiddleware
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from . import __version__
from . import config

app = FastAPI(
    title="Clow",
    version=__version__,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
) if HAS_FASTAPI else None


# ── Autenticacao ─────────────────────────────────────────────────

def _get_api_keys() -> list[str]:
    """Carrega API keys do settings ou env."""
    settings = config.load_settings()
    keys = settings.get("webapp", {}).get("api_keys", [])
    env_key = os.getenv("CLOW_API_KEY", "")
    if env_key and env_key not in keys:
        keys.append(env_key)
    return keys


def _generate_api_key() -> str:
    """Gera uma nova API key segura."""
    return f"clow_{secrets.token_urlsafe(32)}"


def _verify_api_key(key: str) -> bool:
    """Verifica se uma API key e valida."""
    valid_keys = _get_api_keys()
    if not valid_keys:
        return True  # Sem keys configuradas = sem autenticacao (dev mode)
    return key in valid_keys


async def _auth_dependency(request: Request) -> None:
    """FastAPI dependency para verificar autenticacao."""
    keys = _get_api_keys()
    if not keys:
        return  # Dev mode — sem autenticacao

    # Tenta Authorization header
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if _verify_api_key(token):
            return

    # Tenta query param
    api_key = request.query_params.get("api_key", "")
    if api_key and _verify_api_key(api_key):
        return

    raise HTTPException(status_code=401, detail="API key invalida ou ausente")


# ── Rate Limiting ────────────────────────────────────────────────

class RateLimiter:
    """Rate limiter por IP com sliding window."""

    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, ip: str) -> bool:
        now = time.time()
        window_start = now - self.window

        # Limpa requests antigos
        self._requests[ip] = [t for t in self._requests[ip] if t > window_start]

        if len(self._requests[ip]) >= self.max_requests:
            return False

        self._requests[ip].append(now)
        return True

    def remaining(self, ip: str) -> int:
        now = time.time()
        window_start = now - self.window
        recent = [t for t in self._requests[ip] if t > window_start]
        return max(0, self.max_requests - len(recent))


_rate_limiter = RateLimiter(max_requests=60, window_seconds=60)
_ws_rate_limiter = RateLimiter(max_requests=10, window_seconds=60)


async def _rate_limit_dependency(request: Request) -> None:
    """FastAPI dependency para rate limiting."""
    client_ip = request.client.host if request.client else "unknown"
    if not _rate_limiter.is_allowed(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Rate limit excedido. Tente novamente em alguns segundos.",
            headers={"Retry-After": "60"},
        )


# ── Setup CORS e Middleware ──────────────────────────────────────

def _setup_middleware():
    """Configura CORS e middlewares de seguranca."""
    if not HAS_FASTAPI or app is None:
        return

    settings = config.load_settings()
    webapp_cfg = settings.get("webapp", {})

    # CORS
    allowed_origins = webapp_cfg.get("cors_origins", ["http://localhost:*", "http://127.0.0.1:*"])
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )


if HAS_FASTAPI:
    _setup_middleware()


def get_app():
    if not HAS_FASTAPI:
        raise RuntimeError("FastAPI nao instalado. Instale com: pip install 'clow[web]'")
    return app


def start_with_tls(host: str = "0.0.0.0", port: int = 8080, certfile: str = "", keyfile: str = ""):
    """Inicia o servidor com TLS/HTTPS se certificados forem fornecidos."""
    import uvicorn

    kwargs: dict[str, Any] = {
        "app": "clow.webapp:app",
        "host": host,
        "port": port,
        "log_level": "info",
    }
    if certfile and keyfile:
        kwargs["ssl_certfile"] = certfile
        kwargs["ssl_keyfile"] = keyfile

    uvicorn.run(**kwargs)


# ── Ações executadas (Feature #24 — tracking) ──────────────────
_recent_actions: list[dict] = []
MAX_RECENT_ACTIONS = 50


def track_action(action: str, details: str = "", status: str = "ok") -> None:
    """Registra ação recente para o dashboard."""
    _recent_actions.append({
        "action": action,
        "details": details[:100],
        "status": status,
        "timestamp": time.time(),
    })
    if len(_recent_actions) > MAX_RECENT_ACTIONS:
        _recent_actions.pop(0)


# ── Feature #19: Health Check ──────────────────────────────────

def _get_health_data() -> dict:
    """Coleta status de todos os componentes."""
    from .memory import list_memories
    from .cron import get_cron_manager
    from .triggers import get_trigger_server
    from .tasks import get_task_manager

    memories = list_memories()
    cron = get_cron_manager()
    trigger = get_trigger_server()
    tasks = get_task_manager()

    mem_by_type: dict[str, int] = {}
    for m in memories:
        t = m.get("type", "general")
        mem_by_type[t] = mem_by_type.get(t, 0) + 1

    all_tasks = tasks.list_all()
    tasks_by_status: dict[str, int] = {}
    for t in all_tasks:
        s = t.status.value
        tasks_by_status[s] = tasks_by_status.get(s, 0) + 1

    cron_jobs = cron.list_all()
    active_crons = [j for j in cron_jobs if j.active]

    return {
        "status": "healthy",
        "version": __version__,
        "uptime_info": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "components": {
            "memory": {
                "status": "ok",
                "total": len(memories),
                "by_type": mem_by_type,
            },
            "cron": {
                "status": "ok",
                "total_jobs": len(cron_jobs),
                "active_jobs": len(active_crons),
                "jobs": [
                    {
                        "id": j.id,
                        "prompt": j.prompt[:50],
                        "interval": cron.format_interval(j.interval_seconds),
                        "active": j.active,
                        "run_count": j.run_count,
                        "last_run": j.last_run,
                        "next_run": j.last_run + j.interval_seconds if j.last_run else j.created_at + j.interval_seconds,
                    }
                    for j in cron_jobs
                ],
            },
            "triggers": {
                "status": "ok" if trigger.running else "stopped",
                "running": trigger.running,
                "port": trigger.port,
                "results_count": len(trigger.list_results()),
            },
            "tasks": {
                "status": "ok",
                "total": len(all_tasks),
                "by_status": tasks_by_status,
            },
        },
        "recent_actions": _recent_actions[-10:],
    }


# ── HTML/CSS/JS completo inline ──────────────────────────────

WEBAPP_HTML = r'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Clow — AI Code Agent</title>
<style>
  :root {
    --bg-primary: #0d1117;
    --bg-secondary: #161b22;
    --bg-tertiary: #1c2128;
    --bg-code: #0d1117;
    --text-primary: #e6edf3;
    --text-secondary: #8b949e;
    --text-muted: #484f58;
    --accent: #FFD700;
    --accent-dim: #B8860B;
    --green: #4ade80;
    --red: #f87171;
    --blue: #58a6ff;
    --purple: #bc8cff;
    --border: #30363d;
    --border-subtle: #21262d;
    --font-mono: "Fira Code", "JetBrains Mono", "Cascadia Code", "Consolas", monospace;
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    background: var(--bg-primary);
    color: var(--text-primary);
    font-family: var(--font-mono);
    font-size: 14px;
    line-height: 1.6;
    height: 100vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  /* ── Top Bar ── */
  .top-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 16px;
    background: var(--bg-secondary);
    border-bottom: 1px solid var(--border);
    height: 40px;
    flex-shrink: 0;
  }
  .top-bar .logo { color: var(--accent); font-weight: 600; font-size: 15px; }
  .top-bar .version { color: var(--text-muted); font-size: 12px; margin-left: 8px; }
  .top-bar .status { font-size: 12px; display: flex; align-items: center; gap: 6px; }
  .top-bar .nav-links { display: flex; gap: 12px; }
  .top-bar .nav-links a {
    color: var(--text-secondary); font-size: 12px; text-decoration: none;
    padding: 2px 8px; border-radius: 4px; transition: all 0.2s;
  }
  .top-bar .nav-links a:hover { color: var(--accent); background: var(--bg-tertiary); }
  .top-bar .nav-links a.active { color: var(--accent); border-bottom: 1px solid var(--accent); }
  .status-dot { width: 8px; height: 8px; border-radius: 50%; }
  .status-dot.connected { background: var(--green); }
  .status-dot.disconnected { background: var(--red); }
  .status-dot.reconnecting { background: var(--accent); animation: blink-cursor 1s infinite; }

  /* ── Messages Area ── */
  .messages {
    flex: 1;
    overflow-y: auto;
    padding: 16px;
    scroll-behavior: smooth;
  }
  .messages::-webkit-scrollbar { width: 6px; }
  .messages::-webkit-scrollbar-track { background: transparent; }
  .messages::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
  .messages::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }

  .message { margin-bottom: 16px; padding: 8px 0; }
  .message.user .msg-label { color: var(--accent); font-weight: 600; font-size: 13px; }
  .message.assistant .msg-label { color: var(--blue); font-weight: 600; font-size: 13px; }
  .msg-content {
    margin-top: 4px;
    white-space: pre-wrap;
    word-wrap: break-word;
    font-size: 14px;
  }
  .message.user .msg-content { color: var(--text-primary); }
  .message.assistant .msg-content { color: var(--text-primary); }

  /* ── Code blocks ── */
  .msg-content code {
    background: var(--bg-code);
    padding: 1px 4px;
    border-radius: 3px;
    font-size: 13px;
  }
  .msg-content pre {
    background: var(--bg-tertiary);
    border: 1px solid var(--border-subtle);
    border-radius: 6px;
    padding: 12px;
    margin: 8px 0;
    overflow-x: auto;
    font-size: 13px;
  }
  .msg-content pre code { background: none; padding: 0; }

  /* ── Thinking Indicator ── */
  .thinking-container { display: flex; align-items: center; gap: 10px; padding: 12px 0; }
  .thinking-icon { font-size: 24px; animation: clow-thinking 1.5s ease-in-out infinite; }
  .thinking-text { color: var(--text-secondary); font-size: 13px; }
  .thinking-dots::after { content: ''; animation: dots 1.5s steps(4, end) infinite; }

  @keyframes clow-thinking {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.4; transform: scale(0.95); }
  }
  @keyframes dots {
    0% { content: ''; }
    25% { content: '.'; }
    50% { content: '..'; }
    75% { content: '...'; }
  }

  /* ── Shimmer Bar ── */
  .shimmer-bar {
    height: 2px;
    background: var(--bg-tertiary);
    overflow: hidden;
    position: relative;
    border-radius: 1px;
    margin-bottom: 8px;
  }
  .shimmer-bar::after {
    content: '';
    position: absolute;
    top: 0; left: 0;
    width: 40%;
    height: 100%;
    background: linear-gradient(90deg, transparent, var(--accent), transparent);
    animation: shimmer 1.5s ease-in-out infinite;
  }
  @keyframes shimmer {
    0% { transform: translateX(-100%); }
    100% { transform: translateX(350%); }
  }

  /* ── Streaming Cursor ── */
  .streaming-cursor {
    display: inline-block;
    width: 8px;
    height: 16px;
    background: var(--accent);
    animation: blink-cursor 0.8s step-end infinite;
    vertical-align: text-bottom;
    margin-left: 2px;
  }
  @keyframes blink-cursor {
    0%, 50% { opacity: 1; }
    51%, 100% { opacity: 0; }
  }

  /* ── Tool Call Blocks ── */
  .tool-block {
    margin: 8px 0;
    border: 1px solid var(--border-subtle);
    border-radius: 6px;
    overflow: hidden;
    font-size: 13px;
  }
  .tool-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 12px;
    background: var(--bg-secondary);
    cursor: pointer;
    user-select: none;
  }
  .tool-header:hover { background: var(--bg-tertiary); }
  .tool-spinner { animation: spin 1s linear infinite; display: inline-block; }
  @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
  .tool-name { color: var(--purple); font-weight: 600; }
  .tool-duration { color: var(--text-muted); margin-left: auto; font-size: 12px; }
  .tool-status-icon { font-size: 14px; }
  .tool-body {
    padding: 8px 12px;
    background: var(--bg-primary);
    border-top: 1px solid var(--border-subtle);
    max-height: 200px;
    overflow-y: auto;
    color: var(--text-secondary);
    display: none;
  }
  .tool-block.expanded .tool-body { display: block; }
  .tool-block.running .tool-body { display: block; }

  /* ── Diff Visual ── */
  .diff-add { color: var(--green); }
  .diff-del { color: var(--red); }

  /* ── Input Area ── */
  .input-area {
    padding: 12px 16px;
    background: var(--bg-secondary);
    border-top: 1px solid var(--border);
    flex-shrink: 0;
  }
  .input-wrapper {
    display: flex;
    align-items: flex-end;
    gap: 8px;
    background: var(--bg-tertiary);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 8px 12px;
    transition: border-color 0.2s;
  }
  .input-wrapper:focus-within { border-color: var(--accent-dim); }
  .input-prompt { color: var(--accent); font-weight: 600; padding-bottom: 2px; user-select: none; }
  .input-wrapper textarea {
    flex: 1;
    background: none;
    border: none;
    color: var(--text-primary);
    font-family: var(--font-mono);
    font-size: 14px;
    line-height: 1.5;
    resize: none;
    outline: none;
    max-height: 120px;
    min-height: 20px;
  }
  .input-wrapper textarea::placeholder { color: var(--text-muted); }
  .send-btn {
    background: var(--accent);
    color: var(--bg-primary);
    border: none;
    border-radius: 4px;
    padding: 4px 12px;
    font-family: var(--font-mono);
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    transition: opacity 0.2s;
  }
  .send-btn:hover { opacity: 0.85; }
  .send-btn:disabled { opacity: 0.4; cursor: not-allowed; }

  .input-hint {
    margin-top: 4px;
    font-size: 11px;
    color: var(--text-muted);
    text-align: center;
  }

  /* ── Reconnecting overlay ── */
  .reconnecting {
    position: fixed;
    top: 44px;
    left: 50%;
    transform: translateX(-50%);
    background: var(--red);
    color: #fff;
    padding: 4px 16px;
    border-radius: 0 0 6px 6px;
    font-size: 12px;
    z-index: 100;
    display: none;
  }
  .reconnecting.active { display: block; }
</style>
</head>
<body>

<div class="top-bar">
  <div style="display:flex;align-items:center;">
    <span class="logo">🃏 Clow</span>
    <span class="version">v''' + __version__ + r'''</span>
    <div class="nav-links" style="margin-left:24px;">
      <a href="/" class="active">Chat</a>
      <a href="/dashboard">Dashboard</a>
    </div>
  </div>
  <div class="status">
    <div class="status-dot connected" id="statusDot"></div>
    <span id="statusText" style="color: var(--text-muted); font-size: 12px;">Conectado</span>
  </div>
</div>

<div class="reconnecting" id="reconnectBanner">Reconectando...</div>

<div class="messages" id="messages">
  <div class="message assistant">
    <div class="msg-label">🃏 Clow</div>
    <div class="msg-content">Pronto para ajudar. Digite sua mensagem abaixo.</div>
  </div>
</div>

<div class="input-area">
  <div class="input-wrapper">
    <span class="input-prompt">❯</span>
    <textarea id="input" rows="1" placeholder="Digite sua mensagem..." autofocus></textarea>
    <button class="send-btn" id="sendBtn" onclick="sendMessage()">Enviar</button>
  </div>
  <div class="input-hint">Enter para enviar · Shift+Enter para nova linha</div>
</div>

<script>
const messagesEl = document.getElementById('messages');
const inputEl = document.getElementById('input');
const sendBtn = document.getElementById('sendBtn');
const statusDot = document.getElementById('statusDot');
const statusText = document.getElementById('statusText');
const reconnectBanner = document.getElementById('reconnectBanner');

let ws = null;
let isProcessing = false;
let currentAssistantEl = null;
let currentContentEl = null;
let currentToolEl = null;
let toolStartTime = 0;
let toolTimer = null;
let reconnectAttempts = 0;

function connectWS() {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(`${protocol}//${location.host}/ws`);

  ws.onopen = () => {
    statusDot.className = 'status-dot connected';
    statusText.textContent = 'Conectado';
    reconnectBanner.classList.remove('active');
    reconnectAttempts = 0;
  };

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    handleMessage(msg);
  };

  ws.onclose = () => {
    statusDot.className = 'status-dot disconnected';
    statusText.textContent = 'Desconectado';
    reconnectBanner.classList.add('active');
    reconnectBanner.textContent = 'Reconectando...';
    setTimeout(() => {
      reconnectAttempts++;
      connectWS();
    }, Math.min(1000 * reconnectAttempts, 5000));
  };

  ws.onerror = () => {
    statusDot.className = 'status-dot reconnecting';
  };
}

function handleMessage(msg) {
  switch (msg.type) {
    case 'thinking_start':
      showThinking();
      break;
    case 'thinking_end':
      hideThinking();
      break;
    case 'text_delta':
      appendText(msg.content);
      break;
    case 'text_done':
      finishText();
      break;
    case 'tool_call':
      showToolCall(msg.name, msg.args);
      break;
    case 'tool_result':
      showToolResult(msg.name, msg.status, msg.output);
      break;
    case 'turn_complete':
      finishTurn();
      break;
    case 'error':
      showError(msg.content);
      break;
  }
}

function sendMessage() {
  const text = inputEl.value.trim();
  if (!text || isProcessing || !ws || ws.readyState !== WebSocket.OPEN) return;

  addUserMessage(text);
  ws.send(JSON.stringify({ type: 'message', content: text }));
  inputEl.value = '';
  inputEl.style.height = 'auto';
  isProcessing = true;
  sendBtn.disabled = true;
}

function addUserMessage(text) {
  const div = document.createElement('div');
  div.className = 'message user';
  div.innerHTML = `<div class="msg-label" style="color:var(--accent)">❯ Você</div><div class="msg-content">${escapeHtml(text)}</div>`;
  messagesEl.appendChild(div);
  scrollToBottom();
}

function showThinking() {
  hideThinking();
  const div = document.createElement('div');
  div.className = 'message assistant';
  div.id = 'thinkingMsg';
  div.innerHTML = `
    <div class="shimmer-bar"></div>
    <div class="thinking-container">
      <span class="thinking-icon">🃏</span>
      <span class="thinking-text">Pensando<span class="thinking-dots"></span></span>
    </div>`;
  messagesEl.appendChild(div);
  scrollToBottom();
}

function hideThinking() {
  const el = document.getElementById('thinkingMsg');
  if (el) el.remove();
}

function ensureAssistantEl() {
  if (!currentAssistantEl) {
    hideThinking();
    currentAssistantEl = document.createElement('div');
    currentAssistantEl.className = 'message assistant';
    currentAssistantEl.innerHTML = '<div class="msg-label">🃏 Clow</div>';
    currentContentEl = document.createElement('div');
    currentContentEl.className = 'msg-content';
    currentAssistantEl.appendChild(currentContentEl);
    messagesEl.appendChild(currentAssistantEl);
  }
}

function appendText(text) {
  ensureAssistantEl();
  // Remove old cursor
  const oldCursor = currentContentEl.querySelector('.streaming-cursor');
  if (oldCursor) oldCursor.remove();
  // Append text
  currentContentEl.insertAdjacentText('beforeend', text);
  // Add cursor
  const cursor = document.createElement('span');
  cursor.className = 'streaming-cursor';
  currentContentEl.appendChild(cursor);
  scrollToBottom();
}

function finishText() {
  if (currentContentEl) {
    const cursor = currentContentEl.querySelector('.streaming-cursor');
    if (cursor) cursor.remove();
  }
}

function showToolCall(name, args) {
  ensureAssistantEl();
  const block = document.createElement('div');
  block.className = 'tool-block running';
  block.id = 'tool-' + Date.now();
  const argsStr = typeof args === 'string' ? args : JSON.stringify(args, null, 2);
  block.innerHTML = `
    <div class="tool-header" onclick="this.parentElement.classList.toggle('expanded')">
      <span class="tool-spinner tool-status-icon">⚙</span>
      <span class="tool-name">${escapeHtml(name)}</span>
      <span class="tool-duration">0.0s</span>
    </div>
    <div class="tool-body"><pre>${escapeHtml(argsStr).substring(0, 500)}</pre></div>`;
  currentAssistantEl.appendChild(block);
  currentToolEl = block;
  toolStartTime = Date.now();
  if (toolTimer) clearInterval(toolTimer);
  toolTimer = setInterval(() => {
    if (!currentToolEl) { clearInterval(toolTimer); return; }
    const elapsed = ((Date.now() - toolStartTime) / 1000).toFixed(1);
    const dur = currentToolEl.querySelector('.tool-duration');
    if (dur) dur.textContent = elapsed + 's';
  }, 100);
  scrollToBottom();
}

function showToolResult(name, status, output) {
  if (toolTimer) { clearInterval(toolTimer); toolTimer = null; }
  if (currentToolEl) {
    currentToolEl.classList.remove('running');
    const icon = currentToolEl.querySelector('.tool-status-icon');
    if (icon) {
      icon.classList.remove('tool-spinner');
      if (status === 'success') {
        icon.textContent = '✓';
        icon.style.color = 'var(--green)';
      } else if (status === 'error') {
        icon.textContent = '✗';
        icon.style.color = 'var(--red)';
      } else {
        icon.textContent = '⊘';
        icon.style.color = 'var(--accent)';
      }
    }
    // Add output to body
    if (output) {
      const body = currentToolEl.querySelector('.tool-body');
      if (body) {
        body.innerHTML += `<pre style="margin-top:4px;color:${status==='error'?'var(--red)':'var(--text-secondary)'}">${escapeHtml(output).substring(0, 1000)}</pre>`;
      }
    }
    const elapsed = ((Date.now() - toolStartTime) / 1000).toFixed(1);
    const dur = currentToolEl.querySelector('.tool-duration');
    if (dur) dur.textContent = elapsed + 's';
    currentToolEl = null;
  }
  scrollToBottom();
}

function showError(text) {
  ensureAssistantEl();
  const errDiv = document.createElement('div');
  errDiv.style.cssText = 'color:var(--red);margin:8px 0;';
  errDiv.textContent = '✗ ' + text;
  currentAssistantEl.appendChild(errDiv);
  scrollToBottom();
}

function finishTurn() {
  finishText();
  isProcessing = false;
  sendBtn.disabled = false;
  currentAssistantEl = null;
  currentContentEl = null;
  inputEl.focus();
}

function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function escapeHtml(text) {
  const d = document.createElement('div');
  d.textContent = text;
  return d.innerHTML;
}

// ── Input handling ──
inputEl.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});
inputEl.addEventListener('input', () => {
  inputEl.style.height = 'auto';
  inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + 'px';
});

// ── Init ──
connectWS();
</script>
</body>
</html>
'''


# ── Feature #24: Dashboard HTML ────────────────────────────────

DASHBOARD_HTML = r'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Clow — Dashboard</title>
<style>
  :root {
    --bg-primary: #0d1117;
    --bg-secondary: #161b22;
    --bg-tertiary: #1c2128;
    --text-primary: #e6edf3;
    --text-secondary: #8b949e;
    --text-muted: #484f58;
    --accent: #FFD700;
    --accent-dim: #B8860B;
    --green: #4ade80;
    --red: #f87171;
    --blue: #58a6ff;
    --purple: #bc8cff;
    --border: #30363d;
    --font-mono: "Fira Code", "JetBrains Mono", "Cascadia Code", "Consolas", monospace;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: var(--bg-primary);
    color: var(--text-primary);
    font-family: var(--font-mono);
    font-size: 14px;
    line-height: 1.6;
  }
  .top-bar {
    display: flex; align-items: center; justify-content: space-between;
    padding: 8px 16px; background: var(--bg-secondary);
    border-bottom: 1px solid var(--border); height: 40px;
  }
  .top-bar .logo { color: var(--accent); font-weight: 600; font-size: 15px; }
  .top-bar .version { color: var(--text-muted); font-size: 12px; margin-left: 8px; }
  .top-bar .nav-links { display: flex; gap: 12px; margin-left: 24px; }
  .top-bar .nav-links a {
    color: var(--text-secondary); font-size: 12px; text-decoration: none;
    padding: 2px 8px; border-radius: 4px; transition: all 0.2s;
  }
  .top-bar .nav-links a:hover { color: var(--accent); background: var(--bg-tertiary); }
  .top-bar .nav-links a.active { color: var(--accent); border-bottom: 1px solid var(--accent); }

  .dashboard { padding: 20px; max-width: 1200px; margin: 0 auto; }
  .dashboard h2 { color: var(--accent); margin-bottom: 16px; font-size: 16px; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; margin-bottom: 24px; }
  .card {
    background: var(--bg-secondary); border: 1px solid var(--border);
    border-radius: 8px; padding: 16px;
  }
  .card h3 { color: var(--blue); font-size: 13px; margin-bottom: 10px; text-transform: uppercase; letter-spacing: 0.5px; }
  .card .big-num { font-size: 32px; font-weight: 600; color: var(--accent); }
  .card .detail { color: var(--text-secondary); font-size: 12px; margin-top: 4px; }
  .card .badge {
    display: inline-block; padding: 1px 6px; border-radius: 3px;
    font-size: 11px; margin-right: 4px;
  }
  .badge.ok { background: rgba(74,222,128,0.15); color: var(--green); }
  .badge.warn { background: rgba(248,113,113,0.15); color: var(--red); }
  .badge.info { background: rgba(88,166,255,0.15); color: var(--blue); }

  table {
    width: 100%; border-collapse: collapse;
    background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 8px;
    overflow: hidden; margin-bottom: 24px;
  }
  th { background: var(--bg-tertiary); color: var(--text-secondary); font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; text-align: left; padding: 8px 12px; }
  td { padding: 6px 12px; border-top: 1px solid var(--border); font-size: 13px; color: var(--text-primary); }
  .status-ok { color: var(--green); }
  .status-err { color: var(--red); }
  .status-run { color: var(--blue); }
  .refresh-info { color: var(--text-muted); font-size: 11px; text-align: right; margin-bottom: 8px; }
</style>
</head>
<body>
<div class="top-bar">
  <div style="display:flex;align-items:center;">
    <span class="logo">🃏 Clow</span>
    <span class="version">v''' + __version__ + r'''</span>
    <div class="nav-links" style="margin-left:24px;">
      <a href="/">Chat</a>
      <a href="/dashboard" class="active">Dashboard</a>
    </div>
  </div>
</div>
<div class="dashboard">
  <h2>📊 Dashboard</h2>
  <div class="refresh-info">Auto-refresh a cada 10s · <span id="lastUpdate">-</span></div>
  <div class="cards" id="cards">
    <div class="card"><h3>Carregando...</h3></div>
  </div>
  <h2>🕐 Cron Jobs</h2>
  <table id="cronTable"><thead><tr><th>ID</th><th>Prompt</th><th>Intervalo</th><th>Status</th><th>Execuções</th><th>Próxima</th></tr></thead><tbody id="cronBody"><tr><td colspan="6" style="color:var(--text-muted)">Carregando...</td></tr></tbody></table>
  <h2>🔄 Ações Recentes</h2>
  <table id="actionsTable"><thead><tr><th>Hora</th><th>Ação</th><th>Detalhes</th><th>Status</th></tr></thead><tbody id="actionsBody"><tr><td colspan="4" style="color:var(--text-muted)">Carregando...</td></tr></tbody></table>
</div>
<script>
async function refresh() {
  try {
    const r = await fetch('/health');
    const d = await r.json();
    document.getElementById('lastUpdate').textContent = new Date().toLocaleTimeString();

    const c = d.components;
    document.getElementById('cards').innerHTML = `
      <div class="card"><h3>Tasks</h3>
        <div class="big-num">${c.tasks.total}</div>
        <div class="detail">${Object.entries(c.tasks.by_status).map(([k,v])=>`<span class="badge ${k==='completed'?'ok':k==='failed'?'warn':'info'}">${k}: ${v}</span>`).join('')}</div>
      </div>
      <div class="card"><h3>Cron Jobs</h3>
        <div class="big-num">${c.cron.active_jobs}<span style="font-size:14px;color:var(--text-muted)"> / ${c.cron.total_jobs}</span></div>
        <div class="detail">ativos</div>
      </div>
      <div class="card"><h3>Memória</h3>
        <div class="big-num">${c.memory.total}</div>
        <div class="detail">${Object.entries(c.memory.by_type).map(([k,v])=>`<span class="badge info">${k}: ${v}</span>`).join('')}</div>
      </div>
      <div class="card"><h3>Triggers</h3>
        <div class="big-num">${c.triggers.results_count}</div>
        <div class="detail">${c.triggers.running?'<span class="badge ok">online porta '+c.triggers.port+'</span>':'<span class="badge warn">offline</span>'}</div>
      </div>`;

    // Cron table
    const cronBody = document.getElementById('cronBody');
    if (c.cron.jobs.length === 0) {
      cronBody.innerHTML = '<tr><td colspan="6" style="color:var(--text-muted)">Nenhum cron job</td></tr>';
    } else {
      cronBody.innerHTML = c.cron.jobs.map(j => {
        const next = new Date(j.next_run * 1000).toLocaleTimeString();
        return `<tr>
          <td>${j.id}</td>
          <td>${j.prompt}</td>
          <td>${j.interval}</td>
          <td class="${j.active?'status-ok':'status-err'}">${j.active?'ativo':'pausado'}</td>
          <td>${j.run_count}x</td>
          <td>${next}</td>
        </tr>`;
      }).join('');
    }

    // Actions table
    const actionsBody = document.getElementById('actionsBody');
    const actions = d.recent_actions || [];
    if (actions.length === 0) {
      actionsBody.innerHTML = '<tr><td colspan="4" style="color:var(--text-muted)">Nenhuma ação recente</td></tr>';
    } else {
      actionsBody.innerHTML = actions.reverse().map(a => {
        const t = new Date(a.timestamp * 1000).toLocaleTimeString();
        return `<tr>
          <td>${t}</td>
          <td>${a.action}</td>
          <td style="color:var(--text-secondary)">${a.details}</td>
          <td class="${a.status==='ok'?'status-ok':'status-err'}">${a.status}</td>
        </tr>`;
      }).join('');
    }
  } catch(e) {
    document.getElementById('cards').innerHTML = `<div class="card"><h3 style="color:var(--red)">Erro ao carregar</h3><div class="detail">${e.message}</div></div>`;
  }
}
refresh();
setInterval(refresh, 10000);
</script>
</body>
</html>
'''


if HAS_FASTAPI:
    @app.get("/", response_class=HTMLResponse)
    async def index():
        return WEBAPP_HTML

    # Feature #24: Dashboard (protegido)
    @app.get("/dashboard", response_class=HTMLResponse, dependencies=[Depends(_auth_dependency)])
    async def dashboard():
        return DASHBOARD_HTML

    # Feature #19: Health Check (publico — sem auth)
    @app.get("/health", dependencies=[Depends(_rate_limit_dependency)])
    async def health():
        return JSONResponse(_get_health_data())

    # API endpoints protegidos
    @app.get("/api/v1/status", dependencies=[Depends(_auth_dependency), Depends(_rate_limit_dependency)])
    async def api_status():
        """Status completo da API com metricas."""
        return JSONResponse({
            "version": __version__,
            "status": "ok",
            **_get_health_data(),
        })

    @app.post("/api/v1/generate-key", dependencies=[Depends(_auth_dependency)])
    async def generate_key():
        """Gera nova API key para autenticacao."""
        key = _generate_api_key()
        return JSONResponse({"api_key": key, "note": "Adicione esta key em settings.json > webapp > api_keys"})

    @app.get("/api/v1/metrics", dependencies=[Depends(_auth_dependency), Depends(_rate_limit_dependency)])
    async def api_metrics():
        """Retorna metricas coletadas (counters, gauges, histograms)."""
        from .logging import metrics
        return JSONResponse(metrics.snapshot())

    @app.get("/api/v1/sessions", dependencies=[Depends(_auth_dependency), Depends(_rate_limit_dependency)])
    async def api_sessions():
        """Lista sessoes salvas."""
        from .session import list_sessions
        return JSONResponse({"sessions": list_sessions()})

    @app.get("/api/v1/memory", dependencies=[Depends(_auth_dependency), Depends(_rate_limit_dependency)])
    async def api_memory():
        """Lista memorias persistidas."""
        from .memory import list_memories
        return JSONResponse({"memories": list_memories()})

    @app.get("/api/v1/tools", dependencies=[Depends(_auth_dependency)])
    async def api_tools():
        """Lista todas as ferramentas disponiveis."""
        from .tools.base import create_default_registry
        registry = create_default_registry()
        tools = [{"name": t.name, "description": t.description} for t in registry.all_tools()]
        return JSONResponse({"tools": tools, "count": len(tools)})

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        # Verificacao de API key via query param para WebSocket
        api_key = websocket.query_params.get("api_key", "")
        keys = _get_api_keys()
        if keys and not _verify_api_key(api_key):
            await websocket.close(code=4001, reason="API key invalida")
            return

        # Rate limit para WebSocket
        client_ip = websocket.client.host if websocket.client else "unknown"
        if not _ws_rate_limiter.is_allowed(client_ip):
            await websocket.close(code=4029, reason="Rate limit excedido")
            return

        await websocket.accept()

        from .agent import Agent

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
                    if not content:
                        continue

                    track_action("user_message", content[:60])

                    # Envia thinking
                    await websocket.send_json({"type": "thinking_start"})

                    # Executa agente em thread separada
                    try:
                        result = await loop.run_in_executor(
                            None, agent.run_turn, content
                        )
                        track_action("agent_response", result[:60] if result else "")
                    except Exception as e:
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
