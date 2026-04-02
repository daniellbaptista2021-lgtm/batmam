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


# ── HTML/CSS/JS — SPA Completo ────────────────────────────────


WEBAPP_HTML = r'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no,viewport-fit=cover">
<meta name="theme-color" content="#0a0a0f">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<link rel="manifest" href="/static/manifest.json">
<title>Clow</title>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&display=swap');
:root{--bg:#06060b;--s1:#0a0a0f;--s2:#111118;--s3:#16161f;--s4:#1a1a25;--s5:#1e1e2a;--t1:#f0f0f5;--t2:#9d9db5;--tm:#55556a;--p:#a78bfa;--pb:#c4b5fd;--pd:#7c3aed;--pp:#5b21b6;--pg:rgba(167,139,250,.15);--pgs:rgba(167,139,250,.3);--v:#8b5cf6;--g:#34d399;--gd:rgba(52,211,153,.15);--r:#f87171;--rd:rgba(248,113,113,.15);--b:rgba(167,139,250,.12);--bf:rgba(167,139,250,.4);--f:"JetBrains Mono","Fira Code","SF Mono",monospace;--st:env(safe-area-inset-top,0px);--sb:env(safe-area-inset-bottom,0px);--sw:260px}
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html{height:100%;overflow:hidden}
body{background:var(--bg);color:var(--t1);font-family:var(--f);font-size:13px;height:100dvh;display:flex;overflow:hidden;-webkit-font-smoothing:antialiased}

/* SIDEBAR */
.sidebar{width:var(--sw);height:100%;background:var(--s1);border-right:1px solid var(--b);display:flex;flex-direction:column;flex-shrink:0;overflow:hidden;transition:transform .25s ease;z-index:30}
.sidebar-head{padding:16px;padding-top:calc(12px + var(--st));border-bottom:1px solid var(--b);display:flex;align-items:center;gap:10px}
.sb-logo{font-size:18px;font-weight:700;letter-spacing:2px;background:linear-gradient(135deg,var(--pb),var(--p),var(--v));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.sb-inf{width:20px;height:20px}
.sb-inf path{fill:none;stroke:var(--p);stroke-width:3;stroke-linecap:round}
.sb-body{flex:1;overflow-y:auto;padding:8px 0}
.sb-body::-webkit-scrollbar{width:3px}.sb-body::-webkit-scrollbar-thumb{background:var(--b);border-radius:2px}
.sb-section{padding:0 12px;margin-bottom:4px}
.sb-title{font-size:9px;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:var(--tm);padding:10px 4px 6px;cursor:pointer;display:flex;align-items:center;justify-content:space-between;user-select:none}
.sb-title:hover{color:var(--t2)}
.sb-title .arr{transition:transform .2s;font-size:8px}
.sb-title.open .arr{transform:rotate(90deg)}
.sb-content{display:none;padding-bottom:4px}
.sb-title.open+.sb-content{display:block}
.sb-btn{display:flex;align-items:center;gap:8px;padding:8px 12px;border-radius:8px;cursor:pointer;font-size:12px;color:var(--t2);transition:all .15s;border:none;background:none;width:100%;text-align:left;font-family:var(--f)}
.sb-btn:hover,.sb-btn:active{background:var(--s3);color:var(--t1)}
.sb-btn.active{background:var(--pg);color:var(--p)}
.sb-btn .icon{font-size:14px;width:20px;text-align:center;flex-shrink:0}
.sb-new{margin:8px 12px;padding:10px;border-radius:8px;background:linear-gradient(135deg,var(--pd),var(--v));color:#fff;font-family:var(--f);font-size:12px;font-weight:600;border:none;cursor:pointer;text-align:center;transition:transform .1s}
.sb-new:active{transform:scale(.97)}
.sb-conv{max-height:200px;overflow-y:auto}
.sb-conv::-webkit-scrollbar{width:2px}
.sb-user{padding:12px 16px;border-top:1px solid var(--b);display:flex;align-items:center;gap:10px;cursor:pointer}
.sb-user:hover{background:var(--s3)}
.sb-avatar{width:28px;height:28px;border-radius:8px;background:var(--pg);border:1px solid var(--pgs);display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:var(--p);flex-shrink:0}
.sb-uname{font-size:11px;color:var(--t2);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sb-uplan{font-size:9px;padding:2px 6px;border-radius:3px;background:var(--pg);color:var(--p)}

/* MAIN */
.main{flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0}
.topbar{display:flex;align-items:center;padding:0 16px;padding-top:var(--st);height:calc(48px + var(--st));background:var(--s1);border-bottom:1px solid var(--b);flex-shrink:0;gap:12px}
.hamburger{display:none;background:none;border:none;color:var(--t2);font-size:20px;cursor:pointer;padding:4px}
.tb-title{flex:1;font-size:13px;font-weight:600;color:var(--t1);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.conn-pill{display:flex;align-items:center;gap:5px;padding:3px 8px;border-radius:12px;font-size:9px;font-weight:500;letter-spacing:.3px;text-transform:uppercase}
.conn-pill.on{background:var(--gd);color:var(--g);border:1px solid rgba(52,211,153,.2)}
.conn-pill.off{background:var(--rd);color:var(--r);border:1px solid rgba(248,113,113,.2)}
.conn-dot{width:5px;height:5px;border-radius:50%;background:currentColor}
.tb-menu{position:relative}
.tb-menu-btn{background:var(--s3);border:1px solid var(--b);color:var(--t2);width:32px;height:32px;border-radius:8px;cursor:pointer;font-size:14px;display:flex;align-items:center;justify-content:center}
.tb-menu-btn:hover{color:var(--p);border-color:var(--bf)}
.tb-drop{position:absolute;right:0;top:38px;background:var(--s2);border:1px solid var(--b);border-radius:10px;padding:6px;min-width:160px;display:none;z-index:50;box-shadow:0 8px 24px rgba(0,0,0,.4)}
.tb-drop.show{display:block}
.tb-drop a,.tb-drop button{display:flex;align-items:center;gap:8px;padding:8px 12px;border-radius:6px;font-size:11px;color:var(--t2);text-decoration:none;cursor:pointer;background:none;border:none;font-family:var(--f);width:100%;text-align:left}
.tb-drop a:hover,.tb-drop button:hover{background:var(--s3);color:var(--t1)}

/* TERMINAL */
.terminal{flex:1;overflow-y:auto;padding:16px;-webkit-overflow-scrolling:touch}
.terminal::-webkit-scrollbar{width:4px}.terminal::-webkit-scrollbar-thumb{background:var(--b);border-radius:2px}

/* WELCOME */
.welcome{text-align:center;padding:20px 16px 24px}
.welcome h2{font-size:15px;font-weight:600;color:var(--t1);margin:12px 0 4px}
.welcome p{font-size:11px;color:var(--tm);max-width:260px;margin:0 auto}
.qgrid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;max-width:340px;margin:18px auto 0}
.qcard{background:var(--s2);border:1px solid var(--b);border-radius:10px;padding:12px 10px;cursor:pointer;transition:all .15s;text-align:left}
.qcard:hover,.qcard:active{border-color:var(--bf);background:var(--s3);transform:translateY(-1px)}
.qcard .qi{font-size:16px;margin-bottom:4px}.qcard .qt{font-size:10px;font-weight:600;color:var(--t1)}.qcard .qd{font-size:9px;color:var(--tm);margin-top:1px}

/* MESSAGES */
.ml{margin-bottom:18px;animation:mi .2s ease-out}
@keyframes mi{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:translateY(0)}}
.mh{display:flex;align-items:center;gap:8px;margin-bottom:5px}
.mav{width:20px;height:20px;border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:9px;font-weight:700;flex-shrink:0}
.ml.user .mav{background:var(--s4);color:var(--t2);border:1px solid var(--b)}
.ml.assistant .mav{background:var(--pgs);border:1px solid rgba(167,139,250,.3);padding:2px}
.ml.assistant .mav svg{width:12px;height:12px}
.ml.assistant .mav svg path{fill:none;stroke:var(--pb);stroke-width:3;stroke-linecap:round}
.mn{font-size:11px;font-weight:600}.ml.user .mn{color:var(--t2)}.ml.assistant .mn{color:var(--p)}
.mt{font-size:9px;color:var(--tm);margin-left:auto}
.mb{padding-left:28px;white-space:pre-wrap;word-wrap:break-word;font-size:13px;line-height:1.7;color:var(--t1)}
.ml.user .mb{color:var(--t2)}
.mb h1,.mb h2,.mb h3{color:var(--pb);margin:10px 0 4px;font-size:14px}.mb h1{font-size:16px}
.mb ul,.mb ol{margin:4px 0;padding-left:18px}.mb li{margin-bottom:2px}.mb p{margin:4px 0}
.mb a{color:var(--p);text-decoration:underline}.mb strong{color:var(--t1);font-weight:700}
.mb code{background:var(--s4);padding:1px 5px;border-radius:4px;font-size:12px;border:1px solid var(--b);color:var(--pb)}
.mb pre{background:var(--s1);border:1px solid var(--b);border-left:3px solid var(--pd);border-radius:8px;padding:10px 12px;margin:8px 0;overflow-x:auto;font-size:12px}
.mb pre code{background:none;padding:0;border:none;color:var(--t1)}
.mb table{border-collapse:collapse;margin:6px 0;font-size:11px;width:100%}.mb th,.mb td{border:1px solid var(--b);padding:3px 6px;text-align:left}.mb th{background:var(--s3);color:var(--p);font-weight:600}
.mb blockquote{border-left:3px solid var(--pd);padding:3px 10px;margin:6px 0;color:var(--t2);background:var(--s2);border-radius:0 6px 6px 0}

/* THINKING */
.think{margin-bottom:18px;animation:mi .2s ease-out}
.think-in{display:flex;align-items:center;gap:12px;padding:12px 14px;background:var(--s2);border:1px solid var(--b);border-radius:10px}
.inf-spin{width:32px;height:32px;flex-shrink:0;animation:idr 2s ease-in-out infinite}
.inf-spin path{fill:none;stroke:var(--p);stroke-width:3;stroke-linecap:round;stroke-dasharray:120;animation:itr 2s ease-in-out infinite}
@keyframes itr{0%{stroke-dashoffset:0;stroke:var(--p)}50%{stroke-dashoffset:120;stroke:var(--pb)}100%{stroke-dashoffset:240;stroke:var(--p)}}
@keyframes idr{0%,100%{opacity:1}50%{opacity:.6}}
.think-t{font-size:11px;color:var(--t2)}.think-d::after{content:'';animation:td 1.5s steps(4,end) infinite}
@keyframes td{0%{content:''}25%{content:'.'}50%{content:'..'}75%{content:'...'}}

.scur{display:inline-block;width:2px;height:14px;background:var(--p);animation:cb .8s step-end infinite;vertical-align:text-bottom;margin-left:1px;border-radius:1px}
@keyframes cb{0%,50%{opacity:1}51%,100%{opacity:0}}

/* TOOL BLOCKS */
.tblk{margin:6px 0;border:1px solid var(--b);border-radius:8px;overflow:hidden;font-size:11px;background:var(--s2)}
.thd{display:flex;align-items:center;gap:6px;padding:6px 10px;cursor:pointer;user-select:none}.thd:active{background:var(--s3)}
.tsp{animation:sp 1s linear infinite;display:inline-block}@keyframes sp{from{transform:rotate(0)}to{transform:rotate(360deg)}}
.tlb{color:var(--p);font-weight:600;flex:1}.tdr{color:var(--tm);font-size:10px}
.tout{padding:6px 10px;background:var(--s1);border-top:1px solid var(--b);max-height:140px;overflow-y:auto;color:var(--t2);font-size:10px;display:none}
.tblk.open .tout,.tblk.act .tout{display:block}

/* FILE CARD */
.fcard{display:flex;align-items:center;gap:12px;padding:12px 14px;margin:8px 0;background:var(--s2);border:1px solid var(--b);border-radius:10px}
.fcard:hover{border-color:var(--bf)}
.ficon{width:40px;height:40px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:18px;background:var(--pg);border:1px solid rgba(167,139,250,.2);flex-shrink:0}
.finfo{flex:1;min-width:0}.fname{font-size:12px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.fmeta{font-size:9px;color:var(--tm);margin-top:1px}
.fbtn{padding:6px 12px;border-radius:6px;font-family:var(--f);font-size:10px;font-weight:600;cursor:pointer;text-decoration:none;border:none}
.fbtn:active{transform:scale(.95)}.fbtn.pr{background:linear-gradient(135deg,var(--pd),var(--v));color:#fff}.fbtn.sc{background:var(--s3);color:var(--p);border:1px solid var(--b)}
.eline{color:var(--r);background:var(--rd);border:1px solid rgba(248,113,113,.2);border-radius:8px;padding:6px 10px;margin:6px 0;font-size:11px}

/* INPUT */
.input-area{flex-shrink:0;padding:10px 12px;padding-bottom:calc(10px + var(--sb));background:var(--s1);border-top:1px solid var(--b)}
.ibox{display:flex;align-items:flex-end;gap:8px;background:var(--s2);border:1px solid var(--b);border-radius:14px;padding:10px 12px;transition:border-color .2s,box-shadow .2s}
.ibox:focus-within{border-color:var(--bf);box-shadow:0 0 0 3px var(--pg)}
.ichev{color:var(--p);font-weight:700;font-size:14px;user-select:none;flex-shrink:0}
.ibox textarea{flex:1;background:none;border:none;color:var(--t1);font-family:var(--f);font-size:14px;line-height:1.5;resize:none;outline:none;max-height:100px;min-height:20px}
.ibox textarea::placeholder{color:var(--tm);font-size:13px}
.sbtn{width:34px;height:34px;border-radius:10px;border:none;background:linear-gradient(135deg,var(--pd),var(--v));color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:transform .1s}
.sbtn:active{transform:scale(.92)}.sbtn:disabled{opacity:.3;cursor:not-allowed}
.sbtn svg{width:16px;height:16px}

/* MODAL */
.modal-bg{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:100;display:none;align-items:center;justify-content:center;padding:20px;backdrop-filter:blur(4px)}
.modal-bg.show{display:flex}
.modal{background:var(--s2);border:1px solid var(--b);border-radius:16px;padding:24px;max-width:400px;width:100%;max-height:80vh;overflow-y:auto}
.modal h3{font-size:14px;color:var(--pb);margin-bottom:16px}
.modal label{display:block;font-size:10px;font-weight:600;letter-spacing:.5px;text-transform:uppercase;color:var(--tm);margin:10px 0 4px}
.modal input,.modal select{width:100%;padding:10px;background:var(--s3);border:1px solid var(--b);border-radius:8px;color:var(--t1);font-family:var(--f);font-size:13px;outline:none}
.modal input:focus{border-color:var(--bf)}
.modal .mbtn{margin-top:16px;padding:12px;width:100%;border-radius:10px;border:none;background:linear-gradient(135deg,var(--pd),var(--v));color:#fff;font-family:var(--f);font-size:13px;font-weight:600;cursor:pointer}
.modal .mclose{position:absolute;top:12px;right:16px;background:none;border:none;color:var(--tm);font-size:18px;cursor:pointer}

/* ADMIN SECTION */
.adm-cards{display:grid;grid-template-columns:repeat(2,1fr);gap:6px;padding:4px 0}
.adm-card{background:var(--s3);border:1px solid var(--b);border-radius:8px;padding:8px 10px}
.adm-card .al{font-size:8px;font-weight:600;letter-spacing:.5px;text-transform:uppercase;color:var(--tm)}.adm-card .av{font-size:18px;font-weight:700;color:var(--p);margin-top:2px}
.adm-tbl{width:100%;font-size:10px;border-collapse:collapse;margin-top:6px}
.adm-tbl th{text-align:left;color:var(--tm);font-weight:600;padding:4px 6px;border-bottom:1px solid var(--b);font-size:9px;text-transform:uppercase}
.adm-tbl td{padding:4px 6px;border-bottom:1px solid rgba(167,139,250,.06);color:var(--t2)}
.adm-tbl select{background:var(--s3);border:1px solid var(--b);color:var(--t1);font-family:var(--f);font-size:9px;padding:2px 4px;border-radius:3px}
.adm-tbl button{background:var(--s3);border:1px solid var(--b);color:var(--t2);font-family:var(--f);font-size:9px;padding:2px 6px;border-radius:3px;cursor:pointer}
.adm-tbl button:hover{color:var(--p);border-color:var(--bf)}
.badge-s{padding:1px 5px;border-radius:3px;font-size:9px;font-weight:500}
.badge-s.g{background:var(--gd);color:var(--g)}.badge-s.r{background:var(--rd);color:var(--r)}.badge-s.p{background:var(--pg);color:var(--p)}

/* RESPONSIVE */
@media(max-width:768px){
  .sidebar{position:fixed;left:0;top:0;height:100%;transform:translateX(-100%);box-shadow:4px 0 20px rgba(0,0,0,.5)}
  .sidebar.open{transform:translateX(0)}
  .hamburger{display:block}
  .sb-overlay{position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:25;display:none}
  .sb-overlay.show{display:block}
}
@media(min-width:769px){.hamburger{display:none}}
</style>
</head>
<body>

<!-- Sidebar Overlay (mobile) -->
<div class="sb-overlay" id="sbOverlay" onclick="toggleSB()"></div>

<!-- Sidebar -->
<aside class="sidebar" id="sidebar">
  <div class="sidebar-head">
    <svg class="sb-inf" viewBox="0 0 32 32"><path d="M8 16c0-3 2-6 5-6s5 3 8 6c3 3 5 6 8 6s5-3 5-6-2-6-5-6-5 3-8 6c-3 3-5 6-8 6s-5-3-5-6z" transform="translate(-5,0) scale(.95)"/></svg>
    <span class="sb-logo">CLOW</span>
  </div>
  <div class="sb-body">
    <div class="sb-section">
      <button class="sb-new" onclick="newConv()">+ Nova Conversa</button>
    </div>

    <div class="sb-section">
      <div class="sb-title open" onclick="this.classList.toggle('open')">Conversas <span class="arr">&#9654;</span></div>
      <div class="sb-content"><div class="sb-conv" id="convList"></div></div>
    </div>

    <div class="sb-section">
      <div class="sb-title open" onclick="this.classList.toggle('open')">Ferramentas <span class="arr">&#9654;</span></div>
      <div class="sb-content">
        <button class="sb-btn" onclick="qa('Cria uma landing page de ')"><span class="icon">&#x1F310;</span>Landing Page</button>
        <button class="sb-btn" onclick="qa('Gera uma planilha de ')"><span class="icon">&#x1F4CA;</span>Planilha</button>
        <button class="sb-btn" onclick="qa('Cria uma apresentacao sobre ')"><span class="icon">&#x1F3AC;</span>Apresentacao</button>
        <button class="sb-btn" onclick="qa('Faz um documento de ')"><span class="icon">&#x1F4C4;</span>Documento</button>
        <button class="sb-btn" onclick="qa('Me faz um app de ')"><span class="icon">&#x26A1;</span>Web App</button>
        <button class="sb-btn" onclick="qa('Gera copy para anuncio de ')"><span class="icon">&#x1F4DD;</span>Copy Ads</button>
        <button class="sb-btn" onclick="qa('Ideias de conteudo para instagram sobre ')"><span class="icon">&#x1F4F1;</span>Conteudo</button>
      </div>
    </div>

    <div class="sb-section">
      <div class="sb-title" onclick="this.classList.toggle('open')">Conexoes <span class="arr">&#9654;</span></div>
      <div class="sb-content" id="connSection">
        <button class="sb-btn" onclick="sendCmd('/connections')"><span class="icon">&#x1F517;</span>Ver conexoes</button>
        <button class="sb-btn" onclick="sendCmd('/connect')"><span class="icon">&#x2795;</span>Conectar servico</button>
      </div>
    </div>

    <div class="sb-section" id="adminSection" style="display:none">
      <div class="sb-title" onclick="this.classList.toggle('open')">Admin <span class="arr">&#9654;</span></div>
      <div class="sb-content">
        <button class="sb-btn" onclick="showAdminUsers()"><span class="icon">&#x1F465;</span>Usuarios</button>
        <button class="sb-btn" onclick="showAdminStats()"><span class="icon">&#x1F4CA;</span>Consumo</button>
        <button class="sb-btn" onclick="showCreateUser()"><span class="icon">&#x2795;</span>Cadastrar usuario</button>
      </div>
    </div>
  </div>

  <div class="sb-user" id="sbUser" onclick="toggleMenu()">
    <div class="sb-avatar" id="sbAvatar">?</div>
    <span class="sb-uname" id="sbEmail">...</span>
    <span class="sb-uplan" id="sbPlan">...</span>
  </div>
</aside>

<!-- Main -->
<div class="main">
  <div class="topbar">
    <button class="hamburger" onclick="toggleSB()">&#9776;</button>
    <div class="tb-title" id="tbTitle">Nova conversa</div>
    <div class="conn-pill on" id="connPill"><span class="conn-dot"></span><span id="connLbl">online</span></div>
    <div class="tb-menu">
      <button class="tb-menu-btn" onclick="toggleDrop()">&#x22EE;</button>
      <div class="tb-drop" id="tbDrop">
        <button onclick="sendCmd('/usage');closeDrop()">&#x1F4CA; Meu consumo</button>
        <button onclick="sendCmd('/plan');closeDrop()">&#x1F4E6; Meu plano</button>
        <button onclick="sendCmd('/help');closeDrop()">&#x2753; Ajuda</button>
        <a href="/logout">&#x1F6AA; Sair</a>
      </div>
    </div>
  </div>

  <div class="terminal" id="terminal">
    <div class="welcome" id="welc">
      <svg style="width:40px;height:40px;margin:0 auto;opacity:.7" viewBox="0 0 32 32"><path d="M8 16c0-3 2-6 5-6s5 3 8 6c3 3 5 6 8 6s5-3 5-6-2-6-5-6-5 3-8 6c-3 3-5 6-8 6s-5-3-5-6z" transform="translate(-5,0) scale(.95)" fill="none" stroke="var(--p)" stroke-width="2" stroke-linecap="round"/></svg>
      <h2>System Clow</h2>
      <p>O que voce precisa hoje?</p>
      <div class="qgrid">
        <div class="qcard" onclick="qa('Cria uma landing page de ')"><div class="qi">&#x1F310;</div><div class="qt">Landing Page</div><div class="qd">Site completo</div></div>
        <div class="qcard" onclick="qa('Gera uma planilha de ')"><div class="qi">&#x1F4CA;</div><div class="qt">Planilha</div><div class="qd">Excel profissional</div></div>
        <div class="qcard" onclick="qa('Cria uma apresentacao sobre ')"><div class="qi">&#x1F3AC;</div><div class="qt">Apresentacao</div><div class="qd">Slides PowerPoint</div></div>
        <div class="qcard" onclick="qa('Me faz um app de ')"><div class="qi">&#x26A1;</div><div class="qt">Web App</div><div class="qd">App funcional</div></div>
        <div class="qcard" onclick="qa('Gera copy para anuncio de ')"><div class="qi">&#x1F4DD;</div><div class="qt">Copy Ads</div><div class="qd">Texto p/ anuncios</div></div>
        <div class="qcard" onclick="qa('Ideias de conteudo para instagram sobre ')"><div class="qi">&#x1F4F1;</div><div class="qt">Conteudo</div><div class="qd">Ideias p/ redes</div></div>
      </div>
    </div>
  </div>

  <div class="input-area">
    <div class="ibox"><span class="ichev">&#x276f;</span>
      <textarea id="input" rows="1" placeholder="Digite um comando..." autofocus></textarea>
      <button class="sbtn" id="sendBtn" onclick="sendMessage()"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg></button>
    </div>
  </div>
</div>

<!-- Modal -->
<div class="modal-bg" id="modalBg" onclick="if(event.target===this)closeModal()">
  <div class="modal" id="modalContent"></div>
</div>

<script>
const INF='<svg viewBox="0 0 32 32" style="width:12px;height:12px"><path d="M8 16c0-3 2-6 5-6s5 3 8 6c3 3 5 6 8 6s5-3 5-6-2-6-5-6-5 3-8 6c-3 3-5 6-8 6s-5-3-5-6z" transform="translate(-5,0) scale(.95)" fill="none" stroke="var(--pb)" stroke-width="3" stroke-linecap="round"/></svg>';
const SINF='<svg viewBox="0 0 32 32" style="width:32px;height:32px"><path d="M8 16c0-3 2-6 5-6s5 3 8 6c3 3 5 6 8 6s5-3 5-6-2-6-5-6-5 3-8 6c-3 3-5 6-8 6s-5-3-5-6z" transform="translate(-5,0) scale(.95)" fill="none" stroke="var(--p)" stroke-width="3" stroke-linecap="round" stroke-dasharray="120" style="animation:itr 2s ease-in-out infinite"/></svg>';
const T=document.getElementById('terminal'),I=document.getElementById('input'),SB=document.getElementById('sendBtn');
let ws=null,proc=false,curMsg=null,curBody=null,curTool=null,tStart=0,tTimer=null,rAttempts=0,httpMode=false,httpSid='',rawBuf='',me=null,convId='';

// ── Init ──
async function init(){
  try{const r=await fetch('/api/v1/me');me=await r.json();
    document.getElementById('sbAvatar').textContent=me.email[0].toUpperCase();
    document.getElementById('sbEmail').textContent=me.email;
    document.getElementById('sbPlan').textContent=me.plan;
    if(me.is_admin)document.getElementById('adminSection').style.display='block';
  }catch(e){}
  loadConvs();
  connectWS();
}

// ── Sidebar ──
function toggleSB(){document.getElementById('sidebar').classList.toggle('open');document.getElementById('sbOverlay').classList.toggle('show')}
function toggleMenu(){document.getElementById('tbDrop').classList.toggle('show')}
function toggleDrop(){document.getElementById('tbDrop').classList.toggle('show')}
function closeDrop(){document.getElementById('tbDrop').classList.remove('show')}
document.addEventListener('click',e=>{if(!e.target.closest('.tb-menu'))closeDrop()});

// ── Conversations ──
async function loadConvs(){
  try{const r=await fetch('/api/v1/conversations');const d=await r.json();
    const el=document.getElementById('convList');
    el.innerHTML=d.conversations.map(c=>`<button class="sb-btn${c.id===convId?' active':''}" onclick="loadConv('${c.id}')"><span class="icon">&#x1F4AC;</span>${esc(c.title.substring(0,25))}</button>`).join('')||'<div style="padding:8px 12px;color:var(--tm);font-size:10px">Nenhuma conversa</div>';
  }catch(e){}
}
async function newConv(){
  try{const r=await fetch('/api/v1/conversations',{method:'POST'});const d=await r.json();
    convId=d.id;T.innerHTML='';showWelcome();
    document.getElementById('tbTitle').textContent='Nova conversa';
    loadConvs();
    if(window.innerWidth<769)toggleSB();
  }catch(e){}
}
async function loadConv(id){
  convId=id;T.innerHTML='';
  try{const r=await fetch(`/api/v1/conversations/${id}/messages`);const d=await r.json();
    d.messages.forEach(m=>{
      if(m.role==='user')addUserMsg(m.content,false);
      else{curMsg=null;curBody=null;appendText(m.content);finishText();curMsg=null;curBody=null}
    });
    const convs=await(await fetch('/api/v1/conversations')).json();
    const c=convs.conversations.find(x=>x.id===id);
    if(c)document.getElementById('tbTitle').textContent=c.title;
    loadConvs();
    if(window.innerWidth<769)toggleSB();
  }catch(e){}
}
function showWelcome(){
  const w=document.createElement('div');w.className='welcome';w.id='welc';
  w.innerHTML='<svg style="width:40px;height:40px;margin:0 auto;opacity:.7" viewBox="0 0 32 32"><path d="M8 16c0-3 2-6 5-6s5 3 8 6c3 3 5 6 8 6s5-3 5-6-2-6-5-6-5 3-8 6c-3 3-5 6-8 6s-5-3-5-6z" transform="translate(-5,0) scale(.95)" fill="none" stroke="var(--p)" stroke-width="2" stroke-linecap="round"/></svg><h2>System Clow</h2><p>O que voce precisa hoje?</p><div class="qgrid"><div class="qcard" onclick="qa(\'Cria uma landing page de \')"><div class="qi">&#x1F310;</div><div class="qt">Landing Page</div></div><div class="qcard" onclick="qa(\'Gera uma planilha de \')"><div class="qi">&#x1F4CA;</div><div class="qt">Planilha</div></div><div class="qcard" onclick="qa(\'Cria uma apresentacao sobre \')"><div class="qi">&#x1F3AC;</div><div class="qt">Apresentacao</div></div><div class="qcard" onclick="qa(\'Me faz um app de \')"><div class="qi">&#x26A1;</div><div class="qt">Web App</div></div></div>';
  T.appendChild(w);
}

// ── WebSocket ──
function connectWS(){
  const pr=location.protocol==='https:'?'wss:':'ws:';
  try{ws=new WebSocket(`${pr}//${location.host}/ws`)}catch(e){httpMode=true;setConn('http');return}
  const to=setTimeout(()=>{if(!ws||ws.readyState!==1){try{ws.close()}catch(e){}httpMode=true;setConn('http')}},4000);
  ws.onopen=()=>{clearTimeout(to);httpMode=false;setConn('online');rAttempts=0};
  ws.onmessage=e=>handleMsg(JSON.parse(e.data));
  ws.onclose=()=>{clearTimeout(to);if(rAttempts>=3){httpMode=true;setConn('http');return}setConn('offline');setTimeout(()=>{rAttempts++;connectWS()},Math.min(1000*rAttempts,5000))};
  ws.onerror=()=>setConn('offline');
}
function setConn(s){
  const p=document.getElementById('connPill'),l=document.getElementById('connLbl');
  p.className='conn-pill '+(s==='offline'?'off':'on');l.textContent=s;
}
function handleMsg(m){
  switch(m.type){
    case'thinking_start':showThink();break;case'thinking_end':hideThink();break;
    case'text_delta':appendText(m.content);break;case'text_done':finishText();break;
    case'tool_call':showTool(m.name,m.args);break;case'tool_result':showToolRes(m.name,m.status,m.output);break;
    case'turn_complete':finishTurn();break;case'error':showErr(m.content);break;
  }
}

// ── Send ──
function sendMessage(){
  const text=I.value.trim();if(!text||proc)return;
  if(httpMode){sendHTTP(text);return}
  if(!ws||ws.readyState!==1)return;
  addUserMsg(text);ws.send(JSON.stringify({type:'message',content:text}));
  I.value='';I.style.height='auto';proc=true;SB.disabled=true;
}
async function sendHTTP(text){
  addUserMsg(text);I.value='';I.style.height='auto';proc=true;SB.disabled=true;
  showThink();
  try{
    const r=await fetch('/api/v1/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content:text,session_id:httpSid,conversation_id:convId})});
    hideThink();
    if(!r.ok){const e=await r.json().catch(()=>({error:'Erro'}));showErr(e.error||e.response||'Erro');finishTurn();return}
    const d=await r.json();httpSid=d.session_id||httpSid;
    if(d.tools&&d.tools.length)d.tools.forEach(t=>{showTool(t.name,t.args);showToolRes(t.name,t.status,t.output||'')});
    if(d.response){appendText(d.response);finishText()}
    if(d.file)showFile(d.file);
    finishTurn();
  }catch(e){hideThink();showErr('Erro: '+e.message);finishTurn()}
}
function sendCmd(cmd){I.value=cmd;sendMessage()}
function qa(text){const w=document.getElementById('welc');if(w)w.remove();I.value=text;I.focus();if(window.innerWidth<769)toggleSB()}

// ── Messages ──
function now(){return new Date().toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'})}
function addUserMsg(text,save=true){
  const w=document.getElementById('welc');if(w)w.remove();
  const d=document.createElement('div');d.className='ml user';
  d.innerHTML=`<div class="mh"><div class="mav">${me?me.email[0].toUpperCase():'?'}</div><span class="mn">voce</span><span class="mt">${now()}</span></div><div class="mb">${esc(text)}</div>`;
  T.appendChild(d);scroll();
  if(!convId&&save){fetch('/api/v1/conversations',{method:'POST'}).then(r=>r.json()).then(d=>{convId=d.id;loadConvs()})}
}
function showThink(){hideThink();const d=document.createElement('div');d.className='think';d.id='thinkEl';d.innerHTML=`<div class="think-in"><div class="inf-spin">${SINF}</div><span class="think-t">Processando<span class="think-d"></span></span></div>`;T.appendChild(d);scroll()}
function hideThink(){const e=document.getElementById('thinkEl');if(e)e.remove()}
function ensureMsg(){
  if(!curMsg){hideThink();curMsg=document.createElement('div');curMsg.className='ml assistant';
    curMsg.innerHTML=`<div class="mh"><div class="mav">${INF}</div><span class="mn">clow</span><span class="mt">${now()}</span></div>`;
    curBody=document.createElement('div');curBody.className='mb';curMsg.appendChild(curBody);T.appendChild(curMsg);rawBuf=''}
}
function appendText(t){ensureMsg();rawBuf+=t;const c=curBody.querySelector('.scur');if(c)c.remove();curBody.insertAdjacentText('beforeend',t);const s=document.createElement('span');s.className='scur';curBody.appendChild(s);scroll()}
function finishText(){
  if(curBody){const c=curBody.querySelector('.scur');if(c)c.remove();
    if(rawBuf&&typeof marked!=='undefined'){marked.setOptions({breaks:true,gfm:true});curBody.innerHTML=marked.parse(rawBuf);curBody.querySelectorAll('a').forEach(a=>{a.target='_blank';a.rel='noopener'})}
    rawBuf=''}
}
function showTool(n,a){ensureMsg();const b=document.createElement('div');b.className='tblk act';const as=typeof a==='string'?a:JSON.stringify(a,null,2);b.innerHTML=`<div class="thd" onclick="this.parentElement.classList.toggle('open')"><span class="tsp" style="font-size:12px">&#x2699;</span><span class="tlb">${esc(n)}</span><span class="tdr">0.0s</span></div><div class="tout"><pre>${esc(as).substring(0,400)}</pre></div>`;curMsg.appendChild(b);curTool=b;tStart=Date.now();if(tTimer)clearInterval(tTimer);tTimer=setInterval(()=>{if(!curTool){clearInterval(tTimer);return}const d=curTool.querySelector('.tdr');if(d)d.textContent=((Date.now()-tStart)/1000).toFixed(1)+'s'},100);scroll()}
function showToolRes(n,s,o){if(tTimer){clearInterval(tTimer);tTimer=null}if(curTool){curTool.classList.remove('act');const i=curTool.querySelector('.tsp');if(i){i.classList.remove('tsp');i.textContent=s==='success'?'\u2713':s==='error'?'\u2717':'\u25cb';i.style.color=s==='success'?'var(--g)':s==='error'?'var(--r)':'var(--p)'}if(o){const b=curTool.querySelector('.tout');if(b)b.innerHTML+=`<pre style="margin-top:3px;color:${s==='error'?'var(--r)':'var(--t2)'}">${esc(o).substring(0,800)}</pre>`}const d=curTool.querySelector('.tdr');if(d)d.textContent=((Date.now()-tStart)/1000).toFixed(1)+'s';curTool=null}scroll()}
function showFile(f){ensureMsg();const ic={'landing_page':'\ud83c\udf10','app':'\u26a1','xlsx':'\ud83d\udcca','docx':'\ud83d\udcc4','pptx':'\ud83c\udfac'};const i=ic[f.type]||'\ud83d\udcc1';const w=f.type==='landing_page'||f.type==='app';const c=document.createElement('div');c.className='fcard';c.innerHTML=`<div class="ficon">${i}</div><div class="finfo"><div class="fname">${esc(f.name)}</div><div class="fmeta">${esc(f.size)}</div></div><div style="display:flex;gap:6px">${w?`<a href="${esc(f.url)}" target="_blank" class="fbtn pr">Abrir</a>`:''}<a href="${esc(f.url)}" download class="fbtn ${w?'sc':'pr'}">Download</a></div>`;curMsg.appendChild(c);scroll()}
function showErr(t){ensureMsg();const e=document.createElement('div');e.className='eline';e.textContent='\u2717 '+t;curMsg.appendChild(e);scroll()}
function finishTurn(){finishText();proc=false;SB.disabled=false;curMsg=null;curBody=null;I.focus();loadConvs()}
function scroll(){T.scrollTop=T.scrollHeight}
function esc(t){const d=document.createElement('div');d.textContent=t;return d.innerHTML}

// ── Admin ──
async function showAdminUsers(){
  const r=await fetch('/api/v1/admin/users');const d=await r.json();
  let h='<h3>Usuarios</h3><table class="adm-tbl"><tr><th>Email</th><th>Plano</th><th>Status</th><th>Acao</th></tr>';
  d.users.forEach(u=>{
    const st=u.active?'<span class="badge-s g">ativo</span>':'<span class="badge-s r">inativo</span>';
    h+=`<tr><td>${u.email}</td><td><select onchange="setPlan('${u.id}',this.value)">${['free','basic','pro','unlimited'].map(p=>`<option ${u.plan===p?'selected':''}>${p}</option>`).join('')}</select></td><td>${st}</td><td><button onclick="togUser('${u.id}',${u.active?0:1})">${u.active?'Desativar':'Ativar'}</button></td></tr>`;
  });
  h+='</table>';
  document.getElementById('modalContent').innerHTML=h;
  document.getElementById('modalBg').classList.add('show');
}
async function showAdminStats(){
  const r=await fetch('/api/v1/admin/stats');const d=await r.json();
  let h=`<h3>Consumo</h3><div class="adm-cards"><div class="adm-card"><div class="al">Usuarios</div><div class="av">${d.total_users}</div></div><div class="adm-card"><div class="al">Custo Hoje</div><div class="av">$${d.cost_today.toFixed(3)}</div></div><div class="adm-card"><div class="al">Custo Semana</div><div class="av">$${d.cost_week.toFixed(3)}</div></div><div class="adm-card"><div class="al">Tokens Hoje</div><div class="av">${(d.tokens_today/1000).toFixed(0)}k</div></div></div>`;
  if(d.top_users_today.length){h+='<table class="adm-tbl" style="margin-top:12px"><tr><th>Email</th><th>Tokens</th><th>Custo</th></tr>';d.top_users_today.forEach(u=>{h+=`<tr><td>${u.email}</td><td>${(u.tokens/1000).toFixed(0)}k</td><td>$${u.cost.toFixed(4)}</td></tr>`});h+='</table>'}
  document.getElementById('modalContent').innerHTML=h;
  document.getElementById('modalBg').classList.add('show');
}
function showCreateUser(){
  document.getElementById('modalContent').innerHTML=`<h3>Cadastrar Usuario</h3><label>Email</label><input id="nuEmail" type="email" placeholder="email@exemplo.com"><label>Senha</label><input id="nuPass" type="password" placeholder="minimo 6 chars"><label>Nome</label><input id="nuName" placeholder="opcional"><label>Plano</label><select id="nuPlan"><option>free</option><option>basic</option><option>pro</option><option>unlimited</option></select><button class="mbtn" onclick="createUser()">Cadastrar</button><div id="nuMsg" style="margin-top:8px;font-size:11px"></div>`;
  document.getElementById('modalBg').classList.add('show');
}
async function createUser(){
  const email=document.getElementById('nuEmail').value,pass=document.getElementById('nuPass').value,name=document.getElementById('nuName').value,plan=document.getElementById('nuPlan').value;
  const r=await fetch('/api/v1/admin/create-user',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,password:pass,name,plan})});
  const d=await r.json();
  document.getElementById('nuMsg').innerHTML=d.ok?'<span style="color:var(--g)">Usuario criado!</span>':`<span style="color:var(--r)">${d.error}</span>`;
}
async function setPlan(id,plan){await fetch(`/api/v1/admin/users/${id}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({plan})});showAdminUsers()}
async function togUser(id,active){await fetch(`/api/v1/admin/users/${id}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({active})});showAdminUsers()}
function closeModal(){document.getElementById('modalBg').classList.remove('show')}

// ── Input ──
I.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMessage()}});
I.addEventListener('input',()=>{I.style.height='auto';I.style.height=Math.min(I.scrollHeight,100)+'px'});
let lte=0;document.addEventListener('touchend',e=>{const n=Date.now();if(n-lte<=300)e.preventDefault();lte=n},false);

init();
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

    @app.get("/api/v1/me")
    async def api_me(request: Request):
        sess = _get_user_session(request)
        if not sess:
            return JSONResponse({"error": "Nao autenticado"}, status_code=401)
        return JSONResponse({
            "email": sess["email"],
            "user_id": sess["user_id"],
            "is_admin": sess.get("is_admin", False),
            "plan": sess.get("plan", "free"),
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
