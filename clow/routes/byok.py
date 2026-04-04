"""BYOK (Bring Your Own Key) routes — onboarding, API key management, usage dashboard."""

from __future__ import annotations
import time
from typing import Any

from fastapi import Request as _Req
from fastapi.responses import JSONResponse as _JR, HTMLResponse as _HR


def register_byok_routes(app) -> None:
    """Registra endpoints BYOK."""

    from .auth import _get_user_session

    # ── API Key Management ────────────────────────────────────

    @app.post("/api/v1/onboarding/validate-key", tags=["byok"])
    async def validate_api_key(request: _Req):
        """Valida API key da Anthropic."""
        body = await request.json()
        api_key = body.get("api_key", "").strip()

        if not api_key:
            return _JR({"valid": False, "error": "API key vazia"}, status_code=400)

        if not api_key.startswith("sk-ant-"):
            return _JR({"valid": False, "error": "Formato invalido. A key deve comecar com sk-ant-"}, status_code=400)

        from ..database import validate_anthropic_key
        result = validate_anthropic_key(api_key)
        return _JR(result)

    @app.post("/api/v1/me/api-key", tags=["byok"])
    async def set_api_key(request: _Req):
        """Salva API key do usuario (BYOK)."""
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)

        body = await request.json()
        api_key = body.get("api_key", "").strip()

        if not api_key:
            return _JR({"error": "API key vazia"}, status_code=400)

        if not api_key.startswith("sk-ant-"):
            return _JR({"error": "Formato invalido"}, status_code=400)

        # Valida antes de salvar
        from ..database import validate_anthropic_key, set_user_api_key
        validation = validate_anthropic_key(api_key)
        if not validation.get("valid"):
            return _JR({"error": validation.get("error", "Key invalida")}, status_code=400)

        set_user_api_key(sess["user_id"], api_key)
        return _JR({
            "success": True,
            "message": "API key configurada. Voce agora usa Claude Sonnet com sua propria key.",
            "model": "claude-sonnet-4-20250514",
        })

    @app.delete("/api/v1/me/api-key", tags=["byok"])
    async def remove_api_key(request: _Req):
        """Remove API key do usuario."""
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)

        from ..database import remove_user_api_key
        remove_user_api_key(sess["user_id"])
        return _JR({"success": True, "message": "API key removida."})

    @app.get("/api/v1/me/api-key/status", tags=["byok"])
    async def api_key_status(request: _Req):
        """Verifica se usuario tem API key configurada."""
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)

        from ..database import get_user_api_key, get_user_by_id
        user = get_user_by_id(sess["user_id"])
        has_key = bool(get_user_api_key(sess["user_id"]))

        return _JR({
            "has_api_key": has_key,
            "byok_enabled": bool(user.get("byok_enabled")) if user else False,
            "model": "claude-sonnet-4-20250514" if has_key else "claude-haiku-4-5-20251001",
            "api_key_set_at": user.get("api_key_set_at", 0) if user else 0,
        })

    # ── Usage Dashboard ───────────────────────────────────────

    @app.get("/api/v1/usage/detailed", tags=["byok"])
    async def usage_detailed(request: _Req):
        """Retorna uso detalhado por sessao/dia."""
        sess = _get_user_session(request)
        if not sess:
            return _JR({"error": "Nao autenticado"}, status_code=401)

        from ..database import get_db
        user_id = sess["user_id"]

        with get_db() as db:
            # Uso total
            total = db.execute(
                "SELECT SUM(input_tokens) as inp, SUM(output_tokens) as out, SUM(cost_usd) as cost, COUNT(*) as calls FROM usage_log WHERE user_id=?",
                (user_id,),
            ).fetchone()

            # Uso hoje
            today_start = time.time() - (time.time() % 86400)
            today = db.execute(
                "SELECT SUM(input_tokens) as inp, SUM(output_tokens) as out, SUM(cost_usd) as cost, COUNT(*) as calls FROM usage_log WHERE user_id=? AND created_at>=?",
                (user_id, today_start),
            ).fetchone()

            # Uso por dia (ultimos 7 dias)
            daily = db.execute(
                "SELECT date(created_at, 'unixepoch') as day, SUM(input_tokens) as inp, SUM(output_tokens) as out, SUM(cost_usd) as cost, COUNT(*) as calls "
                "FROM usage_log WHERE user_id=? AND created_at>=? GROUP BY day ORDER BY day DESC",
                (user_id, time.time() - 7 * 86400),
            ).fetchall()

        # Calcula custo estimado (Sonnet: $3/MTok input, $15/MTok output)
        def _estimate_cost(inp: int, out: int) -> float:
            return round((inp * 3.0 + out * 15.0) / 1_000_000, 4)

        total_inp = total["inp"] or 0
        total_out = total["out"] or 0
        today_inp = today["inp"] or 0
        today_out = today["out"] or 0

        return _JR({
            "total": {
                "input_tokens": total_inp,
                "output_tokens": total_out,
                "total_tokens": total_inp + total_out,
                "estimated_cost_usd": _estimate_cost(total_inp, total_out),
                "calls": total["calls"] or 0,
            },
            "today": {
                "input_tokens": today_inp,
                "output_tokens": today_out,
                "total_tokens": today_inp + today_out,
                "estimated_cost_usd": _estimate_cost(today_inp, today_out),
                "calls": today["calls"] or 0,
            },
            "daily": [
                {
                    "date": d["day"],
                    "input_tokens": d["inp"] or 0,
                    "output_tokens": d["out"] or 0,
                    "estimated_cost_usd": _estimate_cost(d["inp"] or 0, d["out"] or 0),
                    "calls": d["calls"],
                }
                for d in daily
            ],
            "pricing": {
                "model": "claude-sonnet-4-20250514",
                "input_per_mtok": 3.0,
                "output_per_mtok": 15.0,
                "currency": "USD",
            },
        })

    # ── Signup (criar conta sem precisar de admin) ────────────

    # Rate limit para signup: max 5 por IP por hora
    _signup_attempts: dict[str, list[float]] = {}

    @app.post("/api/v1/auth/signup", tags=["byok"])
    async def signup(request: _Req):
        """Cria conta nova (BYOK flow). Seta cookie de sessao na response."""
        # Rate limit por IP
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        attempts = _signup_attempts.setdefault(client_ip, [])
        attempts[:] = [t for t in attempts if now - t < 3600]  # Janela 1h
        if len(attempts) >= 5:
            return _JR({"error": "Muitas tentativas. Tente novamente em 1 hora."}, status_code=429)
        attempts.append(now)

        body = await request.json()
        email = body.get("email", "").strip().lower()
        password = body.get("password", "").strip()
        name = body.get("name", "").strip()

        if not name:
            return _JR({"error": "Nome completo obrigatorio"}, status_code=400)
        if len(name.split()) < 2:
            return _JR({"error": "Informe nome e sobrenome"}, status_code=400)
        if not email or not password:
            return _JR({"error": "Email e senha obrigatorios"}, status_code=400)
        if "@" not in email or "." not in email.split("@")[-1]:
            return _JR({"error": "Email invalido"}, status_code=400)
        if len(password) < 6:
            return _JR({"error": "Senha deve ter pelo menos 6 caracteres"}, status_code=400)

        # Verifica duplicidade antes de criar
        from ..database import get_user_by_email, create_user
        existing = get_user_by_email(email)
        if existing:
            return _JR({
                "error": "Este email ja possui uma conta. Faca login em vez de criar outra.",
                "action": "login",
            }, status_code=409)

        user = create_user(email, password, name)
        if not user:
            return _JR({
                "error": "Este email ja possui uma conta. Faca login em vez de criar outra.",
                "action": "login",
            }, status_code=409)

        from .auth import _create_session, _SESSION_TTL
        token = _create_session(user)

        # Seta cookie via response header (mesmo modo que o login form)
        resp = _JR({
            "success": True,
            "token": token,
            "email": user["email"],
            "user_id": user["id"],
            "plan": user["plan"],
            "next_step": "configure_api_key",
        })
        resp.set_cookie(
            "clow_session", token,
            max_age=_SESSION_TTL, httponly=True,
            samesite="lax", secure=False, path="/",
        )
        return resp

    # ── Landing Page ──────────────────────────────────────────

    @app.get("/landing", tags=["byok"])
    async def landing_page():
        """Landing page BYOK do Clow."""
        return _HR(_landing_html())

    # ── Onboarding Page ───────────────────────────────────────

    @app.get("/onboarding", tags=["byok"])
    async def onboarding_page():
        """Pagina de onboarding BYOK."""
        return _HR(_onboarding_html())

    # ── Usage Page ────────────────────────────────────────────

    @app.get("/usage", tags=["byok"])
    async def usage_page():
        """Pagina de uso detalhado."""
        return _HR(_usage_html())


def _landing_html() -> str:
    from pathlib import Path
    tpl = Path(__file__).parent.parent / "templates" / "landing.html"
    if tpl.exists():
        return tpl.read_text(encoding="utf-8")
    return '''<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Clow — Intelig&ecirc;ncia Infinita</title>
<meta name="description" content="Clow: o agente de codigo AI mais completo do Brasil. Traga sua API key da Anthropic e use sem limites.">
<link rel="icon" type="image/png" href="/static/brand/favicon.png">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#050510;--bg2:#0F0F24;--bg3:#14142E;--bd:rgba(100,100,180,.12);--p:#9B59FC;--bl:#4A9EFF;--gp:linear-gradient(135deg,#9B59FC 0%,#4A9EFF 100%);--t1:#E8E8F0;--t2:#9898B8;--tm:#585878;--sans:'DM Sans',sans-serif}
body{font-family:var(--sans);background:var(--bg);color:var(--t1);overflow-x:hidden;-webkit-font-smoothing:antialiased}
body::before{content:'';position:fixed;inset:0;z-index:0;pointer-events:none;background:radial-gradient(ellipse at 50% 30%,rgba(155,89,252,.08),rgba(74,158,255,.04) 40%,transparent 65%)}
a{color:var(--p);text-decoration:none}

/* Hero */
.hero{min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:40px 20px;position:relative;z-index:1}
.hero-logo{height:120px;margin-bottom:8px;filter:drop-shadow(0 0 40px rgba(155,89,252,.3)) drop-shadow(0 0 40px rgba(74,158,255,.2));animation:float 4s ease-in-out infinite}
@keyframes float{0%,100%{transform:translateY(0)}50%{transform:translateY(-8px)}}
.lens-flare{width:280px;height:1px;margin:12px auto 24px;background:linear-gradient(90deg,transparent,rgba(155,89,252,.5),rgba(74,158,255,.5),transparent);box-shadow:0 0 15px rgba(155,89,252,.3)}
.tagline{font-size:10px;color:var(--tm);letter-spacing:3px;text-transform:uppercase;margin-bottom:32px}
.hero h1{font-size:clamp(2.5rem,6vw,4rem);font-weight:800;line-height:1.1;margin-bottom:20px}
.hero h1 span{background:var(--gp);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.hero .sub{font-size:clamp(1rem,2.2vw,1.25rem);color:var(--t2);max-width:580px;margin:0 auto 40px;line-height:1.7}
.hero .sub strong{color:var(--t1)}
.cta-group{display:flex;gap:16px;flex-wrap:wrap;justify-content:center}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:14px 36px;border-radius:12px;font-size:1rem;font-weight:600;border:none;cursor:pointer;transition:all .25s;font-family:var(--sans)}
.btn-primary{background:var(--gp);color:white;box-shadow:0 4px 30px rgba(155,89,252,.25)}
.btn-primary:hover{transform:translateY(-2px);box-shadow:0 8px 40px rgba(155,89,252,.35);filter:brightness(1.1)}
.btn-secondary{background:transparent;color:var(--p);border:1px solid var(--bd)}
.btn-secondary:hover{border-color:var(--p);background:rgba(155,89,252,.05)}

/* Highlights */
.highlights{max-width:1100px;margin:0 auto;display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}
.hl{display:flex;gap:16px;align-items:flex-start;background:linear-gradient(145deg,var(--bg2) 0%,rgba(20,20,46,.8) 100%);border:1px solid var(--bd);border-radius:16px;padding:26px;transition:all .35s cubic-bezier(.25,.8,.25,1);transform:perspective(600px) rotateY(0);position:relative;overflow:hidden}
.hl::before{content:'';position:absolute;top:0;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,rgba(155,89,252,.3),rgba(74,158,255,.3),transparent);opacity:0;transition:opacity .3s}
.hl:hover{border-color:rgba(155,89,252,.35);transform:perspective(600px) rotateY(-1.5deg) translateY(-4px);box-shadow:0 20px 48px rgba(0,0,0,.4),0 0 24px rgba(155,89,252,.08)}
.hl:hover::before{opacity:1}
.hl-icon{flex-shrink:0;width:50px;height:50px;display:flex;align-items:center;justify-content:center;background:linear-gradient(135deg,rgba(155,89,252,.1),rgba(74,158,255,.08));border:1px solid rgba(155,89,252,.15);border-radius:14px;transition:all .3s}
.hl:hover .hl-icon{border-color:rgba(155,89,252,.4);box-shadow:0 0 16px rgba(155,89,252,.15)}
.hl-icon svg{width:26px;height:26px}
.hl-title{font-size:1.02rem;font-weight:700;margin-bottom:5px}
.hl-desc{font-size:.88rem;color:var(--t2);line-height:1.65}
/* Platform logos strip */
.platforms{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px;align-items:center}
.plat{width:38px;height:38px;display:flex;align-items:center;justify-content:center;background:linear-gradient(135deg,rgba(155,89,252,.05),rgba(74,158,255,.05));border:1px solid rgba(100,100,180,.15);border-radius:10px;transition:all .35s cubic-bezier(.25,.8,.25,1);cursor:default;position:relative}
.plat:hover{transform:translateY(-3px) scale(1.08);border-color:rgba(155,89,252,.5);background:linear-gradient(135deg,rgba(155,89,252,.12),rgba(74,158,255,.08));box-shadow:0 8px 24px rgba(0,0,0,.4),0 0 12px rgba(155,89,252,.15)}
.plat svg{width:20px;height:20px;opacity:.7;transition:opacity .3s}
.plat:hover svg{opacity:1}
.plat-label{font-size:.65rem;color:var(--tm);margin-left:2px}

/* Sections */
.section{padding:80px 20px;max-width:1100px;margin:0 auto;position:relative;z-index:1}
.section h2{font-size:2rem;font-weight:700;text-align:center;margin-bottom:56px}
.section h2 span{background:var(--gp);-webkit-background-clip:text;-webkit-text-fill-color:transparent}

/* Steps */
.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:24px}
.step{background:linear-gradient(145deg,var(--bg2) 0%,rgba(20,20,46,.8) 100%);border:1px solid var(--bd);border-radius:16px;padding:32px;transition:all .3s;transform:perspective(800px) rotateY(0deg)}
.step:hover{border-color:rgba(155,89,252,.4);transform:perspective(800px) rotateY(-2deg) translateY(-4px);box-shadow:0 20px 40px rgba(0,0,0,.3),0 0 30px rgba(155,89,252,.08)}
.step-num{width:44px;height:44px;background:var(--gp);border-radius:12px;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:1.1rem;margin-bottom:16px;box-shadow:0 4px 16px rgba(155,89,252,.3)}
.step h3{font-size:1.15rem;font-weight:600;margin-bottom:8px}
.step p{color:var(--t2);line-height:1.6;font-size:.95rem}

/* 3D Feature Cards */
.features{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:20px;perspective:1200px}
.feature{background:linear-gradient(145deg,var(--bg2) 0%,rgba(20,20,46,.8) 100%);border:1px solid var(--bd);border-radius:16px;padding:28px;position:relative;overflow:hidden;transition:all .4s cubic-bezier(.25,.8,.25,1);transform-style:preserve-3d;transform:perspective(800px) rotateX(0deg) rotateY(0deg)}
.feature::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:var(--gp);opacity:0;transition:opacity .3s}
.feature::after{content:'';position:absolute;inset:0;background:radial-gradient(circle at var(--mx,50%) var(--my,50%),rgba(155,89,252,.06),transparent 60%);opacity:0;transition:opacity .3s;pointer-events:none}
.feature:hover{border-color:rgba(155,89,252,.3);transform:perspective(800px) rotateX(var(--rx,0deg)) rotateY(var(--ry,0deg)) translateZ(10px);box-shadow:0 25px 50px rgba(0,0,0,.4),0 0 40px rgba(155,89,252,.06)}
.feature:hover::before{opacity:1}
.feature:hover::after{opacity:1}
.feature h4{font-size:1rem;font-weight:600;margin-bottom:6px;background:var(--gp);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.feature p{color:var(--t2);font-size:.9rem;line-height:1.5}

/* Pricing */
.price-card{max-width:480px;margin:0 auto;background:var(--bg2);border:2px solid transparent;border-image:var(--gp) 1;border-radius:0;position:relative;padding:44px;text-align:center}
.price-wrap{border-radius:20px;overflow:hidden;max-width:480px;margin:0 auto;border:2px solid rgba(155,89,252,.3);background:var(--bg2)}
.price-inner{padding:44px}
.price{font-size:3.5rem;font-weight:800;background:var(--gp);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.price-sub{color:var(--t2);margin-bottom:24px;font-size:.95rem}
.price-list{text-align:left;list-style:none;margin:24px 0}
.price-list li{padding:10px 0;border-bottom:1px solid var(--bd);font-size:.95rem;display:flex;align-items:center;gap:10px}
.price-list li::before{content:'';width:18px;height:18px;background:var(--gp);border-radius:50%;flex-shrink:0;display:flex;align-items:center;justify-content:center}

.footer{text-align:center;padding:40px 20px;color:var(--tm);font-size:.85rem;border-top:1px solid var(--bd);position:relative;z-index:1}
.footer img{height:32px;margin-bottom:8px;opacity:.5}

@media(max-width:640px){.cta-group{flex-direction:column;align-items:center}.hero h1{font-size:2.2rem}.hero-logo{height:80px}}
</style>
</head>
<body>

<section class="hero">
  <img src="/static/brand/logo.png" alt="Clow" class="hero-logo">
  <div class="lens-flare"></div>
  <p class="tagline">INTELIG&Ecirc;NCIA INFINITA &bull; POSSIBILIDADES PREMIUM</p>
  <h1>O agente de c&oacute;digo AI<br>mais <span>completo</span> do Brasil</h1>
  <p class="sub">24 tools &bull; 108 skills &bull; 5 agentes &bull; 16 integra&ccedil;&otilde;es &bull; 10 geradores &bull; 6 interfaces.<br><strong>Traga sua API key</strong> e use sem limites. Voc&ecirc; s&oacute; paga o que usar.</p>
  <div class="cta-group">
    <a href="/onboarding" class="btn btn-primary">Come&ccedil;ar Gr&aacute;tis</a>
    <a href="#como-funciona" class="btn btn-secondary">Como funciona</a>
  </div>
</section>

<!-- Highlights -->
<section style="padding:0 20px 40px;position:relative;z-index:1">
  <div class="highlights">
    <div class="hl"><div class="hl-icon"><svg viewBox="0 0 24 24" fill="none" stroke="url(#g1)" stroke-width="2"><defs><linearGradient id="g1" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#9B59FC"/><stop offset="100%" stop-color="#4A9EFF"/></linearGradient></defs><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></svg></div><div><div class="hl-title">Funciona em qualquer lugar</div><div class="hl-desc">Terminal, VS Code, navegador, celular. Comece no PC, continue no celular. Teleport transfere sua sess&atilde;o entre dispositivos.</div><div class="platforms">
      <div class="plat" title="VS Code"><svg viewBox="0 0 100 100" fill="#0078d4"><path d="M71.6 99.1l23.3-11.3c2.7-1.3 4.4-4 4.4-7V19.2c0-3-1.7-5.7-4.4-7L71.6.9c-3.5-1.7-7.6-.4-9.7 2.7L29.2 42.7 12.1 29.6c-2.1-1.6-5-1.5-7 .3l-3.6 3.3c-2.3 2.1-2.3 5.7 0 7.8L17.3 50 1.5 59c-2.3 2.1-2.3 5.7 0 7.8l3.6 3.3c2 1.8 4.9 1.9 7 .3l17.1-13.1 32.7 39.1c2.1 3.1 6.2 4.4 9.7 2.7zM71.6 27L43.5 50l28.1 23V27z"/></svg></div>
      <div class="plat" title="GitHub"><svg viewBox="0 0 24 24" fill="#fff"><path d="M12 .3a12 12 0 00-3.8 23.4c.6.1.8-.3.8-.6v-2.2c-3.3.7-4-1.6-4-1.6-.5-1.4-1.3-1.7-1.3-1.7-1.1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1.1 1.8 2.8 1.3 3.5 1 .1-.8.4-1.3.7-1.6-2.7-.3-5.5-1.3-5.5-5.9 0-1.3.5-2.4 1.2-3.2-.1-.3-.5-1.5.1-3.2 0 0 1-.3 3.3 1.2a11.5 11.5 0 016 0c2.3-1.5 3.3-1.2 3.3-1.2.6 1.7.2 2.9.1 3.2.8.8 1.2 1.9 1.2 3.2 0 4.6-2.8 5.6-5.5 5.9.4.4.8 1.1.8 2.2v3.3c0 .3.2.7.8.6A12 12 0 0012 .3"/></svg></div>
      <div class="plat" title="Google Chrome"><svg viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="4.5" fill="#fff"/><path d="M12 7.5A4.5 4.5 0 007.5 12H1.6A10.5 10.5 0 0112 1.5a10.5 10.5 0 019.2 5.4L16.3 14" fill="#db4437"/><path d="M16.5 12a4.5 4.5 0 01-2.3 3.9l-5 8.6A10.5 10.5 0 011.6 12h5.9" fill="#0f9d58"/><path d="M14.2 15.9a4.5 4.5 0 01-6.7-2.4l-5-8.6a10.5 10.5 0 0118.7.5h-5.9" fill="#ffcd40"/><path d="M7.5 12A4.5 4.5 0 009.8 15.9l-5 8.6A10.5 10.5 0 011.6 12z" fill="#4285f4"/></svg></div>
      <div class="plat" title="Android"><svg viewBox="0 0 24 24" fill="#3DDC84"><path d="M6 18c0 .55.45 1 1 1h1v3.5c0 .83.67 1.5 1.5 1.5s1.5-.67 1.5-1.5V19h2v3.5c0 .83.67 1.5 1.5 1.5s1.5-.67 1.5-1.5V19h1c.55 0 1-.45 1-1V8H6v10zM3.5 8C2.67 8 2 8.67 2 9.5v7c0 .83.67 1.5 1.5 1.5S5 17.33 5 16.5v-7C5 8.67 4.33 8 3.5 8zm17 0c-.83 0-1.5.67-1.5 1.5v7c0 .83.67 1.5 1.5 1.5s1.5-.67 1.5-1.5v-7c0-.83-.67-1.5-1.5-1.5zM15.53 2.16l1.3-1.3c.2-.2.2-.51 0-.71-.2-.2-.51-.2-.71 0l-1.48 1.48A5.96 5.96 0 0012 1c-.96 0-1.86.23-2.66.63L7.85.15c-.2-.2-.51-.2-.71 0-.2.2-.2.51 0 .71l1.31 1.31A5.98 5.98 0 006 6.5V7h12v-.5c0-1.85-.84-3.5-2.16-4.6l-.31-.24zM10 5H9V4h1v1zm5 0h-1V4h1v1z"/></svg></div>
      <div class="plat" title="Apple"><svg viewBox="0 0 24 24" fill="#fff"><path d="M18.71 19.5c-.83 1.24-1.71 2.45-3.05 2.47-1.34.03-1.77-.79-3.29-.79-1.53 0-2 .77-3.27.82-1.31.05-2.3-1.32-3.14-2.53C4.25 17 2.94 12.45 4.7 9.39c.87-1.52 2.43-2.48 4.12-2.51 1.28-.02 2.5.87 3.29.87.78 0 2.26-1.07 3.8-.91.65.03 2.47.26 3.64 1.98-.09.06-2.17 1.28-2.15 3.81.03 3.02 2.65 4.03 2.68 4.04-.03.07-.42 1.44-1.38 2.83M13 3.5c.73-.83 1.94-1.46 2.94-1.5.13 1.17-.34 2.35-1.04 3.19-.69.85-1.83 1.51-2.95 1.42-.15-1.15.41-2.35 1.05-3.11z"/></svg></div>
    </div></div></div>
    <div class="hl"><div class="hl-icon"><svg viewBox="0 0 24 24" fill="none" stroke="url(#g1)" stroke-width="2"><path d="M9.66 2L4.23 12.11l5.43 3.13L20.77 2z"/><path d="M20.77 2l-11.1 13.24L4.22 12.1"/><path d="M9.66 15.24v6.65l5.22-3.57"/></svg></div><div><div class="hl-title">Intelig&ecirc;ncia de ponta</div><div class="hl-desc">Claude Sonnet 4 com Extended Thinking. O mesmo modelo que alimenta as maiores plataformas de AI coding do mundo. Pensa antes de agir.</div><div class="platforms">
      <div class="plat" title="Anthropic"><svg viewBox="0 0 24 24" fill="#D4A574"><path d="M13.83 2l6.07 20h-4.15l-1.58-5.33H6.99L5.41 22H1.27L7.83 2h6zm-1.45 11.33L10.5 7.6l-1.88 5.73h3.76z"/></svg></div>
    </div></div></div>
    <div class="hl"><div class="hl-icon"><svg viewBox="0 0 24 24" fill="none" stroke="url(#g1)" stroke-width="2"><rect x="5" y="2" width="14" height="20" rx="3"/><path d="M12 18h.01"/></svg></div><div><div class="hl-title">Dev completo no bolso</div><div class="hl-desc">Crie apps, landing pages, APIs, planilhas, PDFs, apresenta&ccedil;&otilde;es. Tudo pelo celular via PWA. Instala como app nativo em 10 segundos.</div><div class="platforms">
      <div class="plat" title="HTML5"><svg viewBox="0 0 24 24" fill="#E34F26"><path d="M1.5 0h21l-1.91 21.56L11.97 24l-8.66-2.44zm7.64 9.88l-.2-2.27h7.84l.6-2.7H6.27l.6 6.7h8.36l-.36 3.63-2.9.78-2.87-.78-.18-2.07H6.4l.36 4.03L12 19.48l5.18-1.47.72-8.13z"/></svg></div>
      <div class="plat" title="Microsoft Excel"><svg viewBox="0 0 24 24" fill="#217346"><path d="M23 1.5v21c0 .28-.22.5-.5.5h-9V1h9c.28 0 .5.22.5.5zM1.5 3L10 1.5v21L1.5 21c-.28 0-.5-.22-.5-.5v-17c0-.28.22-.5.5-.5zM7.8 8.4L5.85 12l1.95 3.6H6.08l-1.1-2.28L3.88 15.6H2.2L4.15 12 2.2 8.4h1.68l1.1 2.16L6.08 8.4z"/></svg></div>
      <div class="plat" title="PDF"><svg viewBox="0 0 24 24" fill="#FF0000"><path d="M20 2H8c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-8.5 7.5c0 .83-.67 1.5-1.5 1.5H9v2H7.5V7H10c.83 0 1.5.67 1.5 1.5v1zm5 2c0 .83-.67 1.5-1.5 1.5h-2.5V7H15c.83 0 1.5.67 1.5 1.5v3zm4-3.5H19V9h1.5V7.5H19V7h1.5V5.5h-3V13h1.5V10.5H20V9.5zM9 9.5h1V8H9v1.5zM4 6H2v14c0 1.1.9 2 2 2h14v-2H4V6zm10 5.5h1v-3h-1v3z"/></svg></div>
      <div class="plat" title="PowerPoint"><svg viewBox="0 0 24 24" fill="#D24726"><path d="M13.5 1.5v21L1.5 21V3l12-1.5zm-1.7 6.7H8.45V16h1.7v-2.88h1.48c1.62 0 2.87-.95 2.87-2.6 0-1.55-1.15-2.32-2.7-2.32zm-.18 3.5H10.15V9.82h1.47c.77 0 1.25.38 1.25 1 0 .6-.48.88-1.25.88zM22.5 1.5v21h-8V21h6.5V3H14.5V1.5z"/></svg></div>
    </div></div></div>
    <div class="hl"><div class="hl-icon"><svg viewBox="0 0 24 24" fill="none" stroke="#F59E0B" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="3"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg></div><div><div class="hl-title">Automa&ccedil;&otilde;es em portugu&ecirc;s</div><div class="hl-desc">&ldquo;Todo dia &agrave;s 8h verifica minhas issues&rdquo; &mdash; diga o que quer e o Clow cria a automa&ccedil;&atilde;o. Sem c&oacute;digo, sem config, s&oacute; linguagem natural.</div><div class="platforms">
      <div class="plat" title="GitHub"><svg viewBox="0 0 24 24" fill="#fff"><path d="M12 .3a12 12 0 00-3.8 23.4c.6.1.8-.3.8-.6v-2.2c-3.3.7-4-1.6-4-1.6-.5-1.4-1.3-1.7-1.3-1.7-1.1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1.1 1.8 2.8 1.3 3.5 1 .1-.8.4-1.3.7-1.6-2.7-.3-5.5-1.3-5.5-5.9 0-1.3.5-2.4 1.2-3.2-.1-.3-.5-1.5.1-3.2 0 0 1-.3 3.3 1.2a11.5 11.5 0 016 0c2.3-1.5 3.3-1.2 3.3-1.2.6 1.7.2 2.9.1 3.2.8.8 1.2 1.9 1.2 3.2 0 4.6-2.8 5.6-5.5 5.9.4.4.8 1.1.8 2.2v3.3c0 .3.2.7.8.6A12 12 0 0012 .3"/></svg></div>
      <div class="plat" title="WhatsApp"><svg viewBox="0 0 24 24" fill="#25D366"><path d="M17.47 14.38c-.29-.14-1.7-.84-1.96-.93s-.46-.15-.65.14c-.19.3-.74.93-.91 1.12s-.33.22-.62.07c-.29-.14-1.22-.45-2.33-1.43-.86-.77-1.44-1.72-1.61-2.01s-.02-.45.13-.59c.13-.13.29-.33.43-.5.15-.17.19-.29.29-.48s.05-.36-.02-.5c-.07-.15-.65-1.56-.89-2.14-.24-.56-.48-.48-.65-.49h-.56c-.19 0-.5.07-.77.36s-1.01.99-1.01 2.41 1.04 2.81 1.18 3c.15.19 2.04 3.12 4.94 4.38.69.3 1.23.48 1.65.61.69.22 1.32.19 1.82.12.55-.08 1.7-.7 1.94-1.37s.24-1.25.17-1.37c-.07-.12-.27-.19-.56-.34zM12 2a10 10 0 00-8.68 14.95L2 22l5.23-1.37A10 10 0 1012 2z"/></svg></div>
      <div class="plat" title="Docker"><svg viewBox="0 0 24 24" fill="#2496ED"><path d="M13.98 11.08h2.12V8.9h-2.12v2.18zm-2.74 0h2.12V8.9h-2.12v2.18zm-2.74 0h2.12V8.9H8.5v2.18zm-2.74 0h2.12V8.9H5.76v2.18zm2.74-2.74h2.12V6.16H8.5v2.18zm2.74 0h2.12V6.16h-2.12v2.18zm2.74 0h2.12V6.16h-2.12v2.18zM8.5 5.6h2.12V3.42H8.5V5.6zm2.74 0h2.12V3.42h-2.12V5.6zm10.04 4.26c-.6-.4-1.96-.55-3-.34-.14-.98-.69-1.82-1.35-2.58l-.46-.4-.38.46c-.48.58-.75 1.37-.68 2.14.04.35.16.97.52 1.52-.36.2-1.08.48-2.02.46H.73l-.07.47c-.18 1.15-.18 4.74 2.7 7.5 2.14 2.05 5.35 3.1 9.54 3.1 9.09 0 15.82-4.2 18.98-11.82.62.01 1.95.01 2.63-1.3l.13-.24-.42-.28z"/></svg></div>
      <div class="plat" title="n8n"><svg viewBox="0 0 24 24" fill="#EA4B71"><path d="M12.87 5.98c0-.7-.57-1.27-1.27-1.27H5.98c-.7 0-1.27.57-1.27 1.27v5.62c0 .7.57 1.27 1.27 1.27h5.62c.7 0 1.27-.57 1.27-1.27V5.98zm6.42 6.42c0-.7-.57-1.27-1.27-1.27h-5.62c-.7 0-1.27.57-1.27 1.27v5.62c0 .7.57 1.27 1.27 1.27h5.62c.7 0 1.27-.57 1.27-1.27V12.4z"/></svg></div>
    </div></div></div>
    <div class="hl"><div class="hl-icon"><svg viewBox="0 0 24 24" fill="none" stroke="url(#g1)" stroke-width="2"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75"/></svg></div><div><div class="hl-title">5 agentes trabalhando juntos</div><div class="hl-desc">Architect planeja, Developer implementa, Tester valida, Reviewer revisa. Ou use Swarm para tarefas brutais em paralelo com git worktrees.</div></div></div>
    <div class="hl"><div class="hl-icon"><svg viewBox="0 0 24 24" fill="none" stroke="#34D399" stroke-width="2"><path d="M12 1v22M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/></svg></div><div><div class="hl-title">R$ 0 &mdash; voc&ecirc; s&oacute; paga a API</div><div class="hl-desc">Sem assinatura, sem mensalidade, sem surpresas. Voc&ecirc; paga direto pra Anthropic o que consumir. M&eacute;dia: R$ 0,05 a R$ 0,25 por mensagem.</div></div></div>
  </div>
</section>

<section class="section" id="como-funciona">
  <h2>Como <span>funciona</span></h2>
  <div class="steps">
    <div class="step"><div class="step-num">1</div><h3>Crie sua conta</h3><p>Email e senha. Sem cart&atilde;o de cr&eacute;dito. 30 segundos.</p></div>
    <div class="step"><div class="step-num">2</div><h3>Cole sua API Key</h3><p>Pegue sua key em <strong>console.anthropic.com</strong>. O Clow valida na hora.</p></div>
    <div class="step"><div class="step-num">3</div><h3>Use sem limites</h3><p>24 tools, auto-correction, extended thinking, agent teams, e muito mais. Voc&ecirc; paga direto pra Anthropic.</p></div>
  </div>
</section>

<section class="section">
  <h2>Uma plataforma <span>completa</span></h2>
  <p style="text-align:center;color:var(--t2);margin:-40px auto 48px;max-width:600px;font-size:1.05rem">24 ferramentas, 108 skills, 5 tipos de agente, 16 integra&ccedil;&otilde;es, 10 geradores de conte&uacute;do. Tudo em 6 interfaces diferentes.</p>

  <div class="features" id="features-grid">
    <div class="feature"><h4>24 Ferramentas Nativas</h4><p>Bash, Read, Write, Edit, Glob, Grep, Web Search, Web Fetch, Scraper, Image Gen, PDF, Spreadsheet, Notebook, WhatsApp, HTTP Request, Supabase, n8n, Docker, Git Advanced e mais. Cada tool com permiss&otilde;es granulares.</p></div>
    <div class="feature"><h4>108 Skills Prontos</h4><p>46 skills nativos + 62 importados cobrindo: /commit, /review, /test, /deploy, /debug, /plan, /security, /perf, /docs, /migrate, /pr, /changelog, /scaffold, /cotacao, /proposta, /relatorio, /ads, /leads, /monitor, /backup e dezenas mais.</p></div>
    <div class="feature"><h4>5 Tipos de Agente</h4><p><strong>Agent</strong> (principal), <strong>Swarm</strong> (paralelo com worktrees git), <strong>Teams</strong> (Architect + Developer + Tester + Reviewer com task board), <strong>Mission Engine</strong> (aut&ocirc;nomo multi-step), <strong>Background</strong> (assync).</p></div>
    <div class="feature"><h4>16 Integra&ccedil;&otilde;es</h4><p>GitHub, Meta Ads, Supabase, PostgreSQL, Redis, n8n, Docker, Vercel, Stripe, Mercado Pago, WhatsApp (Z-API), Chatwoot, Browser (Playwright), Voice, Multi-Agent Coordination e Messaging Bridge.</p></div>
    <div class="feature"><h4>10 Geradores de Conte&uacute;do</h4><p>Landing pages completas, apps web, planilhas Excel, apresenta&ccedil;&otilde;es PowerPoint, documentos Word, PDFs profissionais, imagens AI, copies de marketing, ideias de conte&uacute;do e dispatchers inteligentes.</p></div>
    <div class="feature"><h4>GitHub Autopilot</h4><p>Adicione label &ldquo;clow&rdquo; em qualquer issue e o agente cria branch, implementa a solu&ccedil;&atilde;o, roda testes, e abre PR automaticamente com &ldquo;closes #N&rdquo;. Se falhar, comenta diagn&oacute;stico na issue.</p></div>
    <div class="feature"><h4>Automa&ccedil;&otilde;es em Portugu&ecirc;s</h4><p>Diga &ldquo;todo dia &agrave;s 8h verifica issues abertas e me manda resumo no WhatsApp&rdquo; e o Clow cria a automa&ccedil;&atilde;o completa. Suporta cron, webhooks, eventos GitHub e monitoramento de arquivos.</p></div>
    <div class="feature"><h4>Time Travel &amp; Checkpoints</h4><p>Checkpoints autom&aacute;ticos antes de cada modifica&ccedil;&atilde;o. /undo reverte qualquer passo. /history mostra timeline completa. Diff visual antes de restaurar. At&eacute; 50 checkpoints por sess&atilde;o.</p></div>
    <div class="feature"><h4>Extended Thinking</h4><p>Em tarefas complexas de arquitetura, debug e refatora&ccedil;&atilde;o, o modelo &ldquo;pensa&rdquo; internamente com budget de 10.000 tokens antes de responder. Mesma tecnologia do Claude Pro.</p></div>
    <div class="feature"><h4>Self-Learning</h4><p>Analisa seus padr&otilde;es: corre&ccedil;&otilde;es, sequ&ecirc;ncias de tools, erros recorrentes. Gera regras preventivas autom&aacute;ticas. Fica mais inteligente a cada sess&atilde;o, sem voc&ecirc; precisar configurar nada.</p></div>
    <div class="feature"><h4>6 Interfaces</h4><p><strong>Terminal</strong> (pip install clow), <strong>Web</strong> (navegador), <strong>VS Code</strong> (extens&atilde;o), <strong>PWA</strong> (Android/iPhone), <strong>Chrome Extension</strong> (em qualquer p&aacute;gina), <strong>WebSocket</strong> (tempo real). Teleport transfere sess&atilde;o entre elas.</p></div>
    <div class="feature"><h4>Spectator Mode</h4><p>Compartilhe uma URL e qualquer pessoa pode assistir o agente trabalhando ao vivo: tool calls, respostas, diffs de arquivos em tempo real. Split-screen terminal + c&oacute;digo. Controle remoto com bot&atilde;o de aprova&ccedil;&atilde;o.</p></div>
  </div>
</section>

<section class="section">
  <h2>Quanto <span>custa</span></h2>
  <div class="price-wrap">
    <div class="price-inner">
      <div class="price">R$ 0</div>
      <div class="price-sub">O Clow &eacute; 100%% gr&aacute;tis. Voc&ecirc; s&oacute; paga a API da Anthropic.</div>
      <ul class="price-list">
        <li>Acesso completo a todas as features</li>
        <li>Sem limite de mensagens</li>
        <li>Sem limite de sess&otilde;es</li>
        <li>Dashboard de uso com custo estimado em USD</li>
        <li>Custo m&eacute;dio: ~$0.01 a $0.05 por mensagem</li>
        <li>Voc&ecirc; controla tudo no console.anthropic.com</li>
      </ul>
      <a href="/onboarding" class="btn btn-primary" style="margin-top:24px;width:100%">Criar Conta Gr&aacute;tis</a>
    </div>
  </div>
</section>

<footer class="footer">
  <img src="/static/brand/logo-sidebar.png" alt="Clow">
  <p>Clow AI &mdash; Intelig&ecirc;ncia Infinita &bull; Possibilidades Premium</p>
</footer>

<script>
// 3D tilt effect on feature cards
document.querySelectorAll('.feature').forEach(card=>{
  card.addEventListener('mousemove',e=>{
    const r=card.getBoundingClientRect();
    const x=(e.clientX-r.left)/r.width;
    const y=(e.clientY-r.top)/r.height;
    const ry=(x-.5)*12;
    const rx=(y-.5)*-12;
    card.style.setProperty('--rx',rx+'deg');
    card.style.setProperty('--ry',ry+'deg');
    card.style.setProperty('--mx',(x*100)+'%');
    card.style.setProperty('--my',(y*100)+'%');
  });
  card.addEventListener('mouseleave',()=>{
    card.style.setProperty('--rx','0deg');
    card.style.setProperty('--ry','0deg');
  });
});
// Scroll-in animation
const obs=new IntersectionObserver(entries=>{
  entries.forEach(e=>{if(e.isIntersecting){e.target.style.opacity='1';e.target.style.transform='perspective(800px) rotateX(0) rotateY(0) translateY(0)'}});
},{threshold:.1});
document.querySelectorAll('.feature,.step').forEach(el=>{
  el.style.opacity='0';el.style.transform='perspective(800px) translateY(30px)';
  el.style.transition='all .6s cubic-bezier(.25,.8,.25,1)';
  obs.observe(el);
});
</script>
</body>
</html>'''


def _onboarding_html() -> str:
    return """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Clow — Configurar</title>
<link rel="icon" type="image/png" href="/static/brand/favicon.png">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#050510;--bg2:#0F0F24;--bg3:#14142E;--bd:rgba(100,100,180,.12);--bdf:rgba(155,89,252,.5);--p:#9B59FC;--bl:#4A9EFF;--gp:linear-gradient(135deg,#9B59FC 0%,#4A9EFF 100%);--pg:rgba(155,89,252,.15);--r:#F87171;--rd:rgba(248,113,113,.1);--g:#34D399;--gd:rgba(52,211,153,.1);--t1:#E8E8F0;--t2:#9898B8;--tm:#585878;--sans:'DM Sans',sans-serif;--mono:'JetBrains Mono',monospace}
body{font-family:var(--sans);background:var(--bg);color:var(--t1);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px;-webkit-font-smoothing:antialiased}
body::after{content:'';position:fixed;inset:0;pointer-events:none;background:radial-gradient(ellipse at 50% 40%,rgba(155,89,252,.08),rgba(74,158,255,.04) 30%,transparent 60%)}
.container{width:100%;max-width:440px;position:relative;z-index:1}
.card{background:var(--bg2);border:1px solid var(--bd);border-radius:20px;padding:44px 36px;box-shadow:0 30px 60px rgba(0,0,0,.5),0 0 60px rgba(155,89,252,.05);animation:fadeIn .4s ease-out}
@keyframes fadeIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
.logo{text-align:center;margin-bottom:20px}
.logo img{height:80px;filter:drop-shadow(0 0 24px rgba(155,89,252,.25)) drop-shadow(0 0 24px rgba(74,158,255,.15));animation:float 4s ease-in-out infinite}
@keyframes float{0%,100%{transform:translateY(0)}50%{transform:translateY(-5px)}}
.lens{width:180px;height:1px;margin:10px auto 16px;background:linear-gradient(90deg,transparent,rgba(155,89,252,.5),rgba(74,158,255,.5),transparent);box-shadow:0 0 10px rgba(155,89,252,.3)}
h1{font-size:1.4rem;font-weight:700;text-align:center;margin-bottom:4px}
.sub{color:var(--t2);text-align:center;margin-bottom:28px;font-size:.92rem}
.step{display:none}.step.active{display:block}
.progress{display:flex;gap:8px;justify-content:center;margin-bottom:24px}
.dot{width:10px;height:10px;border-radius:50%;background:var(--bd);transition:all .3s}
.dot.active{background:var(--p);box-shadow:0 0 8px rgba(155,89,252,.5)}
.dot.done{background:var(--g);box-shadow:0 0 8px rgba(52,211,153,.5)}
.fg{margin-bottom:16px}
.fg label{display:block;font-size:10px;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:var(--tm);margin-bottom:6px}
.fg input{width:100%;padding:12px 14px;background:var(--bg3);border:1px solid var(--bd);border-radius:10px;color:var(--t1);font-family:var(--sans);font-size:14px;outline:none;transition:all .2s}
.fg input:focus{border-color:var(--bdf);box-shadow:0 0 20px rgba(155,89,252,.08)}
.fg input::placeholder{color:var(--tm);font-weight:300}
.fg input.mono{font-family:var(--mono);font-size:13px}
.btn{width:100%;padding:14px;border:none;border-radius:10px;font-size:15px;font-weight:600;cursor:pointer;transition:all .2s;margin-top:8px;font-family:var(--sans)}
.btn-primary{background:var(--gp);color:white}.btn-primary:hover{box-shadow:0 0 30px var(--pg);filter:brightness(1.1)}.btn-primary:active{transform:scale(.98)}.btn-primary:disabled{opacity:.5;cursor:not-allowed;transform:none;filter:none}
.msg{padding:12px;border-radius:8px;font-size:.88rem;margin-top:12px;display:none;line-height:1.5}
.msg.error{display:block;background:var(--rd);border:1px solid rgba(248,113,113,.15);color:var(--r)}
.msg.success{display:block;background:var(--gd);border:1px solid rgba(52,211,153,.15);color:var(--g)}
.msg.info{display:block;background:var(--pg);border:1px solid rgba(155,89,252,.15);color:var(--p)}
.spinner{display:inline-block;width:16px;height:16px;border:2px solid rgba(255,255,255,.3);border-top-color:white;border-radius:50%;animation:spin .6s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.link{color:var(--p);cursor:pointer;font-size:.9rem;text-align:center;display:block;margin-top:16px;transition:color .2s}.link:hover{color:var(--bl)}
.icard{background:var(--bg3);border:1px solid var(--bd);border-radius:12px;padding:16px;margin-bottom:12px;display:flex;gap:14px;transition:border-color .2s}
.icard:hover{border-color:rgba(155,89,252,.3)}
.inum{width:28px;height:28px;background:var(--gp);border-radius:8px;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:.85rem;flex-shrink:0;margin-top:2px}
.ititle{font-size:.95rem;font-weight:600;margin-bottom:4px;background:var(--gp);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.idesc{font-size:.85rem;color:var(--t2);line-height:1.5}
.icode{background:var(--bg);border-radius:8px;padding:10px 12px;margin-top:8px}
.icode pre{font-family:var(--mono);font-size:.8rem;color:var(--p);white-space:pre-wrap;margin:0;line-height:1.6}
.icode-label{font-size:.72rem;color:var(--tm);text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px}
.inote{font-size:.78rem;color:var(--tm);margin-top:6px;line-height:1.5}
</style>
</head>
<body>
<div class="container">
<div class="card">
  <div class="logo"><img src="/static/brand/logo.png" alt="Clow"></div>
  <div class="lens"></div>
  <h1>Configurar Clow</h1>
  <div class="progress"><div class="dot active" id="d1"></div><div class="dot" id="d2"></div><div class="dot" id="d3"></div></div>


  <div class="step active" id="step1">
    <p class="sub">Crie sua conta em 30 segundos</p>
    <div class="fg"><label>Nome completo</label><input id="name" placeholder="Nome e Sobrenome" required></div>
    <div class="fg"><label>Email</label><input id="email" type="email" placeholder="seu@email.com" required></div>
    <div class="fg"><label>Senha</label><input id="password" type="password" placeholder="m&iacute;nimo 6 caracteres" required></div>
    <button class="btn btn-primary" onclick="signup()">Criar Conta</button>
    <a class="link" href="/login">J&aacute; tenho conta</a>
    <div class="msg" id="msg1"></div>
  </div>

  <div class="step" id="step2">
    <p class="sub">Cole sua API key da Anthropic</p>
    <div class="fg"><label>API Key da Anthropic</label><input id="apikey" class="mono" placeholder="sk-ant-api03-..." required></div>
    <div style="font-size:.8rem;color:var(--t2);margin-bottom:16px;line-height:1.6">
      <p style="margin-bottom:8px"><strong style="color:var(--t1)">Como conseguir sua key:</strong></p>
      <p>1. Acesse <a href="https://console.anthropic.com/settings/keys" target="_blank" style="color:var(--p)">console.anthropic.com/settings/keys</a></p>
      <p>2. Clique em <strong>Create Key</strong> e copie</p>
      <p>3. Em <a href="https://console.anthropic.com/settings/billing" target="_blank" style="color:var(--p)">Billing</a>, adicione saldo m&iacute;nimo de <strong style="color:var(--g)">$5 USD</strong></p>
      <p style="margin-top:8px;color:var(--tm);font-size:.75rem">Sua key fica salva apenas no Clow. N&atilde;o &eacute; compartilhada com terceiros.</p>
    </div>
    <button class="btn btn-primary" onclick="saveKey()" id="btn-key">Validar e Salvar</button>
    <div class="msg" id="msg2"></div>
  </div>

  <div class="step" id="step3">
    <p class="sub" style="font-size:1.1rem;color:var(--g)">Tudo pronto, <span id="userName"></span>!</p>
    <div class="msg success" style="display:block;text-align:center;margin-bottom:20px">Sua conta est&aacute; ativa. Escolha como usar o Clow:</div>

    <div class="icard">
      <div class="inum">1</div>
      <div>
        <h3 class="ititle">Usar na Web</h3>
        <p class="idesc">Acesse direto no navegador, sem instalar nada.</p>
        <button class="btn btn-primary" onclick="goToClow()" style="padding:10px 20px;font-size:.9rem;width:auto;margin-top:8px">Abrir Clow Web</button>
      </div>
    </div>

    <div class="icard">
      <div class="inum">2</div>
      <div>
        <h3 class="ititle">Instalar no Terminal</h3>
        <p class="idesc">Use em qualquer projeto local ou na VPS.</p>
        <div class="icode">
          <div class="icode-label">No seu computador ou VPS:</div>
          <pre>pip install clow</pre>
        </div>
        <div class="icode">
          <div class="icode-label">Depois execute:</div>
          <pre>clow</pre>
        </div>
        <p class="inote">Na primeira vez, cole sua API key quando pedido.<br>Funciona em Windows, Mac e Linux.</p>
      </div>
    </div>

    <div class="icard">
      <div class="inum">3</div>
      <div>
        <h3 class="ititle">Usar no VS Code <span style="color:var(--g);font-size:.75rem">(recomendado)</span></h3>
        <p class="idesc">O Clow dentro do seu editor, como o Copilot.</p>
        <div class="icode">
          <div class="icode-label">Abra o terminal do VS Code (Ctrl+`) e rode:</div>
          <pre>pip install clow &amp;&amp; clow</pre>
        </div>
        <p class="inote">O Clow roda direto no terminal integrado do VS Code.<br>Ele l&ecirc; e edita os arquivos do seu projeto.</p>
      </div>
    </div>

    <div class="icard">
      <div class="inum">4</div>
      <div>
        <h3 class="ititle">Instalar no Celular (PWA)</h3>
        <p class="idesc">Use como app nativo no Android ou iPhone.</p>
        <div class="icode">
          <div class="icode-label">Android (Chrome):</div>
          <pre>1. Acesse clow.pvcorretor01.com.br
2. Toque no menu &#8942; (3 pontinhos)
3. Toque em &quot;Instalar aplicativo&quot;
4. Pronto! O Clow aparece na tela inicial</pre>
        </div>
        <div class="icode" style="margin-top:8px">
          <div class="icode-label">iPhone (Safari):</div>
          <pre>1. Acesse clow.pvcorretor01.com.br no Safari
2. Toque no bot&atilde;o Compartilhar (quadrado com seta)
3. Toque em &quot;Adicionar &agrave; Tela de In&iacute;cio&quot;
4. Toque em &quot;Adicionar&quot;</pre>
        </div>
      </div>
    </div>

    <a class="link" href="/usage">Ver meu dashboard de uso</a>
  </div>
</div>
</div>

<script>
let token='';
function $(id){return document.getElementById(id)}
function showStep(n){document.querySelectorAll('.step').forEach(s=>s.classList.remove('active'));$('step'+n).classList.add('active');for(let i=1;i<=3;i++){$('d'+i).className=i<n?'dot done':i===n?'dot active':'dot'}}
function showMsg(id,text,type){const el=$(id);el.className='msg '+type;el.textContent=text}

let userEmail='';
async function signup(){
  const name=$('name').value.trim(),email=$('email').value.trim(),password=$('password').value;
  if(!name)return showMsg('msg1','Informe seu nome completo','error');
  if(name.split(/\s+/).length<2)return showMsg('msg1','Informe nome e sobrenome','error');
  if(!email)return showMsg('msg1','Informe seu email','error');
  if(!email.includes('@')||!email.split('@')[1].includes('.'))return showMsg('msg1','Email invalido','error');
  if(!password)return showMsg('msg1','Crie uma senha','error');
  if(password.length<6)return showMsg('msg1','Senha deve ter pelo menos 6 caracteres','error');
  try{
    const r=await fetch('/api/v1/auth/signup',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({name,email,password})});
    const d=await r.json();
    if(d.error){
      if(d.action==='login'){
        $('msg1').className='msg error';
        $('msg1').innerHTML=d.error+' <a href="/login" style="color:var(--p);text-decoration:underline">Ir para o login</a>';
        return;
      }
      return showMsg('msg1',d.error,'error');
    }
    token=d.token;userEmail=email;showStep(2);
  }catch(e){showMsg('msg1','Erro de rede. Tente novamente.','error')}
}

async function saveKey(){
  const key=$('apikey').value.trim();
  if(!key)return showMsg('msg2','Cole sua API key','error');
  if(!key.startsWith('sk-ant-'))return showMsg('msg2','Key deve comecar com sk-ant-','error');
  $('btn-key').disabled=true;$('btn-key').innerHTML='<span class="spinner"></span> Validando...';showMsg('msg2','Validando key com a Anthropic...','info');
  try{const r=await fetch('/api/v1/me/api-key',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({api_key:key})});const d=await r.json();if(d.error){showMsg('msg2',d.error,'error');$('btn-key').disabled=false;$('btn-key').textContent='Validar e Salvar';return}const un=$('userName');if(un)un.textContent=userEmail.split('@')[0];showStep(3)}catch(e){showMsg('msg2','Erro de rede','error');$('btn-key').disabled=false;$('btn-key').textContent='Validar e Salvar'}
}

async function goToClow(){
  // Verifica que a sessao do usuario esta ativa antes de redirecionar
  try{
    const r=await fetch('/api/v1/me',{credentials:'same-origin'});
    const d=await r.json();
    if(d.error||!d.email){
      // Sessao invalida — faz login manual
      window.location='/login';
      return;
    }
    // Sessao valida — redireciona pro chat
    window.location='/';
  }catch(e){window.location='/login';}
  return;
}
</script>
</body>
</html>"""


def _usage_html() -> str:
    return """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Clow — Uso</title>
<link rel="icon" type="image/png" href="/static/brand/favicon.png">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#050510;--bg2:#0F0F24;--bd:rgba(100,100,180,.12);--p:#9B59FC;--bl:#4A9EFF;--gp:linear-gradient(135deg,#9B59FC,#4A9EFF);--g:#34D399;--t1:#E8E8F0;--t2:#9898B8;--tm:#585878;--sans:'DM Sans',sans-serif;--mono:'JetBrains Mono',monospace}
body{font-family:var(--sans);background:var(--bg);color:var(--t1);padding:20px;-webkit-font-smoothing:antialiased}
body::after{content:'';position:fixed;inset:0;pointer-events:none;background:radial-gradient(ellipse at 50% 20%,rgba(155,89,252,.06),transparent 50%)}
.container{max-width:800px;margin:0 auto;position:relative;z-index:1}
.nav{display:flex;align-items:center;gap:16px;margin-bottom:28px}
.nav img{height:28px;opacity:.7}
.nav a{color:var(--p);font-size:.9rem;transition:color .2s}.nav a:hover{color:var(--bl)}
h1{font-size:1.5rem;font-weight:700;margin-bottom:24px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px;margin-bottom:32px}
.stat{background:var(--bg2);border:1px solid var(--bd);border-radius:14px;padding:20px;transition:border-color .3s}
.stat:hover{border-color:rgba(155,89,252,.3)}
.stat-label{font-size:.75rem;color:var(--tm);text-transform:uppercase;letter-spacing:1px}
.stat-value{font-size:1.8rem;font-weight:700;margin-top:4px}
.stat-value.purple{background:var(--gp);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.stat-value.green{color:var(--g)}
table{width:100%;border-collapse:collapse;background:var(--bg2);border-radius:14px;overflow:hidden;border:1px solid var(--bd)}
th,td{padding:12px 16px;text-align:left;border-bottom:1px solid var(--bd)}
th{font-size:.75rem;color:var(--tm);text-transform:uppercase;font-weight:500;letter-spacing:.5px}
td{font-size:.9rem}
.mono{font-family:var(--mono);font-size:.85rem}
#loading{text-align:center;color:var(--tm);padding:40px}
.note{margin-top:16px;font-size:.8rem;color:var(--tm)}
</style>
</head>
<body>
<div class="container">
  <div class="nav"><img src="/static/brand/logo-sidebar.png" alt="Clow"><a href="/">Chat</a><a href="/usage">Uso</a><a href="/onboarding">Config</a></div>
  <h1>Dashboard de Uso</h1>
  <div id="loading">Carregando...</div>
  <div id="content" style="display:none">
    <div class="cards">
      <div class="stat"><div class="stat-label">Tokens Hoje</div><div class="stat-value purple" id="today-tokens">-</div></div>
      <div class="stat"><div class="stat-label">Custo Hoje</div><div class="stat-value green" id="today-cost">-</div></div>
      <div class="stat"><div class="stat-label">Mensagens</div><div class="stat-value" id="today-calls">-</div></div>
      <div class="stat"><div class="stat-label">Total Acumulado</div><div class="stat-value" id="total-tokens">-</div></div>
    </div>
    <h2 style="font-size:1.1rem;margin-bottom:12px">&Uacute;ltimos 7 dias</h2>
    <table><thead><tr><th>Data</th><th>Tokens In</th><th>Tokens Out</th><th>Custo (USD)</th><th>Msgs</th></tr></thead><tbody id="daily-table"></tbody></table>
    <p class="note">$3/MTok input, $15/MTok output. Custo pago direto na sua conta Anthropic.</p>
  </div>
</div>
<script>
function fmt(n){return n>=1e6?(n/1e6).toFixed(1)+'M':n>=1e3?(n/1e3).toFixed(1)+'K':n.toString()}
async function load(){try{const r=await fetch('/api/v1/usage/detailed');const d=await r.json();if(d.error)return;document.getElementById('today-tokens').textContent=fmt(d.today.total_tokens);document.getElementById('today-cost').textContent='$'+d.today.estimated_cost_usd.toFixed(4);document.getElementById('today-calls').textContent=d.today.calls;document.getElementById('total-tokens').textContent=fmt(d.total.total_tokens);const tb=document.getElementById('daily-table');tb.innerHTML='';d.daily.forEach(day=>{tb.innerHTML+='<tr><td>'+day.date+'</td><td class="mono">'+fmt(day.input_tokens)+'</td><td class="mono">'+fmt(day.output_tokens)+'</td><td class="mono">$'+day.estimated_cost_usd.toFixed(4)+'</td><td>'+day.calls+'</td></tr>'});document.getElementById('loading').style.display='none';document.getElementById('content').style.display='block'}catch(e){document.getElementById('loading').textContent='Erro ao carregar'}}
load();
</script>
</body>
</html>"""
