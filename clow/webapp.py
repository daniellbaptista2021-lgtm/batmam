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
from pathlib import Path

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException, Depends
    from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles
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


# ── Login / Sessao Web (SQLite backed) ──────────────────────────

from .database import (
    authenticate_user, create_user, get_user_by_email, get_user_by_id,
    list_users, update_user, log_usage, get_user_usage_today, check_limit,
    get_admin_stats, create_conversation, list_conversations, delete_conversation,
    save_message, get_messages, update_conversation_title, PLANS, ADMIN_EMAIL,
)

_web_sessions: dict[str, dict] = {}  # token -> {"email", "user_id", "is_admin", "created"}
_SESSION_TTL = 86400 * 7  # 7 dias


def _create_session(user: dict) -> str:
    token = secrets.token_urlsafe(48)
    _web_sessions[token] = {
        "email": user["email"],
        "user_id": user["id"],
        "is_admin": bool(user.get("is_admin")),
        "plan": user.get("plan", "free"),
        "created": time.time(),
    }
    return token


def _validate_session(token: str) -> dict | None:
    sess = _web_sessions.get(token)
    if not sess:
        return None
    if time.time() - sess["created"] > _SESSION_TTL:
        del _web_sessions[token]
        return None
    return sess


def _get_session_from_request(request: Request) -> str | None:
    """Returns email string for backwards compat."""
    token = request.cookies.get("clow_session", "")
    sess = _validate_session(token)
    return sess["email"] if sess else None


def _get_user_session(request: Request) -> dict | None:
    """Returns full session dict."""
    token = request.cookies.get("clow_session", "")
    return _validate_session(token)


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
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
<meta name="theme-color" content="#0a0a0f">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<link rel="manifest" href="/static/manifest.json">
<title>Clow</title>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&display=swap');

  :root {
    --bg-deep: #06060b;
    --bg-primary: #0a0a0f;
    --bg-secondary: #111118;
    --bg-tertiary: #16161f;
    --bg-surface: #1a1a25;
    --bg-elevated: #1e1e2a;
    --text-primary: #f0f0f5;
    --text-secondary: #9d9db5;
    --text-muted: #55556a;
    --purple: #a78bfa;
    --purple-bright: #c4b5fd;
    --purple-dim: #7c3aed;
    --purple-deep: #5b21b6;
    --purple-glow: rgba(167,139,250,0.15);
    --purple-glow-strong: rgba(167,139,250,0.3);
    --violet: #8b5cf6;
    --green: #34d399;
    --green-dim: rgba(52,211,153,0.15);
    --red: #f87171;
    --red-dim: rgba(248,113,113,0.15);
    --amber: #fbbf24;
    --border: rgba(167,139,250,0.12);
    --border-focus: rgba(167,139,250,0.4);
    --font-mono: "JetBrains Mono", "Fira Code", "Cascadia Code", "SF Mono", monospace;
    --safe-top: env(safe-area-inset-top, 0px);
    --safe-bottom: env(safe-area-inset-bottom, 0px);
  }

  * { margin: 0; padding: 0; box-sizing: border-box; -webkit-tap-highlight-color: transparent; }

  html { height: 100%; overflow: hidden; }

  body {
    background: var(--bg-deep);
    color: var(--text-primary);
    font-family: var(--font-mono);
    font-size: 13px;
    line-height: 1.65;
    height: 100%;
    height: 100dvh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    -webkit-font-smoothing: antialiased;
  }

  /* ── Title Bar ── */
  .title-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 16px;
    padding-top: var(--safe-top);
    background: var(--bg-primary);
    border-bottom: 1px solid var(--border);
    height: calc(52px + var(--safe-top));
    flex-shrink: 0;
    position: relative;
    z-index: 10;
  }

  .title-left {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .logo-infinity {
    width: 28px;
    height: 28px;
    flex-shrink: 0;
  }
  .logo-infinity path {
    fill: none;
    stroke: var(--purple);
    stroke-width: 3;
    stroke-linecap: round;
    stroke-linejoin: round;
  }

  .logo-text {
    font-size: 20px;
    font-weight: 700;
    letter-spacing: 2px;
    background: linear-gradient(135deg, var(--purple-bright) 0%, var(--purple) 50%, var(--violet) 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    text-transform: uppercase;
  }

  .title-right {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .conn-badge {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border-radius: 20px;
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 0.5px;
    text-transform: uppercase;
  }
  .conn-badge.online {
    background: var(--green-dim);
    color: var(--green);
    border: 1px solid rgba(52,211,153,0.25);
  }
  .conn-badge.offline {
    background: var(--red-dim);
    color: var(--red);
    border: 1px solid rgba(248,113,113,0.25);
  }
  .conn-dot {
    width: 6px; height: 6px;
    border-radius: 50%;
    background: currentColor;
  }
  .conn-badge.online .conn-dot { animation: pulse-dot 2s ease-in-out infinite; }
  @keyframes pulse-dot {
    0%, 100% { opacity: 1; box-shadow: 0 0 0 0 currentColor; }
    50% { opacity: 0.6; box-shadow: 0 0 6px 2px currentColor; }
  }

  .nav-btn {
    background: var(--bg-tertiary);
    border: 1px solid var(--border);
    color: var(--text-secondary);
    font-family: var(--font-mono);
    font-size: 10px;
    font-weight: 500;
    padding: 5px 10px;
    border-radius: 6px;
    cursor: pointer;
    text-decoration: none;
    transition: all 0.2s;
    letter-spacing: 0.3px;
  }
  .nav-btn:hover, .nav-btn:active { background: var(--bg-surface); color: var(--purple); border-color: var(--border-focus); }

  /* ── Terminal Session Area ── */
  .terminal {
    flex: 1;
    overflow-y: auto;
    overflow-x: hidden;
    padding: 16px;
    padding-bottom: 8px;
    scroll-behavior: smooth;
    -webkit-overflow-scrolling: touch;
    background: var(--bg-deep);
  }
  .terminal::-webkit-scrollbar { width: 4px; }
  .terminal::-webkit-scrollbar-track { background: transparent; }
  .terminal::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }

  /* ── Welcome Block ── */
  .welcome {
    text-align: center;
    padding: 24px 16px 32px;
    margin-bottom: 8px;
  }
  .welcome-infinity {
    width: 48px; height: 48px;
    margin: 0 auto 16px;
    opacity: 0.7;
  }
  .welcome-infinity path {
    fill: none;
    stroke: var(--purple);
    stroke-width: 2.5;
    stroke-linecap: round;
  }
  .welcome h2 {
    font-size: 15px;
    font-weight: 600;
    color: var(--text-primary);
    margin-bottom: 6px;
  }
  .welcome p {
    font-size: 12px;
    color: var(--text-muted);
    max-width: 280px;
    margin: 0 auto;
  }
  .welcome .ver {
    display: inline-block;
    margin-top: 10px;
    font-size: 10px;
    color: var(--text-muted);
    background: var(--bg-tertiary);
    padding: 2px 8px;
    border-radius: 4px;
    border: 1px solid var(--border);
  }
  .quick-actions {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 10px;
    max-width: 360px;
    margin: 20px auto 0;
  }
  .qa-card {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 12px;
    cursor: pointer;
    transition: all 0.2s;
    text-align: left;
  }
  .qa-card:hover, .qa-card:active {
    border-color: var(--border-focus);
    background: var(--bg-tertiary);
    transform: translateY(-1px);
  }
  .qa-icon { font-size: 18px; margin-bottom: 6px; }
  .qa-title { font-size: 11px; font-weight: 600; color: var(--text-primary); }
  .qa-desc { font-size: 10px; color: var(--text-muted); margin-top: 2px; }

  /* ── Message Lines ── */
  .msg-line {
    margin-bottom: 20px;
    animation: msg-in 0.25s ease-out;
  }
  @keyframes msg-in {
    from { opacity: 0; transform: translateY(6px); }
    to { opacity: 1; transform: translateY(0); }
  }

  .msg-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 6px;
  }
  .msg-avatar {
    width: 22px; height: 22px;
    border-radius: 6px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 10px;
    font-weight: 700;
    flex-shrink: 0;
  }
  .msg-line.user .msg-avatar {
    background: var(--bg-surface);
    color: var(--text-secondary);
    border: 1px solid var(--border);
  }
  .msg-line.assistant .msg-avatar {
    background: var(--purple-glow-strong);
    border: 1px solid rgba(167,139,250,0.3);
    padding: 3px;
  }
  .msg-line.assistant .msg-avatar svg {
    width: 14px; height: 14px;
  }
  .msg-line.assistant .msg-avatar svg path {
    fill: none;
    stroke: var(--purple-bright);
    stroke-width: 3;
    stroke-linecap: round;
  }

  .msg-name {
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.3px;
  }
  .msg-line.user .msg-name { color: var(--text-secondary); }
  .msg-line.assistant .msg-name { color: var(--purple); }

  .msg-time {
    font-size: 10px;
    color: var(--text-muted);
    margin-left: auto;
  }

  .msg-body {
    padding-left: 30px;
    white-space: pre-wrap;
    word-wrap: break-word;
    word-break: break-word;
    font-size: 13px;
    line-height: 1.7;
    color: var(--text-primary);
  }
  .msg-line.user .msg-body { color: var(--text-secondary); }

  /* ── Code in messages ── */
  .msg-body code {
    background: var(--bg-surface);
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 12px;
    border: 1px solid var(--border);
    color: var(--purple-bright);
  }
  .msg-body pre {
    background: var(--bg-primary);
    border: 1px solid var(--border);
    border-left: 3px solid var(--purple-dim);
    border-radius: 8px;
    padding: 12px 14px;
    margin: 10px 0;
    overflow-x: auto;
    font-size: 12px;
    line-height: 1.6;
  }
  .msg-body pre code {
    background: none;
    padding: 0;
    border: none;
    color: var(--text-primary);
  }
  .msg-body h1, .msg-body h2, .msg-body h3 {
    color: var(--purple-bright);
    margin: 12px 0 6px;
    font-size: 14px;
    font-weight: 700;
  }
  .msg-body h1 { font-size: 16px; }
  .msg-body h2 { font-size: 15px; }
  .msg-body ul, .msg-body ol {
    margin: 6px 0;
    padding-left: 20px;
  }
  .msg-body li { margin-bottom: 3px; }
  .msg-body p { margin: 6px 0; }
  .msg-body a {
    color: var(--purple);
    text-decoration: underline;
    text-decoration-color: rgba(167,139,250,0.4);
  }
  .msg-body a:hover { text-decoration-color: var(--purple); }
  .msg-body strong { color: var(--text-primary); font-weight: 700; }
  .msg-body em { color: var(--text-secondary); font-style: italic; }
  .msg-body blockquote {
    border-left: 3px solid var(--purple-dim);
    padding: 4px 12px;
    margin: 8px 0;
    color: var(--text-secondary);
    background: var(--bg-secondary);
    border-radius: 0 6px 6px 0;
  }
  .msg-body hr {
    border: none;
    border-top: 1px solid var(--border);
    margin: 12px 0;
  }
  .msg-body table {
    border-collapse: collapse;
    margin: 8px 0;
    font-size: 12px;
    width: 100%;
  }
  .msg-body th, .msg-body td {
    border: 1px solid var(--border);
    padding: 4px 8px;
    text-align: left;
  }
  .msg-body th {
    background: var(--bg-tertiary);
    color: var(--purple);
    font-weight: 600;
  }

  /* ── Thinking / Infinity Animation ── */
  .thinking-block {
    margin-bottom: 20px;
    animation: msg-in 0.25s ease-out;
  }
  .thinking-inner {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 14px 16px;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 12px;
  }
  .infinity-spinner {
    width: 36px; height: 36px;
    flex-shrink: 0;
    animation: infinity-draw 2s ease-in-out infinite;
  }
  .infinity-spinner path {
    fill: none;
    stroke: var(--purple);
    stroke-width: 3;
    stroke-linecap: round;
    stroke-dasharray: 120;
    stroke-dashoffset: 0;
    animation: infinity-trace 2s ease-in-out infinite;
  }
  @keyframes infinity-trace {
    0% { stroke-dashoffset: 0; stroke: var(--purple); }
    50% { stroke-dashoffset: 120; stroke: var(--purple-bright); }
    100% { stroke-dashoffset: 240; stroke: var(--purple); }
  }
  @keyframes infinity-draw {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.6; }
  }
  .thinking-label {
    font-size: 12px;
    color: var(--text-secondary);
    font-weight: 500;
  }
  .thinking-dots::after {
    content: '';
    animation: tdots 1.5s steps(4, end) infinite;
  }
  @keyframes tdots {
    0% { content: ''; } 25% { content: '.'; } 50% { content: '..'; } 75% { content: '...'; }
  }

  /* ── Shimmer Bar ── */
  .shimmer {
    height: 2px;
    background: var(--bg-tertiary);
    overflow: hidden;
    position: relative;
    border-radius: 1px;
    margin-bottom: 10px;
  }
  .shimmer::after {
    content: '';
    position: absolute;
    top: 0; left: 0;
    width: 30%;
    height: 100%;
    background: linear-gradient(90deg, transparent, var(--purple), transparent);
    animation: shimmer-move 1.8s ease-in-out infinite;
  }
  @keyframes shimmer-move {
    0% { transform: translateX(-100%); }
    100% { transform: translateX(450%); }
  }

  /* ── Streaming Cursor ── */
  .stream-cursor {
    display: inline-block;
    width: 2px;
    height: 15px;
    background: var(--purple);
    animation: cursor-blink 0.8s step-end infinite;
    vertical-align: text-bottom;
    margin-left: 1px;
    border-radius: 1px;
  }
  @keyframes cursor-blink {
    0%, 50% { opacity: 1; }
    51%, 100% { opacity: 0; }
  }

  /* ── Tool Blocks ── */
  .tool-block {
    margin: 8px 0;
    border: 1px solid var(--border);
    border-radius: 8px;
    overflow: hidden;
    font-size: 12px;
    background: var(--bg-secondary);
  }
  .tool-head {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    cursor: pointer;
    user-select: none;
    transition: background 0.15s;
  }
  .tool-head:active { background: var(--bg-tertiary); }
  .tool-icon { font-size: 13px; flex-shrink: 0; }
  .tool-icon.spinning { animation: spin 1s linear infinite; }
  @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
  .tool-label { color: var(--purple); font-weight: 600; flex: 1; }
  .tool-dur { color: var(--text-muted); font-size: 11px; }
  .tool-output {
    padding: 8px 12px;
    background: var(--bg-primary);
    border-top: 1px solid var(--border);
    max-height: 160px;
    overflow-y: auto;
    color: var(--text-secondary);
    font-size: 11px;
    display: none;
  }
  .tool-block.open .tool-output { display: block; }
  .tool-block.active .tool-output { display: block; }

  /* ── Input Area ── */
  .input-area {
    flex-shrink: 0;
    padding: 10px 12px;
    padding-bottom: calc(10px + var(--safe-bottom));
    background: var(--bg-primary);
    border-top: 1px solid var(--border);
  }
  .input-box {
    display: flex;
    align-items: flex-end;
    gap: 8px;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 10px 12px;
    transition: border-color 0.2s, box-shadow 0.2s;
  }
  .input-box:focus-within {
    border-color: var(--border-focus);
    box-shadow: 0 0 0 3px var(--purple-glow);
  }
  .input-chevron {
    color: var(--purple);
    font-weight: 700;
    font-size: 14px;
    padding-bottom: 1px;
    user-select: none;
    flex-shrink: 0;
  }
  .input-box textarea {
    flex: 1;
    background: none;
    border: none;
    color: var(--text-primary);
    font-family: var(--font-mono);
    font-size: 14px;
    line-height: 1.5;
    resize: none;
    outline: none;
    max-height: 100px;
    min-height: 20px;
  }
  .input-box textarea::placeholder { color: var(--text-muted); font-size: 13px; }

  .send-btn {
    width: 36px;
    height: 36px;
    border-radius: 10px;
    border: none;
    background: linear-gradient(135deg, var(--purple-dim), var(--violet));
    color: white;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    transition: transform 0.15s, opacity 0.15s;
  }
  .send-btn:active { transform: scale(0.92); }
  .send-btn:disabled { opacity: 0.3; cursor: not-allowed; }
  .send-btn svg { width: 18px; height: 18px; }

  .input-hint {
    margin-top: 6px;
    font-size: 10px;
    color: var(--text-muted);
    text-align: center;
    letter-spacing: 0.3px;
  }

  /* ── Reconnecting banner ── */
  .reconnect-bar {
    position: fixed;
    top: calc(52px + var(--safe-top));
    left: 0; right: 0;
    background: rgba(248,113,113,0.15);
    border-bottom: 1px solid rgba(248,113,113,0.3);
    color: var(--red);
    padding: 6px 16px;
    font-size: 11px;
    text-align: center;
    z-index: 20;
    display: none;
    backdrop-filter: blur(8px);
  }
  .reconnect-bar.active { display: block; }

  /* ── Error display ── */
  .error-line {
    color: var(--red);
    background: var(--red-dim);
    border: 1px solid rgba(248,113,113,0.2);
    border-radius: 8px;
    padding: 8px 12px;
    margin: 8px 0;
    font-size: 12px;
  }

  /* ── File Card ── */
  .file-card {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 14px 16px;
    margin: 10px 0;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 12px;
    transition: border-color 0.2s;
  }
  .file-card:hover { border-color: var(--border-focus); }
  .file-icon {
    width: 44px; height: 44px;
    border-radius: 10px;
    display: flex; align-items: center; justify-content: center;
    font-size: 20px; flex-shrink: 0;
    background: var(--purple-glow);
    border: 1px solid rgba(167,139,250,0.2);
  }
  .file-info { flex: 1; min-width: 0; }
  .file-name {
    font-size: 13px; font-weight: 600; color: var(--text-primary);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .file-meta { font-size: 10px; color: var(--text-muted); margin-top: 2px; }
  .file-actions { display: flex; gap: 6px; flex-shrink: 0; }
  .file-btn {
    padding: 8px 14px; border-radius: 8px; font-family: var(--font-mono);
    font-size: 11px; font-weight: 600; cursor: pointer; text-decoration: none;
    transition: all 0.15s; border: none;
  }
  .file-btn:active { transform: scale(0.95); }
  .file-btn.primary {
    background: linear-gradient(135deg, var(--purple-dim), var(--violet));
    color: white;
  }
  .file-btn.secondary {
    background: var(--bg-tertiary); color: var(--purple);
    border: 1px solid var(--border);
  }

  /* ── Responsive ── */
  @media (min-width: 768px) {
    .terminal { padding: 20px 24px; }
    .msg-body { padding-left: 30px; }
  }
  @media (max-width: 380px) {
    body { font-size: 12px; }
    .logo-text { font-size: 17px; letter-spacing: 1.5px; }
    .msg-body { font-size: 12px; }
  }
</style>
</head>
<body>

<!-- Title Bar -->
<div class="title-bar">
  <div class="title-left">
    <svg class="logo-infinity" viewBox="0 0 32 32">
      <path d="M8 16c0-3 2-6 5-6s5 3 8 6c3 3 5 6 8 6s5-3 5-6-2-6-5-6-5 3-8 6c-3 3-5 6-8 6s-5-3-5-6z" transform="translate(-5,0) scale(0.95)"/>
    </svg>
    <span class="logo-text">Clow</span>
  </div>
  <div class="title-right">
    <div class="conn-badge online" id="connBadge">
      <span class="conn-dot"></span>
      <span id="connLabel">online</span>
    </div>
    <a href="/dashboard" class="nav-btn">dash</a>
    <a href="/logout" class="nav-btn" style="color:var(--red);border-color:rgba(248,113,113,0.2)">sair</a>
  </div>
</div>

<!-- Reconnect Banner -->
<div class="reconnect-bar" id="reconnectBar">Reconectando ao servidor...</div>

<!-- Terminal -->
<div class="terminal" id="terminal">
  <div class="welcome" id="welcomeBlock">
    <svg class="welcome-infinity" viewBox="0 0 32 32">
      <path d="M8 16c0-3 2-6 5-6s5 3 8 6c3 3 5 6 8 6s5-3 5-6-2-6-5-6-5 3-8 6c-3 3-5 6-8 6s-5-3-5-6z" transform="translate(-5,0) scale(0.95)" fill="none" stroke="var(--purple)" stroke-width="2" stroke-linecap="round"/>
    </svg>
    <h2>System Clow</h2>
    <p>AI Code Agent — terminal inteligente na palma da mao</p>
    <span class="ver">v''' + __version__ + r'''</span>
    <div class="quick-actions">
      <div class="qa-card" onclick="quickAction('Cria uma landing page de ')">
        <div class="qa-icon">&#x1F310;</div>
        <div class="qa-title">Landing Page</div>
        <div class="qa-desc">Gerar site completo</div>
      </div>
      <div class="qa-card" onclick="quickAction('Gera uma planilha de ')">
        <div class="qa-icon">&#x1F4CA;</div>
        <div class="qa-title">Planilha</div>
        <div class="qa-desc">Excel profissional</div>
      </div>
      <div class="qa-card" onclick="quickAction('Cria uma apresentacao sobre ')">
        <div class="qa-icon">&#x1F3AC;</div>
        <div class="qa-title">Apresentacao</div>
        <div class="qa-desc">Slides PowerPoint</div>
      </div>
      <div class="qa-card" onclick="quickAction('Faz um documento de ')">
        <div class="qa-icon">&#x1F4C4;</div>
        <div class="qa-title">Documento</div>
        <div class="qa-desc">Word formatado</div>
      </div>
      <div class="qa-card" onclick="quickAction('Me faz um app de ')">
        <div class="qa-icon">&#x26A1;</div>
        <div class="qa-title">Web App</div>
        <div class="qa-desc">App funcional</div>
      </div>
      <div class="qa-card" onclick="quickAction('Ideias de conteudo para instagram sobre ')">
        <div class="qa-icon">&#x1F4F1;</div>
        <div class="qa-title">Conteudo</div>
        <div class="qa-desc">Ideias p/ redes</div>
      </div>
      <div class="qa-card" onclick="quickAction('Gera copy para anuncio de ')">
        <div class="qa-icon">&#x1F4DD;</div>
        <div class="qa-title">Copy Ads</div>
        <div class="qa-desc">Texto p/ anuncios</div>
      </div>
      <div class="qa-card" onclick="quickAction('/help')">
        <div class="qa-icon">&#x2753;</div>
        <div class="qa-title">Ajuda</div>
        <div class="qa-desc">Comandos e dicas</div>
      </div>
    </div>
  </div>
</div>

<!-- Input -->
<div class="input-area">
  <div class="input-box">
    <span class="input-chevron">&#x276f;</span>
    <textarea id="input" rows="1" placeholder="Digite um comando..." autofocus></textarea>
    <button class="send-btn" id="sendBtn" onclick="sendMessage()" aria-label="Enviar">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/>
      </svg>
    </button>
  </div>
  <div class="input-hint">Enter envia &middot; Shift+Enter nova linha</div>
</div>

<script>
const INFINITY_SVG = '<svg viewBox="0 0 32 32" style="width:14px;height:14px"><path d="M8 16c0-3 2-6 5-6s5 3 8 6c3 3 5 6 8 6s5-3 5-6-2-6-5-6-5 3-8 6c-3 3-5 6-8 6s-5-3-5-6z" transform="translate(-5,0) scale(0.95)" fill="none" stroke="var(--purple-bright)" stroke-width="3" stroke-linecap="round"/></svg>';
const SPINNER_SVG = '<svg viewBox="0 0 32 32" style="width:36px;height:36px"><path d="M8 16c0-3 2-6 5-6s5 3 8 6c3 3 5 6 8 6s5-3 5-6-2-6-5-6-5 3-8 6c-3 3-5 6-8 6s-5-3-5-6z" transform="translate(-5,0) scale(0.95)" fill="none" stroke="var(--purple)" stroke-width="3" stroke-linecap="round" stroke-dasharray="120" style="animation:infinity-trace 2s ease-in-out infinite"/></svg>';

const terminal = document.getElementById('terminal');
const inputEl = document.getElementById('input');
const sendBtn = document.getElementById('sendBtn');
const connBadge = document.getElementById('connBadge');
const connLabel = document.getElementById('connLabel');
const reconnectBar = document.getElementById('reconnectBar');

let ws = null;
let isProcessing = false;
let currentMsgEl = null;
let currentBodyEl = null;
let currentToolEl = null;
let toolStartTime = 0;
let toolTimer = null;
let reconnectAttempts = 0;
let useHttpFallback = false;
let httpSessionId = '';
let wsConnectTimeout = null;

function setOnline(label) {
  connBadge.className = 'conn-badge online';
  connLabel.textContent = label || 'online';
  reconnectBar.classList.remove('active');
}
function setOffline() {
  connBadge.className = 'conn-badge offline';
  connLabel.textContent = 'offline';
}

function connectWS() {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  try { ws = new WebSocket(`${protocol}//${location.host}/ws`); }
  catch(e) { activateHttpMode(); return; }

  wsConnectTimeout = setTimeout(() => {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      if (ws) { try { ws.close(); } catch(e){} }
      activateHttpMode();
    }
  }, 4000);

  ws.onopen = () => {
    clearTimeout(wsConnectTimeout);
    useHttpFallback = false;
    setOnline();
    reconnectAttempts = 0;
  };
  ws.onmessage = (event) => handleMessage(JSON.parse(event.data));
  ws.onclose = () => {
    clearTimeout(wsConnectTimeout);
    if (reconnectAttempts >= 3) { activateHttpMode(); return; }
    setOffline();
    reconnectBar.classList.add('active');
    setTimeout(() => { reconnectAttempts++; connectWS(); }, Math.min(1000 * reconnectAttempts, 5000));
  };
  ws.onerror = () => setOffline();
}

function activateHttpMode() {
  useHttpFallback = true; ws = null;
  setOnline('http');
}

function handleMessage(msg) {
  switch (msg.type) {
    case 'thinking_start': showThinking(); break;
    case 'thinking_end': hideThinking(); break;
    case 'text_delta': appendText(msg.content); break;
    case 'text_done': finishText(); break;
    case 'tool_call': showToolCall(msg.name, msg.args); break;
    case 'tool_result': showToolResult(msg.name, msg.status, msg.output); break;
    case 'turn_complete': finishTurn(); break;
    case 'error': showError(msg.content); break;
  }
}

function sendMessage() {
  const text = inputEl.value.trim();
  if (!text || isProcessing) return;
  if (useHttpFallback) { sendMessageHTTP(text); return; }
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  addUserMsg(text);
  ws.send(JSON.stringify({ type: 'message', content: text }));
  inputEl.value = ''; inputEl.style.height = 'auto';
  isProcessing = true; sendBtn.disabled = true;
}

async function sendMessageHTTP(text) {
  addUserMsg(text);
  inputEl.value = ''; inputEl.style.height = 'auto';
  isProcessing = true; sendBtn.disabled = true;
  showThinking();
  try {
    const resp = await fetch('/api/v1/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: text, session_id: httpSessionId }),
    });
    hideThinking();
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ error: 'Erro de conexao' }));
      showError(err.error || 'Erro no servidor'); finishTurn(); return;
    }
    const data = await resp.json();
    httpSessionId = data.session_id || httpSessionId;
    if (data.tools && data.tools.length > 0) {
      for (const t of data.tools) { showToolCall(t.name, t.args); showToolResult(t.name, t.status, t.output || ''); }
    }
    if (data.response) { appendText(data.response); finishText(); }
    if (data.file) { showFileCard(data.file); }
    finishTurn();
  } catch (e) { hideThinking(); showError('Erro: ' + e.message); finishTurn(); }
}

function now() {
  return new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
}

function addUserMsg(text) {
  hideWelcome();
  const div = document.createElement('div');
  div.className = 'msg-line user';
  div.innerHTML = `
    <div class="msg-header">
      <div class="msg-avatar">vc</div>
      <span class="msg-name">voce</span>
      <span class="msg-time">${now()}</span>
    </div>
    <div class="msg-body">${esc(text)}</div>`;
  terminal.appendChild(div);
  scrollEnd();
}

function showThinking() {
  hideThinking();
  const div = document.createElement('div');
  div.className = 'thinking-block';
  div.id = 'thinkingEl';
  div.innerHTML = `
    <div class="shimmer"></div>
    <div class="thinking-inner">
      <div class="infinity-spinner">${SPINNER_SVG}</div>
      <span class="thinking-label">Processando<span class="thinking-dots"></span></span>
    </div>`;
  terminal.appendChild(div);
  scrollEnd();
}

function hideThinking() {
  const el = document.getElementById('thinkingEl');
  if (el) el.remove();
}

function ensureMsgEl() {
  if (!currentMsgEl) {
    hideThinking();
    rawTextBuffer = '';
    currentMsgEl = document.createElement('div');
    currentMsgEl.className = 'msg-line assistant';
    currentMsgEl.innerHTML = `
      <div class="msg-header">
        <div class="msg-avatar">${INFINITY_SVG}</div>
        <span class="msg-name">clow</span>
        <span class="msg-time">${now()}</span>
      </div>`;
    currentBodyEl = document.createElement('div');
    currentBodyEl.className = 'msg-body';
    currentMsgEl.appendChild(currentBodyEl);
    terminal.appendChild(currentMsgEl);
  }
}

let rawTextBuffer = '';

function appendText(text) {
  ensureMsgEl();
  rawTextBuffer += text;
  const old = currentBodyEl.querySelector('.stream-cursor');
  if (old) old.remove();
  currentBodyEl.insertAdjacentText('beforeend', text);
  const c = document.createElement('span');
  c.className = 'stream-cursor';
  currentBodyEl.appendChild(c);
  scrollEnd();
}

function finishText() {
  if (currentBodyEl) {
    const c = currentBodyEl.querySelector('.stream-cursor');
    if (c) c.remove();
    if (rawTextBuffer && typeof marked !== 'undefined') {
      marked.setOptions({ breaks: true, gfm: true });
      currentBodyEl.innerHTML = marked.parse(rawTextBuffer);
      // Open links in new tab
      currentBodyEl.querySelectorAll('a').forEach(a => { a.target = '_blank'; a.rel = 'noopener'; });
    }
    rawTextBuffer = '';
  }
}

function showToolCall(name, args) {
  ensureMsgEl();
  const block = document.createElement('div');
  block.className = 'tool-block active';
  const argsStr = typeof args === 'string' ? args : JSON.stringify(args, null, 2);
  block.innerHTML = `
    <div class="tool-head" onclick="this.parentElement.classList.toggle('open')">
      <span class="tool-icon spinning">&#x2699;</span>
      <span class="tool-label">${esc(name)}</span>
      <span class="tool-dur">0.0s</span>
    </div>
    <div class="tool-output"><pre>${esc(argsStr).substring(0, 500)}</pre></div>`;
  currentMsgEl.appendChild(block);
  currentToolEl = block;
  toolStartTime = Date.now();
  if (toolTimer) clearInterval(toolTimer);
  toolTimer = setInterval(() => {
    if (!currentToolEl) { clearInterval(toolTimer); return; }
    const dur = currentToolEl.querySelector('.tool-dur');
    if (dur) dur.textContent = ((Date.now() - toolStartTime) / 1000).toFixed(1) + 's';
  }, 100);
  scrollEnd();
}

function showToolResult(name, status, output) {
  if (toolTimer) { clearInterval(toolTimer); toolTimer = null; }
  if (currentToolEl) {
    currentToolEl.classList.remove('active');
    const icon = currentToolEl.querySelector('.tool-icon');
    if (icon) {
      icon.classList.remove('spinning');
      if (status === 'success') { icon.textContent = '\u2713'; icon.style.color = 'var(--green)'; }
      else if (status === 'error') { icon.textContent = '\u2717'; icon.style.color = 'var(--red)'; }
      else { icon.textContent = '\u25cb'; icon.style.color = 'var(--purple)'; }
    }
    if (output) {
      const body = currentToolEl.querySelector('.tool-output');
      if (body) body.innerHTML += `<pre style="margin-top:4px;color:${status==='error'?'var(--red)':'var(--text-secondary)'}">${esc(output).substring(0, 1000)}</pre>`;
    }
    const dur = currentToolEl.querySelector('.tool-dur');
    if (dur) dur.textContent = ((Date.now() - toolStartTime) / 1000).toFixed(1) + 's';
    currentToolEl = null;
  }
  scrollEnd();
}

function showFileCard(file) {
  ensureMsgEl();
  const icons = {
    'landing_page': '\ud83c\udf10', 'app': '\u26a1', 'xlsx': '\ud83d\udcca',
    'docx': '\ud83d\udcc4', 'pptx': '\ud83d\udcfd\ufe0f',
  };
  const icon = icons[file.type] || '\ud83d\udcc1';
  const isWeb = file.type === 'landing_page' || file.type === 'app';
  const card = document.createElement('div');
  card.className = 'file-card';
  card.innerHTML = `
    <div class="file-icon">${icon}</div>
    <div class="file-info">
      <div class="file-name">${esc(file.name)}</div>
      <div class="file-meta">${esc(file.size)}</div>
    </div>
    <div class="file-actions">
      ${isWeb ? `<a href="${esc(file.url)}" target="_blank" rel="noopener" class="file-btn primary">Abrir</a>` : ''}
      <a href="${esc(file.url)}" download class="file-btn ${isWeb ? 'secondary' : 'primary'}">Download</a>
    </div>`;
  currentMsgEl.appendChild(card);
  scrollEnd();
}

function showError(text) {
  ensureMsgEl();
  const e = document.createElement('div');
  e.className = 'error-line';
  e.textContent = '\u2717 ' + text;
  currentMsgEl.appendChild(e);
  scrollEnd();
}

function finishTurn() {
  finishText();
  isProcessing = false;
  sendBtn.disabled = false;
  currentMsgEl = null;
  currentBodyEl = null;
  inputEl.focus();
}

function scrollEnd() { terminal.scrollTop = terminal.scrollHeight; }

function esc(t) {
  const d = document.createElement('div');
  d.textContent = t;
  return d.innerHTML;
}

// Input
inputEl.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});
inputEl.addEventListener('input', () => {
  inputEl.style.height = 'auto';
  inputEl.style.height = Math.min(inputEl.scrollHeight, 100) + 'px';
});

// Prevent zoom on double tap
let lastTouchEnd = 0;
document.addEventListener('touchend', (e) => {
  const now = Date.now();
  if (now - lastTouchEnd <= 300) e.preventDefault();
  lastTouchEnd = now;
}, false);

function quickAction(text) {
  if (text.startsWith('/')) {
    inputEl.value = text;
    sendMessage();
  } else {
    inputEl.value = text;
    inputEl.focus();
  }
}

function hideWelcome() {
  const w = document.getElementById('welcomeBlock');
  if (w) w.style.display = 'none';
}

// Init
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
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="theme-color" content="#0a0a0f">
<title>Clow — Dashboard</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&display=swap');

  :root {
    --bg-deep: #06060b;
    --bg-primary: #0a0a0f;
    --bg-secondary: #111118;
    --bg-tertiary: #16161f;
    --bg-surface: #1a1a25;
    --bg-elevated: #1e1e2a;
    --text-primary: #f0f0f5;
    --text-secondary: #9d9db5;
    --text-muted: #55556a;
    --purple: #a78bfa;
    --purple-bright: #c4b5fd;
    --purple-dim: #7c3aed;
    --purple-deep: #5b21b6;
    --purple-glow: rgba(167,139,250,0.15);
    --violet: #8b5cf6;
    --green: #34d399;
    --green-dim: rgba(52,211,153,0.15);
    --red: #f87171;
    --red-dim: rgba(248,113,113,0.15);
    --amber: #fbbf24;
    --amber-dim: rgba(251,191,36,0.15);
    --blue: #60a5fa;
    --blue-dim: rgba(96,165,250,0.15);
    --border: rgba(167,139,250,0.12);
    --border-focus: rgba(167,139,250,0.4);
    --font-mono: "JetBrains Mono", "Fira Code", "Cascadia Code", "SF Mono", monospace;
    --safe-top: env(safe-area-inset-top, 0px);
  }

  * { margin: 0; padding: 0; box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
  html { height: 100%; }

  body {
    background: var(--bg-deep);
    color: var(--text-primary);
    font-family: var(--font-mono);
    font-size: 13px;
    line-height: 1.65;
    min-height: 100%;
    -webkit-font-smoothing: antialiased;
  }

  /* ── Title Bar ── */
  .title-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 20px;
    padding-top: var(--safe-top);
    background: var(--bg-primary);
    border-bottom: 1px solid var(--border);
    height: calc(52px + var(--safe-top));
    position: sticky;
    top: 0;
    z-index: 10;
    backdrop-filter: blur(12px);
  }
  .title-left { display: flex; align-items: center; gap: 10px; }
  .logo-infinity { width: 28px; height: 28px; flex-shrink: 0; }
  .logo-infinity path {
    fill: none; stroke: var(--purple); stroke-width: 3;
    stroke-linecap: round; stroke-linejoin: round;
  }
  .logo-text {
    font-size: 20px; font-weight: 700; letter-spacing: 2px;
    background: linear-gradient(135deg, var(--purple-bright) 0%, var(--purple) 50%, var(--violet) 100%);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    background-clip: text; text-transform: uppercase;
  }
  .title-right { display: flex; align-items: center; gap: 10px; }
  .nav-pill {
    background: var(--bg-tertiary); border: 1px solid var(--border);
    color: var(--text-secondary); font-family: var(--font-mono);
    font-size: 10px; font-weight: 500; padding: 5px 12px;
    border-radius: 6px; cursor: pointer; text-decoration: none;
    transition: all 0.2s; letter-spacing: 0.3px;
  }
  .nav-pill:hover, .nav-pill:active { background: var(--bg-surface); color: var(--purple); border-color: var(--border-focus); }
  .nav-pill.active { background: var(--purple-glow); color: var(--purple); border-color: var(--border-focus); }

  /* ── Dashboard Body ── */
  .dash {
    max-width: 1100px;
    margin: 0 auto;
    padding: 24px 20px 40px;
  }

  .dash-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 24px;
  }
  .dash-title {
    font-size: 16px;
    font-weight: 600;
    color: var(--text-primary);
    letter-spacing: 0.5px;
  }
  .refresh-tag {
    font-size: 10px;
    color: var(--text-muted);
    background: var(--bg-tertiary);
    padding: 3px 10px;
    border-radius: 4px;
    border: 1px solid var(--border);
  }

  /* ── Cards ── */
  .cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: 14px;
    margin-bottom: 32px;
  }
  .card {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
    transition: border-color 0.2s;
  }
  .card:hover { border-color: var(--border-focus); }
  .card-label {
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: var(--text-muted);
    margin-bottom: 10px;
  }
  .card-value {
    font-size: 36px;
    font-weight: 700;
    background: linear-gradient(135deg, var(--purple-bright), var(--purple));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    line-height: 1;
  }
  .card-value .unit {
    font-size: 14px;
    -webkit-text-fill-color: var(--text-muted);
  }
  .card-detail {
    margin-top: 8px;
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }
  .badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 0.3px;
  }
  .badge.ok { background: var(--green-dim); color: var(--green); }
  .badge.warn { background: var(--red-dim); color: var(--red); }
  .badge.info { background: var(--blue-dim); color: var(--blue); }
  .badge.purple { background: var(--purple-glow); color: var(--purple); }

  /* ── Section Headers ── */
  .section-title {
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: var(--purple);
    margin-bottom: 12px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border);
  }

  /* ── Tables ── */
  .table-wrap {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 12px;
    overflow: hidden;
    margin-bottom: 28px;
  }
  table { width: 100%; border-collapse: collapse; }
  th {
    background: var(--bg-tertiary);
    color: var(--text-muted);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    text-align: left;
    padding: 10px 14px;
  }
  td {
    padding: 8px 14px;
    border-top: 1px solid var(--border);
    font-size: 12px;
    color: var(--text-primary);
  }
  tr:hover td { background: var(--bg-tertiary); }
  .s-ok { color: var(--green); }
  .s-err { color: var(--red); }
  .s-run { color: var(--blue); }
  .s-muted { color: var(--text-muted); }

  /* ── Responsive ── */
  @media (max-width: 600px) {
    .cards { grid-template-columns: repeat(2, 1fr); gap: 10px; }
    .card { padding: 14px; }
    .card-value { font-size: 28px; }
    .dash { padding: 16px 14px 32px; }
    .table-wrap { overflow-x: auto; }
    th, td { padding: 6px 10px; white-space: nowrap; }
  }
</style>
</head>
<body>

<!-- Title Bar -->
<div class="title-bar">
  <div class="title-left">
    <svg class="logo-infinity" viewBox="0 0 32 32">
      <path d="M8 16c0-3 2-6 5-6s5 3 8 6c3 3 5 6 8 6s5-3 5-6-2-6-5-6-5 3-8 6c-3 3-5 6-8 6s-5-3-5-6z" transform="translate(-5,0) scale(0.95)"/>
    </svg>
    <span class="logo-text">Clow</span>
  </div>
  <div class="title-right">
    <a href="/" class="nav-pill">terminal</a>
    <a href="/dashboard" class="nav-pill active">dashboard</a>
    <a href="/logout" class="nav-pill" style="color:var(--red);border-color:rgba(248,113,113,0.2)">sair</a>
  </div>
</div>

<div class="dash">
  <div class="dash-header">
    <span class="dash-title">System Overview</span>
    <span class="refresh-tag">auto-refresh 10s &middot; <span id="lastUpdate">--:--</span></span>
  </div>

  <div class="cards" id="cards">
    <div class="card"><div class="card-label">carregando</div><div class="card-value">...</div></div>
  </div>

  <div class="section-title">Cron Jobs</div>
  <div class="table-wrap">
    <table>
      <thead><tr><th>ID</th><th>Prompt</th><th>Intervalo</th><th>Status</th><th>Runs</th><th>Proxima</th></tr></thead>
      <tbody id="cronBody"><tr><td colspan="6" class="s-muted">Carregando...</td></tr></tbody>
    </table>
  </div>

  <div class="section-title">Acoes Recentes</div>
  <div class="table-wrap">
    <table>
      <thead><tr><th>Hora</th><th>Acao</th><th>Detalhes</th><th>Status</th></tr></thead>
      <tbody id="actionsBody"><tr><td colspan="4" class="s-muted">Carregando...</td></tr></tbody>
    </table>
  </div>
</div>

<script>
async function refresh() {
  try {
    const r = await fetch('/health');
    const d = await r.json();
    document.getElementById('lastUpdate').textContent = new Date().toLocaleTimeString('pt-BR', {hour:'2-digit',minute:'2-digit',second:'2-digit'});

    const c = d.components;
    document.getElementById('cards').innerHTML = `
      <div class="card">
        <div class="card-label">Tasks</div>
        <div class="card-value">${c.tasks.total}</div>
        <div class="card-detail">${Object.entries(c.tasks.by_status).map(([k,v])=>`<span class="badge ${k==='completed'?'ok':k==='failed'?'warn':'info'}">${k}: ${v}</span>`).join('')}</div>
      </div>
      <div class="card">
        <div class="card-label">Cron Jobs</div>
        <div class="card-value">${c.cron.active_jobs}<span class="unit"> / ${c.cron.total_jobs}</span></div>
        <div class="card-detail"><span class="badge purple">ativos</span></div>
      </div>
      <div class="card">
        <div class="card-label">Memoria</div>
        <div class="card-value">${c.memory.total}</div>
        <div class="card-detail">${Object.entries(c.memory.by_type).map(([k,v])=>`<span class="badge purple">${k}: ${v}</span>`).join('')}</div>
      </div>
      <div class="card">
        <div class="card-label">Triggers</div>
        <div class="card-value">${c.triggers.results_count}</div>
        <div class="card-detail">${c.triggers.running?'<span class="badge ok">online :'+c.triggers.port+'</span>':'<span class="badge warn">offline</span>'}</div>
      </div>`;

    const cronBody = document.getElementById('cronBody');
    if (c.cron.jobs.length === 0) {
      cronBody.innerHTML = '<tr><td colspan="6" class="s-muted">Nenhum cron job</td></tr>';
    } else {
      cronBody.innerHTML = c.cron.jobs.map(j => {
        const next = new Date(j.next_run * 1000).toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'});
        return `<tr>
          <td style="color:var(--purple)">${j.id}</td>
          <td>${j.prompt}</td>
          <td><span class="badge purple">${j.interval}</span></td>
          <td class="${j.active?'s-ok':'s-err'}">${j.active?'ativo':'pausado'}</td>
          <td>${j.run_count}x</td>
          <td class="s-muted">${next}</td>
        </tr>`;
      }).join('');
    }

    const actionsBody = document.getElementById('actionsBody');
    const actions = d.recent_actions || [];
    if (actions.length === 0) {
      actionsBody.innerHTML = '<tr><td colspan="4" class="s-muted">Nenhuma acao recente</td></tr>';
    } else {
      actionsBody.innerHTML = actions.reverse().map(a => {
        const t = new Date(a.timestamp * 1000).toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
        return `<tr>
          <td class="s-muted">${t}</td>
          <td>${a.action}</td>
          <td style="color:var(--text-secondary)">${a.details}</td>
          <td class="${a.status==='ok'?'s-ok':'s-err'}">${a.status}</td>
        </tr>`;
      }).join('');
    }
  } catch(e) {
    document.getElementById('cards').innerHTML = `<div class="card"><div class="card-label" style="color:var(--red)">Erro</div><div class="card-detail">${e.message}</div></div>`;
  }
}
refresh();
setInterval(refresh, 10000);
</script>
</body>
</html>
'''


LOGIN_HTML = r'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="theme-color" content="#0a0a0f">
<title>Clow — Login</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&display=swap');
  :root {
    --bg-deep: #06060b;
    --bg-primary: #0a0a0f;
    --bg-secondary: #111118;
    --bg-tertiary: #16161f;
    --text-primary: #f0f0f5;
    --text-secondary: #9d9db5;
    --text-muted: #55556a;
    --purple: #a78bfa;
    --purple-bright: #c4b5fd;
    --purple-dim: #7c3aed;
    --violet: #8b5cf6;
    --red: #f87171;
    --red-dim: rgba(248,113,113,0.15);
    --green: #34d399;
    --border: rgba(167,139,250,0.12);
    --border-focus: rgba(167,139,250,0.4);
    --purple-glow: rgba(167,139,250,0.15);
    --font-mono: "JetBrains Mono", "Fira Code", "Cascadia Code", "SF Mono", monospace;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
  html, body {
    height: 100%; background: var(--bg-deep); font-family: var(--font-mono);
    display: flex; justify-content: center; align-items: center;
    -webkit-font-smoothing: antialiased;
  }
  .login-card {
    width: 100%; max-width: 380px; padding: 24px;
  }
  .logo-area {
    text-align: center; margin-bottom: 36px;
  }
  .logo-infinity {
    width: 52px; height: 52px; margin: 0 auto 16px;
  }
  .logo-infinity path {
    fill: none; stroke: var(--purple); stroke-width: 2.5;
    stroke-linecap: round; stroke-dasharray: 120;
    animation: trace 3s ease-in-out infinite;
  }
  @keyframes trace {
    0% { stroke-dashoffset: 0; stroke: var(--purple); }
    50% { stroke-dashoffset: 120; stroke: var(--purple-bright); }
    100% { stroke-dashoffset: 240; stroke: var(--purple); }
  }
  .logo-text {
    font-size: 28px; font-weight: 700; letter-spacing: 3px; text-transform: uppercase;
    background: linear-gradient(135deg, var(--purple-bright) 0%, var(--purple) 50%, var(--violet) 100%);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
  }
  .logo-sub {
    font-size: 11px; color: var(--text-muted); margin-top: 6px; letter-spacing: 0.5px;
  }
  .form-group {
    margin-bottom: 16px;
  }
  .form-label {
    display: block; font-size: 10px; font-weight: 600; letter-spacing: 0.8px;
    text-transform: uppercase; color: var(--text-muted); margin-bottom: 6px;
  }
  .form-input {
    width: 100%; padding: 12px 14px;
    background: var(--bg-secondary); border: 1px solid var(--border);
    border-radius: 10px; color: var(--text-primary);
    font-family: var(--font-mono); font-size: 14px;
    outline: none; transition: border-color 0.2s, box-shadow 0.2s;
  }
  .form-input:focus {
    border-color: var(--border-focus);
    box-shadow: 0 0 0 3px var(--purple-glow);
  }
  .form-input::placeholder { color: var(--text-muted); font-size: 13px; }
  .login-btn {
    width: 100%; padding: 14px; margin-top: 8px;
    background: linear-gradient(135deg, var(--purple-dim), var(--violet));
    border: none; border-radius: 12px; color: white;
    font-family: var(--font-mono); font-size: 14px; font-weight: 600;
    cursor: pointer; letter-spacing: 0.5px;
    transition: transform 0.15s, box-shadow 0.2s;
  }
  .login-btn:active { transform: scale(0.97); }
  .login-btn:hover { box-shadow: 0 4px 20px rgba(167,139,250,0.3); }
  .error-msg {
    margin-top: 16px; padding: 10px 14px; border-radius: 8px;
    background: var(--red-dim); border: 1px solid rgba(248,113,113,0.25);
    color: var(--red); font-size: 12px; text-align: center;
    display: none;
  }
  .error-msg.show { display: block; }
</style>
</head>
<body>
<div class="login-card">
  <div class="logo-area">
    <svg class="logo-infinity" viewBox="0 0 32 32">
      <path d="M8 16c0-3 2-6 5-6s5 3 8 6c3 3 5 6 8 6s5-3 5-6-2-6-5-6-5 3-8 6c-3 3-5 6-8 6s-5-3-5-6z" transform="translate(-5,0) scale(0.95)"/>
    </svg>
    <div class="logo-text">Clow</div>
    <div class="logo-sub">Acesso ao Sistema</div>
  </div>
  <form method="POST" action="/login">
    <div class="form-group">
      <label class="form-label">Email</label>
      <input class="form-input" type="email" name="email" placeholder="seu@email.com" required autofocus>
    </div>
    <div class="form-group">
      <label class="form-label">Senha</label>
      <input class="form-input" type="password" name="password" placeholder="********" required>
    </div>
    <button class="login-btn" type="submit">Entrar</button>
  </form>
  <div class="error-msg __ERROR_CLASS__">__ERROR_MSG__</div>
  <div style="text-align:center;margin-top:20px;font-size:11px;color:var(--text-muted)">
    Nao tem conta? <a href="/register" style="color:var(--purple);text-decoration:none;font-weight:600">Criar conta</a>
  </div>
</div>
</body>
</html>
'''


ADMIN_HTML = r'''<!DOCTYPE html>
<html lang="pt-BR"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<meta name="theme-color" content="#0a0a0f"><title>Clow Admin</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&display=swap');
:root{--bg:#06060b;--s1:#0a0a0f;--s2:#111118;--s3:#16161f;--t1:#f0f0f5;--t2:#9d9db5;--tm:#55556a;--p:#a78bfa;--pb:#c4b5fd;--pd:#7c3aed;--g:#34d399;--r:#f87171;--b:rgba(167,139,250,.12);--bf:rgba(167,139,250,.4);--f:"JetBrains Mono",monospace}
*{margin:0;padding:0;box-sizing:border-box}body{background:var(--bg);color:var(--t1);font-family:var(--f);font-size:13px}
.bar{display:flex;align-items:center;justify-content:space-between;padding:0 20px;background:var(--s1);border-bottom:1px solid var(--b);height:52px;position:sticky;top:0;z-index:10}
.logo{font-size:20px;font-weight:700;letter-spacing:2px;background:linear-gradient(135deg,var(--pb),var(--p));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.nav a{color:var(--t2);font-size:10px;text-decoration:none;padding:5px 10px;border:1px solid var(--b);border-radius:6px;margin-left:8px}
.nav a:hover{color:var(--p);border-color:var(--bf)}
.wrap{max-width:900px;margin:0 auto;padding:24px 16px}
.row{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:28px}
.stat{background:var(--s2);border:1px solid var(--b);border-radius:12px;padding:16px}
.stat-label{font-size:10px;font-weight:600;letter-spacing:.8px;text-transform:uppercase;color:var(--tm);margin-bottom:8px}
.stat-val{font-size:28px;font-weight:700;background:linear-gradient(135deg,var(--pb),var(--p));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.stat-sub{font-size:10px;color:var(--tm);margin-top:4px}
.sec{font-size:12px;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:var(--p);margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid var(--b)}
.tbl{width:100%;background:var(--s2);border:1px solid var(--b);border-radius:12px;overflow:hidden;margin-bottom:24px}
table{width:100%;border-collapse:collapse}
th{background:var(--s3);color:var(--tm);font-size:10px;font-weight:600;letter-spacing:.5px;text-transform:uppercase;text-align:left;padding:10px 12px}
td{padding:8px 12px;border-top:1px solid var(--b);font-size:12px}
.badge{padding:2px 8px;border-radius:4px;font-size:10px;font-weight:500}
.badge.g{background:rgba(52,211,153,.15);color:var(--g)}.badge.r{background:rgba(248,113,113,.15);color:var(--r)}
.badge.p{background:rgba(167,139,250,.15);color:var(--p)}
select,button{background:var(--s3);border:1px solid var(--b);color:var(--t1);font-family:var(--f);font-size:11px;padding:4px 8px;border-radius:4px;cursor:pointer}
button:hover{border-color:var(--bf);color:var(--p)}
</style></head><body>
<div class="bar"><span class="logo">CLOW ADMIN</span><div class="nav"><a href="/">Terminal</a><a href="/dashboard">Dashboard</a><a href="/logout">Sair</a></div></div>
<div class="wrap">
<div class="row" id="stats"></div>
<div class="sec">Usuarios</div>
<div class="tbl"><table><thead><tr><th>Email</th><th>Plano</th><th>Status</th><th>Criado</th><th>Acao</th></tr></thead><tbody id="usersBody"></tbody></table></div>
<div class="sec">Top Consumo (Hoje)</div>
<div class="tbl"><table><thead><tr><th>Email</th><th>Plano</th><th>Tokens</th><th>Custo</th></tr></thead><tbody id="topBody"></tbody></table></div>
</div>
<script>
async function load(){
  const [sr,ur]=await Promise.all([fetch('/api/v1/admin/stats').then(r=>r.json()),fetch('/api/v1/admin/users').then(r=>r.json())]);
  document.getElementById('stats').innerHTML=`
    <div class="stat"><div class="stat-label">Usuarios</div><div class="stat-val">${sr.total_users}</div><div class="stat-sub">${sr.active_users} ativos</div></div>
    <div class="stat"><div class="stat-label">Custo Hoje</div><div class="stat-val">$${sr.cost_today.toFixed(3)}</div></div>
    <div class="stat"><div class="stat-label">Custo Semana</div><div class="stat-val">$${sr.cost_week.toFixed(3)}</div></div>
    <div class="stat"><div class="stat-label">Custo Mes</div><div class="stat-val">$${sr.cost_month.toFixed(3)}</div></div>
    <div class="stat"><div class="stat-label">Tokens Hoje</div><div class="stat-val">${(sr.tokens_today/1000).toFixed(0)}k</div></div>`;
  const ub=document.getElementById('usersBody');
  ub.innerHTML=ur.users.map(u=>{
    const dt=new Date(u.created_at*1000).toLocaleDateString('pt-BR');
    const st=u.active?'<span class="badge g">ativo</span>':'<span class="badge r">inativo</span>';
    return `<tr><td>${u.email}</td><td><select onchange="setPlan('${u.id}',this.value)">${['free','basic','pro','unlimited'].map(p=>`<option ${u.plan===p?'selected':''}>${p}</option>`).join('')}</select></td><td>${st}</td><td style="color:var(--tm)">${dt}</td><td><button onclick="toggle('${u.id}',${u.active?0:1})">${u.active?'Desativar':'Ativar'}</button></td></tr>`;
  }).join('');
  const tb=document.getElementById('topBody');
  tb.innerHTML=(sr.top_users_today||[]).map(u=>`<tr><td>${u.email}</td><td><span class="badge p">${u.plan}</span></td><td>${(u.tokens/1000).toFixed(0)}k</td><td>$${u.cost.toFixed(4)}</td></tr>`).join('')||'<tr><td colspan="4" style="color:var(--tm)">Sem dados</td></tr>';
}
async function setPlan(id,plan){await fetch(`/api/v1/admin/users/${id}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({plan})});load();}
async function toggle(id,active){await fetch(`/api/v1/admin/users/${id}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({active})});load();}
load();setInterval(load,30000);
</script></body></html>
'''


if HAS_FASTAPI:
    # ── Login routes (sem auth) ──────────────────────────────────
    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        if _get_session_from_request(request):
            return RedirectResponse("/", status_code=302)
        html = LOGIN_HTML.replace("__ERROR_CLASS__", "").replace("__ERROR_MSG__", "")
        return HTMLResponse(html)

    @app.post("/login")
    async def login_submit(request: Request):
        form = await request.form()
        email = form.get("email", "").strip().lower()
        password = form.get("password", "")

        user = authenticate_user(email, password)
        if user:
            token = _create_session(user)
            resp = RedirectResponse("/", status_code=302)
            resp.set_cookie(
                "clow_session", token,
                max_age=_SESSION_TTL, httponly=True,
                samesite="lax", secure=False,
            )
            return resp

        html = LOGIN_HTML.replace("__ERROR_CLASS__", "show").replace("__ERROR_MSG__", "Email ou senha incorretos")
        return HTMLResponse(html, status_code=401)

    @app.get("/register", response_class=HTMLResponse)
    async def register_page(request: Request):
        if _get_session_from_request(request):
            return RedirectResponse("/", status_code=302)
        html = LOGIN_HTML.replace("Acesso ao Sistema", "Criar Conta")
        html = html.replace('action="/login"', 'action="/register"')
        html = html.replace("Entrar", "Criar Conta")
        html = html.replace("__ERROR_CLASS__", "").replace("__ERROR_MSG__", "")
        html = html.replace("</form>", '<div style="text-align:center;margin-top:16px;font-size:11px;color:var(--text-muted)">Ja tem conta? <a href="/login" style="color:var(--purple)">Entrar</a></div></form>')
        return HTMLResponse(html)

    @app.post("/register")
    async def register_submit(request: Request):
        form = await request.form()
        email = form.get("email", "").strip().lower()
        password = form.get("password", "")

        if len(password) < 6:
            html = LOGIN_HTML.replace("Acesso ao Sistema", "Criar Conta").replace('action="/login"', 'action="/register"').replace("Entrar", "Criar Conta")
            html = html.replace("__ERROR_CLASS__", "show").replace("__ERROR_MSG__", "Senha deve ter no minimo 6 caracteres")
            return HTMLResponse(html, status_code=400)

        user = create_user(email, password)
        if not user:
            html = LOGIN_HTML.replace("Acesso ao Sistema", "Criar Conta").replace('action="/login"', 'action="/register"').replace("Entrar", "Criar Conta")
            html = html.replace("__ERROR_CLASS__", "show").replace("__ERROR_MSG__", "Email ja cadastrado")
            return HTMLResponse(html, status_code=400)

        # Auto-login
        full_user = get_user_by_email(email)
        token = _create_session(full_user)
        resp = RedirectResponse("/", status_code=302)
        resp.set_cookie("clow_session", token, max_age=_SESSION_TTL, httponly=True, samesite="lax", secure=False)
        return resp

    @app.get("/logout")
    async def logout(request: Request):
        token = request.cookies.get("clow_session", "")
        if token in _web_sessions:
            del _web_sessions[token]
        resp = RedirectResponse("/login", status_code=302)
        resp.delete_cookie("clow_session")
        return resp

    # ── Protected routes ─────────────────────────────────────────
    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        if not _get_session_from_request(request):
            return RedirectResponse("/login", status_code=302)
        return WEBAPP_HTML

    # ── PWA Routes (System Clow App) ──────────────────────────────
    @app.get("/pwa", response_class=HTMLResponse)
    async def pwa_index():
        """Página principal do PWA."""
        static_dir = Path(__file__).parent.parent / "static"
        if (static_dir / "index.html").exists():
            with open(static_dir / "index.html") as f:
                return f.read()
        return HTMLResponse("<h1>System Clow</h1><p>PWA app</p>")

    @app.get("/static/manifest.json")
    async def manifest():
        """Manifest do PWA."""
        static_dir = Path(__file__).parent.parent / "static"
        manifest_path = static_dir / "manifest.json"
        if manifest_path.exists():
            return FileResponse(manifest_path, media_type="application/manifest+json")
        return JSONResponse({"name": "System Clow", "short_name": "Clow"})

    @app.get("/static/service-worker.js")
    async def service_worker():
        """Service Worker para PWA."""
        static_dir = Path(__file__).parent.parent / "static"
        sw_path = static_dir / "service-worker.js"
        if sw_path.exists():
            return FileResponse(sw_path, media_type="application/javascript")
        return JSONResponse({"error": "Service Worker not found"}, status_code=404)

    @app.get("/static/{file_path:path}")
    async def static_files(file_path: str):
        """Serve arquivos estáticos (CSS, JS, imagens, etc)."""
        static_dir = Path(__file__).parent.parent / "static"
        full_path = (static_dir / file_path).resolve()
        
        # Security: previne path traversal
        if not str(full_path).startswith(str(static_dir)):
            return JSONResponse({"error": "Forbidden"}, status_code=403)
        
        if full_path.exists() and full_path.is_file():
            return FileResponse(full_path)
        return JSONResponse({"error": "Not found"}, status_code=404)

    # Feature #24: Dashboard (protegido por login)
    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard(request: Request):
        if not _get_session_from_request(request):
            return RedirectResponse("/login", status_code=302)
        return DASHBOARD_HTML

    # Admin panel (so admin)
    @app.get("/admin", response_class=HTMLResponse)
    async def admin_panel(request: Request):
        sess = _get_user_session(request)
        if not sess or not sess.get("is_admin"):
            return RedirectResponse("/login", status_code=302)
        return HTMLResponse(ADMIN_HTML)

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

    # ── API: Conversations ──────────────────────────────────────────

    @app.get("/api/v1/conversations")
    async def api_conversations(request: Request):
        sess = _get_user_session(request)
        if not sess:
            return JSONResponse({"error": "Nao autenticado"}, status_code=401)
        convs = list_conversations(sess["user_id"])
        return JSONResponse({"conversations": convs})

    @app.post("/api/v1/conversations")
    async def api_create_conversation(request: Request):
        sess = _get_user_session(request)
        if not sess:
            return JSONResponse({"error": "Nao autenticado"}, status_code=401)
        cid = create_conversation(sess["user_id"])
        return JSONResponse({"id": cid})

    @app.get("/api/v1/conversations/{conv_id}/messages")
    async def api_get_messages(conv_id: str, request: Request):
        sess = _get_user_session(request)
        if not sess:
            return JSONResponse({"error": "Nao autenticado"}, status_code=401)
        msgs = get_messages(conv_id)
        return JSONResponse({"messages": msgs})

    @app.delete("/api/v1/conversations/{conv_id}")
    async def api_delete_conversation(conv_id: str, request: Request):
        sess = _get_user_session(request)
        if not sess:
            return JSONResponse({"error": "Nao autenticado"}, status_code=401)
        delete_conversation(sess["user_id"], conv_id)
        return JSONResponse({"ok": True})

    # ── API: Usage ───────────────────────────────────────────────────

    @app.get("/api/v1/usage")
    async def api_usage(request: Request):
        sess = _get_user_session(request)
        if not sess:
            return JSONResponse({"error": "Nao autenticado"}, status_code=401)
        usage = get_user_usage_today(sess["user_id"])
        plan = PLANS.get(sess.get("plan", "free"), PLANS["free"])
        return JSONResponse({
            "usage": usage,
            "plan": sess.get("plan", "free"),
            "plan_label": plan["label"],
            "daily_limit": plan["daily_tokens"],
        })

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

    # ── HTTP Chat Fallback (para mobile sem WebSocket) ────────────
    _http_sessions: dict[str, Any] = {}

    @app.post("/api/v1/chat", dependencies=[Depends(_rate_limit_dependency)])
    async def api_chat(request: Request):
        """Chat HTTP com deteccao automatica de geracao de arquivos."""
        sess = _get_user_session(request)
        if not sess:
            return JSONResponse({"error": "Nao autenticado"}, status_code=401)

        # Checa limite de uso
        allowed, pct = check_limit(sess["user_id"])
        if not allowed:
            return JSONResponse({
                "session_id": "",
                "response": "Voce atingiu seu limite diario de tokens. Volte amanha ou faca upgrade do seu plano.\n\nUse `/plan` para ver seu plano atual.",
                "tools": [], "file": None,
            })

        from .agent import Agent
        import uuid

        body = await request.json()
        content = body.get("content", "").strip()
        conv_id = body.get("conversation_id", "")
        session_id = body.get("session_id", "")

        if not content:
            return JSONResponse({"error": "content vazio"}, status_code=400)

        user_email = sess["email"]
        user_id = sess["user_id"]
        track_action("user_message_http", content[:60])

        # Salva mensagem do usuario no historico
        if conv_id:
            save_message(conv_id, "user", content)

        # ── Comandos internos ──
        if content.startswith("/"):
            cmd_lower = content.lower().strip()
            cmd_resp = None

            if cmd_lower == "/help":
                cmd_resp = (
                    "## Comandos Disponiveis\n\n"
                    "| Comando | Descricao |\n|---------|----------|\n"
                    "| `/connect` | Conectar servico externo |\n"
                    "| `/connections` | Ver conexoes ativas |\n"
                    "| `/disconnect X` | Desconectar servico |\n"
                    "| `/usage` | Ver consumo de tokens hoje |\n"
                    "| `/plan` | Ver plano atual e limites |\n"
                    "| `/help` | Esta lista de comandos |\n\n"
                    "**Geracao de arquivos:** peca naturalmente (ex: 'cria uma planilha de vendas')\n\n"
                    "**Integracoes:** pergunte direto (ex: 'mostra minhas campanhas meta ads')"
                )
            elif cmd_lower == "/usage":
                usage = get_user_usage_today(user_id)
                plan_info = PLANS.get(sess.get("plan", "free"), PLANS["free"])
                limit = plan_info["daily_tokens"]
                used = usage["total_tokens"]
                pct_str = f"{(used/limit*100):.0f}%" if limit > 0 else "ilimitado"
                cmd_resp = (
                    f"## Seu Consumo Hoje\n\n"
                    f"- Tokens usados: **{used:,}**\n"
                    f"- Limite diario: **{limit:,}** ({pct_str})\n"
                    f"- Requests: **{usage['requests']}**\n"
                    f"- Custo estimado: **${usage['total_cost']:.4f}**"
                )
            elif cmd_lower == "/plan":
                plan_info = PLANS.get(sess.get("plan", "free"), PLANS["free"])
                cmd_resp = (
                    f"## Seu Plano: {plan_info['label']}\n\n"
                    f"- Limite diario: **{plan_info['daily_tokens']:,} tokens**\n\n"
                    "**Planos disponiveis:**\n"
                    "| Plano | Tokens/dia |\n|-------|------------|\n"
                    "| Free | 50.000 |\n| Basic | 200.000 |\n| Pro | 1.000.000 |\n| Unlimited | Sem limite |"
                )

            if cmd_resp:
                if conv_id:
                    save_message(conv_id, "assistant", cmd_resp)
                return JSONResponse({
                    "session_id": session_id or str(uuid.uuid4())[:8],
                    "response": cmd_resp, "tools": [], "file": None,
                })

            # /connect, /disconnect, /connections
            from .integrations.command_handler import handle_command
            cmd_result = handle_command(content, user_email)
            if cmd_result:
                if conv_id:
                    save_message(conv_id, "assistant", cmd_result["response"])
                return JSONResponse({
                    "session_id": session_id or str(uuid.uuid4())[:8],
                    "response": cmd_result["response"],
                    "tools": [], "file": None,
                })

        # ── Detecta pedidos de integracao (meta ads, supabase, etc) ──
        from .integrations.command_handler import detect_integration_request
        int_result = detect_integration_request(content, user_email)
        if int_result:
            return JSONResponse({
                "session_id": session_id or str(uuid.uuid4())[:8],
                "response": int_result["response"],
                "tools": [],
                "file": None,
            })

        # ── Detecta geracao de arquivo ──
        from .generators.dispatcher import detect, run_generator
        gen_module, gen_type = detect(content)

        if gen_module:
            loop = asyncio.get_event_loop()
            try:
                result = await loop.run_in_executor(None, run_generator, gen_module, content)
                track_action("file_generated", f"{gen_type}: {result.get('name', '')}", "ok")

                if result.get("type") == "text":
                    return JSONResponse({
                        "session_id": session_id or str(uuid.uuid4())[:8],
                        "response": result["content"],
                        "tools": [],
                        "file": None,
                    })

                # Formata tamanho
                size_bytes = result.get("size", 0)
                if size_bytes > 1024 * 1024:
                    size_str = f"{size_bytes / (1024*1024):.1f} MB"
                elif size_bytes > 1024:
                    size_str = f"{size_bytes / 1024:.1f} KB"
                else:
                    size_str = f"{size_bytes} bytes"

                type_labels = {
                    "landing_page": "Landing Page",
                    "app": "Web App",
                    "xlsx": "Planilha Excel",
                    "docx": "Documento Word",
                    "pptx": "Apresentacao PowerPoint",
                }
                type_label = type_labels.get(result["type"], result["type"])
                msg = f"Pronto! Aqui esta seu arquivo:\n\n**{type_label}** — {result['name']} ({size_str})"

                return JSONResponse({
                    "session_id": session_id or str(uuid.uuid4())[:8],
                    "response": msg,
                    "tools": [],
                    "file": {
                        "type": result["type"],
                        "name": result["name"],
                        "url": result["url"],
                        "size": size_str,
                    },
                })
            except Exception as e:
                track_action("file_gen_error", str(e)[:60], "error")
                return JSONResponse({
                    "session_id": session_id or str(uuid.uuid4())[:8],
                    "response": f"Erro ao gerar arquivo: {str(e)}",
                    "tools": [],
                    "file": None,
                }, status_code=500)

        # ── Chat normal via Agent ──
        if session_id and session_id in _http_sessions:
            agent = _http_sessions[session_id]["agent"]
        else:
            session_id = str(uuid.uuid4())[:8]
            agent = Agent(cwd=os.getcwd(), auto_approve=True)
            _http_sessions[session_id] = {"agent": agent, "last_used": time.time()}

        _http_sessions[session_id]["last_used"] = time.time()

        now = time.time()
        stale = [k for k, v in _http_sessions.items() if now - v["last_used"] > 1800]
        for k in stale:
            del _http_sessions[k]

        loop = asyncio.get_event_loop()
        collected_text: list[str] = []
        tools_used: list[dict] = []

        def on_text_delta(delta: str):
            collected_text.append(delta)

        def on_tool_call(name: str, args: dict):
            tools_used.append({"name": name, "args": args, "status": "running", "output": ""})
            track_action("tool_call", name, "running")

        def on_tool_result(name: str, status: str, output: str):
            for t in tools_used:
                if t["name"] == name and t["status"] == "running":
                    t["status"] = status
                    t["output"] = output[:500]
                    break
            track_action("tool_result", f"{name}: {status}", status)

        agent.on_text_delta = on_text_delta
        agent.on_text_done = lambda t: None
        agent.on_tool_call = on_tool_call
        agent.on_tool_result = on_tool_result

        try:
            result = await loop.run_in_executor(None, agent.run_turn, content)
        except Exception as e:
            return JSONResponse({
                "session_id": session_id,
                "error": str(e),
            }, status_code=500)

        response_text = "".join(collected_text) if collected_text else (result or "")
        track_action("agent_response_http", response_text[:60] if response_text else "")

        return JSONResponse({
            "session_id": session_id,
            "response": response_text,
            "tools": tools_used,
            "file": None,
        })

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        # Verificacao de sessao via cookie para WebSocket
        ws_cookie = websocket.cookies.get("clow_session", "")
        if not _validate_session(ws_cookie):
            # Fallback: API key via query param
            api_key = websocket.query_params.get("api_key", "")
            keys = _get_api_keys()
            if keys and not _verify_api_key(api_key):
                await websocket.close(code=4001, reason="Nao autenticado")
                return
            elif not keys and not ws_cookie:
                await websocket.close(code=4001, reason="Nao autenticado")
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
