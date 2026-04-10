"""Onboarding Routes — wizard de primeiro acesso."""

from __future__ import annotations
from pathlib import Path

from fastapi import Request as _Req
from fastapi.responses import JSONResponse as _JR, HTMLResponse as _HR, RedirectResponse

_TPL_DIR = Path(__file__).resolve().parent.parent / "templates"


def register_onboarding_routes(app) -> None:

    from .auth import _get_user_session

    def _auth(request: _Req):
        return _get_user_session(request)

    def _tenant(sess: dict) -> str:
        return sess["user_id"]

    @app.get("/app/onboarding", tags=["onboarding"])
    async def onboarding_page(request: _Req):
        sess = _auth(request)
        if not sess:
            return RedirectResponse("/login")
        tpl = _TPL_DIR / "onboarding.html"
        if tpl.exists():
            return _HR(tpl.read_text(encoding="utf-8"))
        return _HR("<h1>Onboarding em construcao</h1>")

    @app.get("/api/v1/onboarding/progress", tags=["onboarding"])
    async def onboarding_progress(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..onboarding import get_progress
        return _JR(get_progress(_tenant(sess)))

    @app.post("/api/v1/onboarding/complete-step", tags=["onboarding"])
    async def onboarding_complete_step(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        step_id = body.get("step_id", "")
        step_data = body.get("data", {})
        from ..onboarding import complete_step
        return _JR(complete_step(_tenant(sess), step_id, step_data))

    @app.post("/api/v1/onboarding/skip-step", tags=["onboarding"])
    async def onboarding_skip_step(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        from ..onboarding import skip_step
        return _JR(skip_step(_tenant(sess), body.get("step_id", "")))

    @app.post("/api/v1/onboarding/generate-prompt", tags=["onboarding"])
    async def onboarding_gen_prompt(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        from ..onboarding import generate_agent_prompt
        prompt = generate_agent_prompt(body)
        return _JR({"prompt": prompt})

    @app.post("/api/v1/onboarding/test-message", tags=["onboarding"])
    async def onboarding_test(request: _Req):
        """Simula conversa com o agente usando o prompt gerado."""
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        message = body.get("message", "").strip()
        prompt = body.get("prompt", "")
        if not message:
            return _JR({"error": "Mensagem obrigatoria"}, status_code=400)
        try:
            from openai import OpenAI
            from .. import config as _cfg
            client = OpenAI(**_cfg.get_deepseek_client_kwargs())
            response = client.chat.completions.create(
                model=_cfg.CLOW_MODEL,
                messages=[
                    {"role": "system", "content": prompt or "Voce e um atendente virtual. Seja simpatico e objetivo."},
                    {"role": "user", "content": message},
                ],
                max_tokens=300,
            )
            reply = (response.choices[0].message.content or "").strip() if response.choices else "Desculpe, nao consegui responder."
            return _JR({"reply": reply})
        except Exception as e:
            return _JR({"reply": f"Erro no teste: {str(e)[:100]}"})

    # ── Templates de agentes ──

    @app.get("/api/v1/templates", tags=["templates"])
    async def list_agent_templates(request: _Req):
        from ..agent_templates import list_templates
        return _JR({"templates": list_templates()})

    @app.get("/api/v1/templates/{tid}", tags=["templates"])
    async def get_agent_template(tid: str, request: _Req):
        from ..agent_templates import get_template
        t = get_template(tid)
        if not t:
            return _JR({"error": "Template nao encontrado"}, status_code=404)
        return _JR(t)

    @app.post("/api/v1/templates/{tid}/apply", tags=["templates"])
    async def apply_agent_template(tid: str, request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        body = await request.json()
        from ..agent_templates import apply_template
        result = apply_template(_tenant(sess), body.get("instance_id", ""), tid,
                                body.get("business_name", ""))
        return _JR(result)

    @app.post("/api/v1/onboarding/finish", tags=["onboarding"])
    async def onboarding_finish(request: _Req):
        sess = _auth(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)
        from ..onboarding import finish_onboarding
        return _JR(finish_onboarding(_tenant(sess)))
