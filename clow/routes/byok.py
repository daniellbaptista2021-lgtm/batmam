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

        accepted_terms = body.get("accepted_terms", False)
        if not accepted_terms:
            return _JR({"error": "Aceite os Termos de Uso e Politica de Privacidade"}, status_code=400)

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

        # Salva aceite dos termos
        from ..database import get_db
        with get_db() as db:
            try:
                db.execute("ALTER TABLE users ADD COLUMN accepted_terms_at REAL DEFAULT 0")
            except Exception:
                pass
            db.execute("UPDATE users SET accepted_terms_at=? WHERE id=?", (time.time(), user["id"]))

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
        from pathlib import Path
        tpl = Path(__file__).parent.parent / "templates" / "landing.html"
        if tpl.exists():
            return _HR(tpl.read_text(encoding="utf-8"))
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
    return """<!DOCTYPE html>
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

/* Sections */
.section{padding:80px 20px;max-width:1100px;margin:0 auto;position:relative;z-index:1}
.section h2{font-size:2rem;font-weight:700;text-align:center;margin-bottom:56px}
.section h2 span{background:var(--gp);-webkit-background-clip:text;-webkit-text-fill-color:transparent}

/* Steps */
.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:24px}
.step{background:var(--bg2);border:1px solid var(--bd);border-radius:16px;padding:32px;transition:all .3s;transform:perspective(800px) rotateY(0deg)}
.step:hover{border-color:rgba(155,89,252,.4);transform:perspective(800px) rotateY(-2deg) translateY(-4px);box-shadow:0 20px 40px rgba(0,0,0,.3),0 0 30px rgba(155,89,252,.08)}
.step-num{width:44px;height:44px;background:var(--gp);border-radius:12px;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:1.1rem;margin-bottom:16px;box-shadow:0 4px 16px rgba(155,89,252,.3)}
.step h3{font-size:1.15rem;font-weight:600;margin-bottom:8px}
.step p{color:var(--t2);line-height:1.6;font-size:.95rem}

/* 3D Feature Cards */
.features{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:20px;perspective:1200px}
.feature{background:var(--bg2);border:1px solid var(--bd);border-radius:14px;padding:28px;position:relative;overflow:hidden;transition:all .4s cubic-bezier(.25,.8,.25,1);transform-style:preserve-3d;transform:perspective(800px) rotateX(0deg) rotateY(0deg)}
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
  <p class="sub">24 ferramentas, 40+ skills, multi-agent, automa&ccedil;&otilde;es, GitHub autopilot.<br><strong>Traga sua API key</strong> e use sem limites. Voc&ecirc; s&oacute; paga o que usar.</p>
  <div class="cta-group">
    <a href="/onboarding" class="btn btn-primary">Come&ccedil;ar Gr&aacute;tis</a>
    <a href="#como-funciona" class="btn btn-secondary">Como funciona</a>
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
  <h2>O que voc&ecirc; <span>ganha</span></h2>
  <div class="features" id="features-grid">
    <div class="feature"><h4>24 Ferramentas</h4><p>Bash, Read, Write, Edit, Glob, Grep, Web Search, Image Gen, PDF, Spreadsheet, WhatsApp, Supabase, Docker e mais.</p></div>
    <div class="feature"><h4>40+ Skills</h4><p>/commit, /review, /test, /deploy, /debug, /plan, /automate &mdash; cada skill &eacute; um workflow completo.</p></div>
    <div class="feature"><h4>Agent Teams</h4><p>4 agentes (Architect, Developer, Tester, Reviewer) colaboram em tasks complexas com task board compartilhado.</p></div>
    <div class="feature"><h4>GitHub Autopilot</h4><p>Adicione label &ldquo;clow&rdquo; em qualquer issue e o agente cria branch, resolve, e abre PR automaticamente.</p></div>
    <div class="feature"><h4>Time Travel</h4><p>Checkpoints autom&aacute;ticos antes de cada mudan&ccedil;a. /undo reverte qualquer passo.</p></div>
    <div class="feature"><h4>NL Automations</h4><p>Diga em portugu&ecirc;s: &ldquo;todo dia &agrave;s 8h verifica issues abertas&rdquo; &mdash; o Clow cria a automa&ccedil;&atilde;o.</p></div>
    <div class="feature"><h4>Extended Thinking</h4><p>O modelo &ldquo;pensa&rdquo; antes de responder em tarefas complexas de arquitetura e debug.</p></div>
    <div class="feature"><h4>Spectator Mode</h4><p>Compartilhe uma URL e qualquer pessoa pode assistir o agente trabalhando em tempo real.</p></div>
    <div class="feature"><h4>Self-Learning</h4><p>O Clow aprende suas prefer&ecirc;ncias e evita erros que j&aacute; cometeu. Fica melhor a cada sess&atilde;o.</p></div>
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
</html>"""


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
    <label style="display:flex;align-items:flex-start;gap:8px;margin-bottom:14px;cursor:pointer;font-size:.82rem;color:var(--t2);line-height:1.5"><input type="checkbox" id="terms" style="margin-top:3px;accent-color:var(--p);width:16px;height:16px;flex-shrink:0"><span>Li e aceito os <a href="/termos" target="_blank" style="color:var(--p)">Termos de Uso</a> e a <a href="/privacidade" target="_blank" style="color:var(--p)">Pol&iacute;tica de Privacidade</a></span></label>
    <button class="btn btn-primary" onclick="signup()">Criar Conta</button>
    <a class="link" href="/logout">J&aacute; tenho conta</a>
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
  if(!$('terms').checked)return showMsg('msg1','Aceite os Termos de Uso e Politica de Privacidade','error');
  if(!name)return showMsg('msg1','Informe seu nome completo','error');
  if(name.split(/\s+/).length<2)return showMsg('msg1','Informe nome e sobrenome','error');
  if(!email)return showMsg('msg1','Informe seu email','error');
  if(!email.includes('@')||!email.split('@')[1].includes('.'))return showMsg('msg1','Email invalido','error');
  if(!password)return showMsg('msg1','Crie uma senha','error');
  if(password.length<6)return showMsg('msg1','Senha deve ter pelo menos 6 caracteres','error');
  try{
    const r=await fetch('/api/v1/auth/signup',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({name,email,password,accepted_terms:true})});
    const d=await r.json();
    if(d.error){
      if(d.action==='login'){
        $('msg1').className='msg error';
        $('msg1').innerHTML=d.error+' <a href="/login" style="color:var(--p);text-decoration:underline">Ir para o login</a>';
        return;
      }
      return showMsg('msg1',d.error,'error');
    }
    token=d.token;userEmail=email;
    // Se veio com ?plan= na URL, vai direto pro checkout Stripe
    const urlPlan=new URLSearchParams(window.location.search).get('plan');
    if(urlPlan&&['lite','starter','pro','business'].includes(urlPlan)){
      // Redireciona pro Stripe checkout
      try{
        const cr=await fetch('/api/v1/billing/checkout',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({plan_id:urlPlan})});
        const cd=await cr.json();
        if(cd.url){window.open(cd.url,'_blank');showStep(3);return}
      }catch(ex){}
      showStep(3);
    }else{showStep(2)}
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
