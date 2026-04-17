"""Page routes: login, logout, index, dashboard, admin, PWA, static files."""

from __future__ import annotations
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .auth import (
    _create_session, _get_session_from_request, _get_user_session,
    _session_cache, _delete_session_db, _SESSION_TTL,
)
from ..database import authenticate_user

logger = logging.getLogger(__name__)

# ── Templates — carrega HTML de arquivos separados ─────────────

_TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
_STATIC_DIR = Path(__file__).parent.parent / "static"


def _load_template(name: str) -> str:
    """Carrega template HTML do diretorio templates/."""
    path = _TEMPLATE_DIR / name
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.error("Template not found: %s", path)
        return f"<h1>Template {name} not found</h1>"


# Lazy-loaded templates (cached on first access)
_template_cache: dict[str, str] = {}


def _get_template(name: str) -> str:
    """Retorna template com cache."""
    if name not in _template_cache:
        _template_cache[name] = _load_template(name)
    return _template_cache[name]


# Template accessors
def _webapp_html() -> str:
    return _get_template("chat.html")

def _dashboard_html() -> str:
    return _get_template("dashboard.html")

def _login_html() -> str:
    return _get_template("login.html")

def _admin_html() -> str:
    return _get_template("admin.html")


def register_page_routes(app: FastAPI) -> None:
    """Register all page-serving routes on the app."""

    # ── Login routes (sem auth) ──────────────────────────────────
    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        if _get_session_from_request(request):
            return RedirectResponse("/", status_code=302)
        html = _login_html().replace("__ERROR_CLASS__", "").replace("__ERROR_MSG__", "")
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
                samesite="lax", secure=True, path="/",
            )
            return resp

        html = _login_html().replace("__ERROR_CLASS__", "show").replace("__ERROR_MSG__", "Email ou senha incorretos")
        return HTMLResponse(html, status_code=401)

    @app.get("/logout")
    async def logout(request: Request):
        token = request.cookies.get("clow_session", "")
        if token in _session_cache:
            del _session_cache[token]
        _delete_session_db(token)
        resp = RedirectResponse("/login", status_code=302)
        resp.delete_cookie("clow_session", path="/", samesite="lax", secure=True)
        return resp

    # ── Mount static assets (CSS/JS extraidos) ─────────────────
    _css_dir = _STATIC_DIR / "css"
    _js_dir = _STATIC_DIR / "js"
    if _css_dir.is_dir():
        app.mount("/static/css", StaticFiles(directory=str(_css_dir)), name="css_static")
    if _js_dir.is_dir():
        app.mount("/static/js", StaticFiles(directory=str(_js_dir)), name="js_static")

    # ── Install tutorial (publica, sem login) ─────────────────────
    @app.get("/install", response_class=HTMLResponse)
    async def install_page():
        return _get_template("install.html")

    # ── Protected routes ─────────────────────────────────────────
    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        sess = _get_user_session(request)
        if not sess:
            return RedirectResponse("/login", status_code=302)
        # Redirect to onboarding if first login and not admin
        if not sess.get("is_admin") and sess.get("user_id"):
            from ..database import get_db
            with get_db() as db:
                user = db.execute("SELECT onboarding_completed, first_login FROM users WHERE id=?", (sess["user_id"],)).fetchone()
            if user and not user["onboarding_completed"] and user["first_login"]:
                return RedirectResponse("/app/onboarding", status_code=302)
        return _webapp_html()

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard_page(request: Request):
        if not _get_session_from_request(request):
            return RedirectResponse("/login", status_code=302)
        return _dashboard_html()

    @app.get("/admin", response_class=HTMLResponse)
    async def admin_page(request: Request):
        sess = _get_user_session(request)
        if not sess or not sess.get("is_admin"):
            return RedirectResponse("/login", status_code=302)
        return _admin_html()

    @app.get("/app/chatwoot-bot", response_class=HTMLResponse)
    async def chatwoot_bot_page(request: Request):
        sess = _get_user_session(request)
        if not sess or not sess.get("is_admin"):
            return RedirectResponse("/login", status_code=302)
        return _get_template("chatwoot_bot.html")

    @app.get("/app/admin/infrastructure", response_class=HTMLResponse)
    async def admin_infra_page(request: Request):
        sess = _get_user_session(request)
        if not sess or not sess.get("is_admin"):
            return RedirectResponse("/", status_code=302)
        return _get_template("admin_infra.html")

    @app.get("/app/setup", response_class=HTMLResponse)
    async def chatwoot_setup_page(request: Request):
        sess = _get_user_session(request)
        if not sess:
            return RedirectResponse("/login", status_code=302)
        return _get_template("chatwoot_setup.html")

    # ── PWA Routes (System Clow App) ──────────────────────────────
    @app.get("/pwa", response_class=HTMLResponse)
    async def pwa_index():
        """Pagina principal do PWA."""
        static_dir = Path(__file__).parent.parent.parent / "static"
        if (static_dir / "index.html").exists():
            with open(static_dir / "index.html") as f:
                return f.read()
        return HTMLResponse("<h1>System Clow</h1><p>PWA app</p>")

    @app.get("/static/manifest.json")
    async def manifest():
        """Manifest do PWA."""
        static_dir = Path(__file__).parent.parent.parent / "static"
        manifest_path = static_dir / "manifest.json"
        if manifest_path.exists():
            return FileResponse(manifest_path, media_type="application/manifest+json")
        return JSONResponse({"name": "System Clow", "short_name": "Clow"})

    @app.get("/static/service-worker.js")
    async def service_worker():
        """Service Worker para PWA."""
        static_dir = Path(__file__).parent.parent.parent / "static"
        sw_path = static_dir / "service-worker.js"
        if sw_path.exists():
            return FileResponse(sw_path, media_type="application/javascript")
        return JSONResponse({"error": "Service Worker not found"}, status_code=404)

    @app.get("/static/{file_path:path}")
    async def static_files(file_path: str):
        """Serve arquivos estaticos (CSS, JS, imagens, etc)."""
        static_dir = Path(__file__).parent.parent.parent / "static"
        full_path = (static_dir / file_path).resolve()

        # Security: previne path traversal
        if not str(full_path).startswith(str(static_dir)):
            return JSONResponse({"error": "Forbidden"}, status_code=403)

        if full_path.exists() and full_path.is_file():
            return FileResponse(full_path)
        return JSONResponse({"error": "Not found"}, status_code=404)
