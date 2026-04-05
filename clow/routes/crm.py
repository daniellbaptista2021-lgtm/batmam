"""CRM routes — proxy reverso do Chatwoot embeddado no Clow."""

from __future__ import annotations
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from fastapi import Request as _Req
from fastapi.responses import JSONResponse as _JR, HTMLResponse as _HR, RedirectResponse, Response

_TPL_DIR = Path(__file__).resolve().parent.parent / "templates"


def register_crm_routes(app) -> None:

    from .auth import _get_user_session

    def _auth(request: _Req):
        return _get_user_session(request)

    def _tenant(sess: dict) -> str:
        return sess["user_id"]

    # ── Page ──────────────────────────────────────────────────

    @app.get("/app/crm", tags=["crm"])
    async def crm_page(request: _Req):
        sess = _auth(request)
        if not sess:
            return RedirectResponse("/login")
        tpl = _TPL_DIR / "crm.html"
        if tpl.exists():
            return _HR(tpl.read_text(encoding="utf-8"))
        return _HR("<h1>CRM template not found</h1>")

    # ── Config ────────────────────────────────────────────────

    @app.get("/api/v1/crm/config", tags=["crm"])
    async def crm_get_config(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..chatwoot import get_crm_config
        cfg = get_crm_config(_tenant(sess))
        return _JR({
            "url": cfg.chatwoot_url,
            "configured": cfg.configured,
            "account_id": cfg.chatwoot_account_id,
            "token_full": cfg.chatwoot_api_token,
        })

    @app.post("/api/v1/crm/config", tags=["crm"])
    async def crm_save_config(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        try:
            body = await request.json()
            url = (body.get("url") or "").strip()
            email = (body.get("email") or "").strip()
            password = (body.get("password") or "").strip()

            if not url or not email or not password:
                return _JR({"error": "Preencha URL, email e senha."}, status_code=400)

            if body.get("test_only"):
                from ..chatwoot import chatwoot_login
                result = chatwoot_login(url, email, password)
                if result.get("success"):
                    return _JR({"ok": True, "message": f"Conexao OK! Account: {result.get('account_id', 1)}"})
                return _JR({"error": result.get("error", "Falha")}, status_code=400)

            from ..chatwoot import save_crm_config
            result = save_crm_config(_tenant(sess), url, email, password)
            if "error" in result:
                return _JR(result, status_code=400)
            return _JR(result)
        except Exception as exc:
            return _JR({"error": f"Erro: {exc}"}, status_code=500)

    # ── Proxy reverso ─────────────────────────────────────────
    # Serve o Chatwoot inteiro via proxy, removendo X-Frame-Options

    @app.api_route("/api/v1/crm/proxy/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"], tags=["crm"])
    async def crm_proxy(path: str, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)

        from ..chatwoot import get_crm_config
        cfg = get_crm_config(_tenant(sess))
        if not cfg.configured:
            return _JR({"error": "CRM nao configurado"}, status_code=400)

        # Build target URL
        target = f"{cfg.chatwoot_url}/{path}"
        qs = str(request.query_params)
        if qs:
            target += f"?{qs}"

        # Forward request
        try:
            body = await request.body() if request.method != "GET" else None
            headers = {
                "api_access_token": cfg.chatwoot_api_token,
                "Content-Type": request.headers.get("content-type", "application/json"),
            }
            # For browser requests (HTML pages), use cookie auth
            cookie = request.headers.get("x-crm-cookie", "")
            if cookie:
                headers["Cookie"] = cookie

            req = Request(
                target,
                data=body,
                headers=headers,
                method=request.method,
            )
            resp = urlopen(req, timeout=30)
            content = resp.read()
            content_type = resp.headers.get("Content-Type", "application/json")

            # Remove X-Frame-Options to allow iframe
            resp_headers = {
                "Content-Type": content_type,
                "Cache-Control": "no-cache",
            }

            return Response(content=content, headers=resp_headers, status_code=resp.status)
        except HTTPError as e:
            content = e.read() if e.fp else b""
            return Response(content=content, status_code=e.code, headers={"Content-Type": "text/html"})
        except Exception as e:
            return _JR({"error": str(e)[:200]}, status_code=502)

    @app.get("/api/v1/crm/proxy", tags=["crm"])
    async def crm_proxy_root(request: _Req):
        """Proxy da pagina principal do Chatwoot."""
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)

        from ..chatwoot import get_crm_config
        cfg = get_crm_config(_tenant(sess))
        if not cfg.configured:
            return _HR("<h1>CRM nao configurado</h1>")

        # Gera pagina que carrega o Chatwoot com token de autenticacao
        account_id = cfg.chatwoot_account_id
        chatwoot_url = cfg.chatwoot_url
        token = cfg.chatwoot_api_token

        # Injeta JS para fazer login automatico e redirecionar
        html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
body {{ margin:0; background:#1f2937; font-family:system-ui; }}
.loading {{ display:flex; align-items:center; justify-content:center; height:100vh; color:#9ca3af; }}
.spinner {{ width:30px; height:30px; border:3px solid #374151; border-top-color:#7c5cfc; border-radius:50%; animation:spin .8s linear infinite; margin-right:12px; }}
@keyframes spin {{ to {{ transform:rotate(360deg) }} }}
</style>
</head>
<body>
<div class="loading"><div class="spinner"></div>Carregando CRM...</div>
<script>
// Login automatico no Chatwoot
fetch("{chatwoot_url}/auth/sign_in", {{
  method: "POST",
  headers: {{"Content-Type": "application/json"}},
  body: JSON.stringify({{email: "{cfg.chatwoot_email}", password: "{cfg.chatwoot_password}"}})
}})
.then(r => r.json())
.then(data => {{
  if (data.data && data.data.access_token) {{
    // Seta cookies de autenticacao e redireciona
    document.cookie = "access_token=" + data.data.access_token + ";path=/;SameSite=Lax";
    document.cookie = "cw_d_session_info=%7B%22cs%22%3A%22" + data.data.access_token + "%22%7D;path=/;SameSite=Lax";
    document.cookie = "user_id=" + data.data.id + ";path=/;SameSite=Lax";
    window.location.href = "{chatwoot_url}/app/accounts/{account_id}/dashboard";
  }} else {{
    document.body.innerHTML = "<div style='color:#ef4444;padding:40px;text-align:center'>Falha no login. Verifique suas credenciais na configuracao do CRM.</div>";
  }}
}})
.catch(e => {{
  document.body.innerHTML = "<div style='color:#ef4444;padding:40px;text-align:center'>Erro de conexao: " + e.message + "</div>";
}});
</script>
</body>
</html>"""
        return _HR(html)
