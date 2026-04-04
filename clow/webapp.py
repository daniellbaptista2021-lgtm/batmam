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
import logging
import os
import time
from pathlib import Path
from typing import Any

try:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from . import __version__
from . import config
from .log_config import setup_logging

# Initialize structured logging before anything else
setup_logging()

logger = logging.getLogger("clow.webapp")

# Run database migrations on import (safe to call repeatedly)
try:
    from .migrations import run_migrations
    run_migrations()
except Exception as e:
    logging.getLogger("clow.webapp").warning("Migrations skipped: %s", e)

app = FastAPI(
    title="Clow",
    version=__version__,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
) if HAS_FASTAPI else None


# ── Acoes executadas (Feature #24 — tracking) ──────────────────
_recent_actions: list[dict] = []
MAX_RECENT_ACTIONS = 50


def track_action(action: str, details: str = "", status: str = "ok") -> None:
    """Registra acao recente para o dashboard."""
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


# ── Setup CORS e Middleware ──────────────────────────────────────

def _setup_middleware():
    """Configura CORS e middlewares de seguranca."""
    if not HAS_FASTAPI or app is None:
        return

    settings = config.load_settings()
    webapp_cfg = settings.get("webapp", {})

    # CORS — permite webapp, localhost e Chrome Extension
    allowed_origins = webapp_cfg.get("cors_origins", ["http://localhost:*", "http://127.0.0.1:*"])
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["*"],
    )

    # Security headers (CSP, X-Frame-Options, HSTS, etc.)
    from .security import SecurityHeadersMiddleware
    app.add_middleware(SecurityHeadersMiddleware)


if HAS_FASTAPI:
    _setup_middleware()

    # Register all route modules
    from .routes.pages import register_page_routes
    from .routes.api import register_api_routes
    from .routes.admin import register_admin_routes
    from .routes.chat import register_chat_routes
    from .routes.ws import register_ws_routes

    register_page_routes(app)
    register_api_routes(app)
    register_admin_routes(app)
    register_chat_routes(app)
    register_ws_routes(app)

    # ── Metrics & Error tracking endpoints ──────────────────────
    from fastapi import Request as _Req
    from fastapi.responses import JSONResponse as _JR, PlainTextResponse as _PR
    from .metrics import metrics
    from .error_tracker import get_recent_errors, error_stats, capture_exception

    @app.get("/metrics", tags=["monitoring"])
    async def prometheus_metrics():
        """Prometheus-compatible metrics endpoint."""
        return _PR(metrics.to_prometheus(), media_type="text/plain")

    @app.get("/api/v1/metrics/json", tags=["monitoring"])
    async def json_metrics():
        """JSON metrics with histograms and percentiles."""
        return _JR(metrics.to_json())

    @app.get("/api/v1/errors", tags=["monitoring"])
    async def api_errors(request: _Req):
        """Recent errors (admin only)."""
        from .routes.auth import _get_user_session
        sess = _get_user_session(request)
        if not sess or not sess.get("is_admin"):
            return _JR({"error": "Admin only"}, status_code=403)
        return _JR({"errors": get_recent_errors(50), "stats": error_stats()})

    # Instrument request latency
    @app.middleware("http")
    async def _metrics_middleware(request: _Req, call_next):
        start = time.time()
        response = await call_next(request)
        duration = time.time() - start
        metrics.inc("http_requests_total", labels={"method": request.method, "status": str(response.status_code)})
        metrics.observe("http_request_duration_seconds", duration, labels={"path": request.url.path[:50]})
        return response


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


# ── Mount de arquivos estaticos ──────────────────────────────────
if app and HAS_FASTAPI:
    try:
        # Usa caminho relativo ao projeto (portavel)
        _project_root = Path(__file__).parent.parent
        _static_dir = _project_root / "static"
        _static_dir.mkdir(parents=True, exist_ok=True)
        (_static_dir / "files").mkdir(exist_ok=True)
        app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")
    except Exception as e:
        logging.error(f"Erro ao montar /static: {e}")
