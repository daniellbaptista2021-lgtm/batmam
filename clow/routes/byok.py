"""BYOK (Bring Your Own Key) routes — onboarding, API key management, usage dashboard."""

from __future__ import annotations
import time
from typing import Any


def register_byok_routes(app) -> None:
    """Registra endpoints BYOK."""

    from fastapi import Request
    from fastapi.responses import JSONResponse, HTMLResponse
    from .auth import _get_user_session

    # ── API Key Management ────────────────────────────────────

    @app.post("/api/v1/onboarding/validate-key", tags=["byok"])
    async def validate_api_key(request: Request):
        """Valida API key da Anthropic."""
        body = await request.json()
        api_key = body.get("api_key", "").strip()

        if not api_key:
            return JSONResponse({"valid": False, "error": "API key vazia"}, status_code=400)

        if not api_key.startswith("sk-ant-"):
            return JSONResponse({"valid": False, "error": "Formato invalido. A key deve comecar com sk-ant-"}, status_code=400)

        from ..database import validate_anthropic_key
        result = validate_anthropic_key(api_key)
        return JSONResponse(result)

    @app.post("/api/v1/me/api-key", tags=["byok"])
    async def set_api_key(request: Request):
        """Salva API key do usuario (BYOK)."""
        sess = _get_user_session(request)
        if not sess:
            return JSONResponse({"error": "Nao autenticado"}, status_code=401)

        body = await request.json()
        api_key = body.get("api_key", "").strip()

        if not api_key:
            return JSONResponse({"error": "API key vazia"}, status_code=400)

        if not api_key.startswith("sk-ant-"):
            return JSONResponse({"error": "Formato invalido"}, status_code=400)

        # Valida antes de salvar
        from ..database import validate_anthropic_key, set_user_api_key
        validation = validate_anthropic_key(api_key)
        if not validation.get("valid"):
            return JSONResponse({"error": validation.get("error", "Key invalida")}, status_code=400)

        set_user_api_key(sess["user_id"], api_key)
        return JSONResponse({
            "success": True,
            "message": "API key configurada. Voce agora usa Claude Sonnet com sua propria key.",
            "model": "claude-sonnet-4-20250514",
        })

    @app.delete("/api/v1/me/api-key", tags=["byok"])
    async def remove_api_key(request: Request):
        """Remove API key do usuario."""
        sess = _get_user_session(request)
        if not sess:
            return JSONResponse({"error": "Nao autenticado"}, status_code=401)

        from ..database import remove_user_api_key
        remove_user_api_key(sess["user_id"])
        return JSONResponse({"success": True, "message": "API key removida."})

    @app.get("/api/v1/me/api-key/status", tags=["byok"])
    async def api_key_status(request: Request):
        """Verifica se usuario tem API key configurada."""
        sess = _get_user_session(request)
        if not sess:
            return JSONResponse({"error": "Nao autenticado"}, status_code=401)

        from ..database import get_user_api_key, get_user_by_id
        user = get_user_by_id(sess["user_id"])
        has_key = bool(get_user_api_key(sess["user_id"]))

        return JSONResponse({
            "has_api_key": has_key,
            "byok_enabled": bool(user.get("byok_enabled")) if user else False,
            "model": "claude-sonnet-4-20250514" if has_key else "claude-haiku-4-5-20251001",
            "api_key_set_at": user.get("api_key_set_at", 0) if user else 0,
        })

    # ── Usage Dashboard ───────────────────────────────────────

    @app.get("/api/v1/usage/detailed", tags=["byok"])
    async def usage_detailed(request: Request):
        """Retorna uso detalhado por sessao/dia."""
        sess = _get_user_session(request)
        if not sess:
            return JSONResponse({"error": "Nao autenticado"}, status_code=401)

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

        return JSONResponse({
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

    @app.post("/api/v1/auth/signup", tags=["byok"])
    async def signup(request: Request):
        """Cria conta nova (BYOK flow)."""
        body = await request.json()
        email = body.get("email", "").strip().lower()
        password = body.get("password", "").strip()
        name = body.get("name", "").strip()

        if not email or not password:
            return JSONResponse({"error": "Email e senha obrigatorios"}, status_code=400)
        if len(password) < 6:
            return JSONResponse({"error": "Senha deve ter pelo menos 6 caracteres"}, status_code=400)
        if "@" not in email:
            return JSONResponse({"error": "Email invalido"}, status_code=400)

        from ..database import create_user
        user = create_user(email, password, name)
        if not user:
            return JSONResponse({"error": "Email ja cadastrado"}, status_code=409)

        from .auth import _create_session
        token = _create_session(user)

        return JSONResponse({
            "success": True,
            "token": token,
            "email": user["email"],
            "user_id": user["id"],
            "plan": user["plan"],
            "next_step": "configure_api_key",
        })

    # ── Landing Page ──────────────────────────────────────────

    @app.get("/landing", tags=["byok"])
    async def landing_page():
        """Landing page BYOK do Clow."""
        return HTMLResponse(_landing_html())

    # ── Onboarding Page ───────────────────────────────────────

    @app.get("/onboarding", tags=["byok"])
    async def onboarding_page():
        """Pagina de onboarding BYOK."""
        return HTMLResponse(_onboarding_html())

    # ── Usage Page ────────────────────────────────────────────

    @app.get("/usage", tags=["byok"])
    async def usage_page():
        """Pagina de uso detalhado."""
        return HTMLResponse(_usage_html())


def _landing_html() -> str:
    return """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Clow — AI Code Agent | Traga Sua Key</title>
<meta name="description" content="Clow: o agente de codigo AI mais completo do Brasil. Traga sua API key da Anthropic e use Sonnet gratis, sem limites.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--purple:#7C5CFC;--purple-dark:#6B4FE0;--purple-light:#9B8AFB;--bg:#050510;--card:#0d1117;--border:#1c2333;--text:#e6edf3;--muted:#8b949e}
body{font-family:'DM Sans',sans-serif;background:var(--bg);color:var(--text);overflow-x:hidden}
a{color:var(--purple-light);text-decoration:none}

/* Hero */
.hero{min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:40px 20px;position:relative;overflow:hidden}
.hero::before{content:'';position:absolute;width:600px;height:600px;background:radial-gradient(circle,rgba(124,92,252,0.15),transparent 70%);top:-200px;left:50%;transform:translateX(-50%);pointer-events:none}
.hero h1{font-size:clamp(2.5rem,6vw,4.5rem);font-weight:800;line-height:1.1;margin-bottom:16px}
.hero h1 span{background:linear-gradient(135deg,var(--purple),var(--purple-light));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.hero .sub{font-size:clamp(1.1rem,2.5vw,1.4rem);color:var(--muted);max-width:600px;margin:0 auto 40px;line-height:1.6}
.hero .sub strong{color:var(--text)}
.cta-group{display:flex;gap:16px;flex-wrap:wrap;justify-content:center}
.btn{display:inline-flex;align-items:center;gap:8px;padding:14px 32px;border-radius:12px;font-size:1.05rem;font-weight:600;border:none;cursor:pointer;transition:all .2s}
.btn-primary{background:linear-gradient(135deg,var(--purple),var(--purple-dark));color:white;box-shadow:0 4px 24px rgba(124,92,252,0.3)}
.btn-primary:hover{transform:translateY(-2px);box-shadow:0 8px 32px rgba(124,92,252,0.4)}
.btn-secondary{background:transparent;color:var(--purple-light);border:1px solid var(--border)}
.btn-secondary:hover{border-color:var(--purple);background:rgba(124,92,252,0.05)}
.badge{display:inline-block;background:rgba(124,92,252,0.1);color:var(--purple-light);padding:6px 16px;border-radius:20px;font-size:.85rem;font-weight:500;margin-bottom:24px;border:1px solid rgba(124,92,252,0.2)}

/* How it works */
.section{padding:80px 20px;max-width:1100px;margin:0 auto}
.section h2{font-size:2rem;font-weight:700;text-align:center;margin-bottom:48px}
.section h2 span{color:var(--purple-light)}
.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:24px}
.step{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:32px;transition:border-color .2s}
.step:hover{border-color:var(--purple)}
.step-num{width:40px;height:40px;background:linear-gradient(135deg,var(--purple),var(--purple-dark));border-radius:10px;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:1.1rem;margin-bottom:16px}
.step h3{font-size:1.15rem;font-weight:600;margin-bottom:8px}
.step p{color:var(--muted);line-height:1.6;font-size:.95rem}

/* Features */
.features{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:20px;margin-top:48px}
.feature{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:24px}
.feature h4{font-size:1rem;font-weight:600;margin-bottom:6px;color:var(--purple-light)}
.feature p{color:var(--muted);font-size:.9rem;line-height:1.5}

/* Pricing */
.price-card{max-width:480px;margin:0 auto;background:var(--card);border:2px solid var(--purple);border-radius:20px;padding:40px;text-align:center}
.price-card .price{font-size:3rem;font-weight:800;color:var(--purple-light)}
.price-card .price-sub{color:var(--muted);margin-bottom:24px}
.price-card ul{text-align:left;list-style:none;margin:24px 0}
.price-card li{padding:8px 0;border-bottom:1px solid var(--border);font-size:.95rem}
.price-card li::before{content:'\\2713 ';color:var(--purple-light);font-weight:bold}

/* Footer */
.footer{text-align:center;padding:40px 20px;color:var(--muted);font-size:.85rem;border-top:1px solid var(--border)}

@media(max-width:640px){.cta-group{flex-direction:column;align-items:center}.hero h1{font-size:2.2rem}}
</style>
</head>
<body>

<section class="hero">
  <div class="badge">Modelo: Claude Sonnet 4 — o mesmo do Cursor e Claude Code</div>
  <h1>O agente de codigo AI<br>mais <span>completo</span> do Brasil</h1>
  <p class="sub">24 ferramentas, 40+ skills, multi-agent, automacoes, GitHub autopilot.<br><strong>Traga sua API key da Anthropic</strong> e use sem limites. Voce so paga o que usar.</p>
  <div class="cta-group">
    <a href="/onboarding" class="btn btn-primary">Comecar Gratis</a>
    <a href="#como-funciona" class="btn btn-secondary">Como funciona</a>
  </div>
</section>

<section class="section" id="como-funciona">
  <h2>Como <span>funciona</span></h2>
  <div class="steps">
    <div class="step">
      <div class="step-num">1</div>
      <h3>Crie sua conta</h3>
      <p>Email e senha. Sem cartao de credito. 30 segundos.</p>
    </div>
    <div class="step">
      <div class="step-num">2</div>
      <h3>Cole sua API Key</h3>
      <p>Pegue sua key em <strong>console.anthropic.com</strong>. O Clow valida na hora e nao armazena em nenhum servidor externo.</p>
    </div>
    <div class="step">
      <div class="step-num">3</div>
      <h3>Use sem limites</h3>
      <p>Claude Sonnet 4 com 24 tools, auto-correction, extended thinking, agent teams, e muito mais. Voce paga direto pra Anthropic.</p>
    </div>
  </div>
</section>

<section class="section">
  <h2>O que voce <span>ganha</span></h2>
  <div class="features">
    <div class="feature"><h4>24 Ferramentas</h4><p>Bash, Read, Write, Edit, Glob, Grep, Web Search, Image Gen, PDF, Spreadsheet, WhatsApp, Supabase, Docker e mais.</p></div>
    <div class="feature"><h4>40+ Skills</h4><p>/commit, /review, /test, /deploy, /debug, /plan, /automate — cada skill e um workflow completo.</p></div>
    <div class="feature"><h4>Agent Teams</h4><p>4 agentes (Architect, Developer, Tester, Reviewer) colaboram em tasks complexas com task board compartilhado.</p></div>
    <div class="feature"><h4>GitHub Autopilot</h4><p>Adicione label "clow" em qualquer issue e o agente cria branch, resolve, e abre PR automaticamente.</p></div>
    <div class="feature"><h4>Time Travel</h4><p>Checkpoints automaticos antes de cada mudanca. /undo reverte qualquer passo.</p></div>
    <div class="feature"><h4>NL Automations</h4><p>Diga em portugues: "todo dia as 8h verifica issues abertas" — o Clow cria a automacao.</p></div>
    <div class="feature"><h4>Extended Thinking</h4><p>O modelo "pensa" antes de responder em tarefas complexas. Mesma feature do Claude Pro.</p></div>
    <div class="feature"><h4>Spectator Mode</h4><p>Compartilhe uma URL e qualquer pessoa pode assistir o agente trabalhando em tempo real.</p></div>
    <div class="feature"><h4>Self-Learning</h4><p>O Clow aprende suas preferencias e evita erros que ja cometeu. Fica melhor a cada sessao.</p></div>
  </div>
</section>

<section class="section">
  <h2>Quanto <span>custa</span></h2>
  <div class="price-card">
    <div class="price">R$ 0</div>
    <div class="price-sub">O Clow e 100% gratis. Voce so paga a API da Anthropic.</div>
    <ul>
      <li>Acesso completo a todas as features</li>
      <li>Claude Sonnet 4 (mesmo modelo do Cursor Pro)</li>
      <li>Sem limite de mensagens</li>
      <li>Sem limite de sessoes</li>
      <li>Dashboard de uso com custo estimado em USD</li>
      <li>Custo medio: ~$0.01 a $0.05 por mensagem</li>
      <li>Voce controla tudo no console.anthropic.com</li>
    </ul>
    <a href="/onboarding" class="btn btn-primary" style="margin-top:24px;width:100%;justify-content:center">Criar Conta Gratis</a>
  </div>
</section>

<footer class="footer">
  <p>Clow AI — Inteligencia Infinita &bull; Possibilidades Premium</p>
  <p style="margin-top:8px">Feito no Brasil. Open source.</p>
</footer>

</body>
</html>"""


def _onboarding_html() -> str:
    return """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Clow — Setup</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--purple:#7C5CFC;--bg:#050510;--card:#0d1117;--border:#1c2333;--text:#e6edf3;--muted:#8b949e;--green:#3fb950;--red:#f85149}
body{font-family:'DM Sans',sans-serif;background:var(--bg);color:var(--text);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
.container{width:100%;max-width:460px}
.card{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:40px 32px}
h1{font-size:1.6rem;font-weight:700;margin-bottom:8px;text-align:center}
.sub{color:var(--muted);text-align:center;margin-bottom:32px;font-size:.95rem}
.step{display:none}.step.active{display:block}
label{display:block;font-size:.85rem;font-weight:500;color:var(--muted);margin-bottom:6px}
input{width:100%;padding:12px 16px;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:1rem;font-family:inherit;outline:none;transition:border .2s}
input:focus{border-color:var(--purple)}
input.mono{font-family:'JetBrains Mono',monospace;font-size:.85rem}
.fg{margin-bottom:16px}
.btn{width:100%;padding:14px;border:none;border-radius:10px;font-size:1rem;font-weight:600;cursor:pointer;transition:all .2s;margin-top:8px}
.btn-primary{background:linear-gradient(135deg,var(--purple),#6B4FE0);color:white}
.btn-primary:hover{transform:translateY(-1px)}
.btn-primary:disabled{opacity:.5;cursor:not-allowed;transform:none}
.msg{padding:12px;border-radius:8px;font-size:.9rem;margin-top:12px;display:none}
.msg.error{display:block;background:rgba(248,81,73,.1);border:1px solid var(--red);color:var(--red)}
.msg.success{display:block;background:rgba(63,185,80,.1);border:1px solid var(--green);color:var(--green)}
.msg.info{display:block;background:rgba(124,92,252,.1);border:1px solid var(--purple);color:var(--purple)}
.progress{display:flex;gap:8px;justify-content:center;margin-bottom:24px}
.dot{width:10px;height:10px;border-radius:50%;background:var(--border)}
.dot.active{background:var(--purple)}
.dot.done{background:var(--green)}
.spinner{display:inline-block;width:16px;height:16px;border:2px solid rgba(255,255,255,.3);border-top-color:white;border-radius:50%;animation:spin .6s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.link{color:var(--purple);cursor:pointer;font-size:.9rem;text-align:center;display:block;margin-top:16px}
</style>
</head>
<body>
<div class="container">
<div class="card">
  <h1>Configurar Clow</h1>
  <div class="progress"><div class="dot active" id="d1"></div><div class="dot" id="d2"></div><div class="dot" id="d3"></div></div>

  <!-- Step 1: Criar conta -->
  <div class="step active" id="step1">
    <p class="sub">Crie sua conta em 30 segundos</p>
    <div class="fg"><label>Nome</label><input id="name" placeholder="Seu nome"></div>
    <div class="fg"><label>Email</label><input id="email" type="email" placeholder="seu@email.com" required></div>
    <div class="fg"><label>Senha</label><input id="password" type="password" placeholder="minimo 6 caracteres" required></div>
    <button class="btn btn-primary" onclick="signup()">Criar Conta</button>
    <a class="link" href="/login">Ja tenho conta</a>
    <div class="msg" id="msg1"></div>
  </div>

  <!-- Step 2: API Key -->
  <div class="step" id="step2">
    <p class="sub">Cole sua API key da Anthropic</p>
    <div class="fg">
      <label>API Key</label>
      <input id="apikey" class="mono" placeholder="sk-ant-api03-..." required>
    </div>
    <p style="font-size:.8rem;color:var(--muted);margin-bottom:16px">
      Pegue em <a href="https://console.anthropic.com/settings/keys" target="_blank" style="color:var(--purple)">console.anthropic.com/settings/keys</a>.<br>
      Sua key fica salva apenas no servidor do Clow. Nao e compartilhada.
    </p>
    <button class="btn btn-primary" onclick="saveKey()" id="btn-key">Validar e Salvar</button>
    <div class="msg" id="msg2"></div>
  </div>

  <!-- Step 3: Done -->
  <div class="step" id="step3">
    <p class="sub" style="font-size:1.1rem;color:var(--green)">Tudo pronto!</p>
    <div class="msg success" style="display:block;text-align:center">
      Sua conta esta configurada com Claude Sonnet 4.<br>
      Voce paga apenas o que usar, direto na Anthropic.
    </div>
    <button class="btn btn-primary" onclick="window.location='/';" style="margin-top:24px">Abrir o Clow</button>
    <a class="link" href="/usage">Ver dashboard de uso</a>
  </div>
</div>
</div>

<script>
let token = '';
function $(id) { return document.getElementById(id); }
function showStep(n) {
  document.querySelectorAll('.step').forEach(s => s.classList.remove('active'));
  $('step'+n).classList.add('active');
  for(let i=1;i<=3;i++) {
    $('d'+i).className = i<n ? 'dot done' : i===n ? 'dot active' : 'dot';
  }
}
function showMsg(id, text, type) {
  const el = $(id);
  el.className = 'msg ' + type;
  el.textContent = text;
}

async function signup() {
  const name = $('name').value.trim();
  const email = $('email').value.trim();
  const password = $('password').value;
  if (!email || !password) return showMsg('msg1', 'Preencha email e senha', 'error');
  if (password.length < 6) return showMsg('msg1', 'Senha deve ter pelo menos 6 caracteres', 'error');

  try {
    const r = await fetch('/api/v1/auth/signup', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name, email, password})
    });
    const d = await r.json();
    if (d.error) return showMsg('msg1', d.error, 'error');
    token = d.token;
    document.cookie = 'clow_session=' + token + ';path=/;max-age=2592000';
    showStep(2);
  } catch(e) { showMsg('msg1', 'Erro de rede', 'error'); }
}

async function saveKey() {
  const key = $('apikey').value.trim();
  if (!key) return showMsg('msg2', 'Cole sua API key', 'error');
  if (!key.startsWith('sk-ant-')) return showMsg('msg2', 'Key deve comecar com sk-ant-', 'error');

  $('btn-key').disabled = true;
  $('btn-key').innerHTML = '<span class="spinner"></span> Validando...';
  showMsg('msg2', 'Validando key com a Anthropic...', 'info');

  try {
    const r = await fetch('/api/v1/me/api-key', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'Cookie': 'clow_session=' + token},
      body: JSON.stringify({api_key: key})
    });
    const d = await r.json();
    if (d.error) {
      showMsg('msg2', d.error, 'error');
      $('btn-key').disabled = false;
      $('btn-key').textContent = 'Validar e Salvar';
      return;
    }
    showStep(3);
  } catch(e) {
    showMsg('msg2', 'Erro de rede', 'error');
    $('btn-key').disabled = false;
    $('btn-key').textContent = 'Validar e Salvar';
  }
}
</script>
</body>
</html>"""


def _usage_html() -> str:
    return """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Clow — Uso</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--purple:#7C5CFC;--bg:#050510;--card:#0d1117;--border:#1c2333;--text:#e6edf3;--muted:#8b949e;--green:#3fb950}
body{font-family:'DM Sans',sans-serif;background:var(--bg);color:var(--text);padding:20px}
.container{max-width:800px;margin:0 auto}
h1{font-size:1.6rem;font-weight:700;margin-bottom:24px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-bottom:32px}
.stat{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px}
.stat-label{font-size:.8rem;color:var(--muted);text-transform:uppercase;letter-spacing:1px}
.stat-value{font-size:1.8rem;font-weight:700;margin-top:4px}
.stat-value.purple{color:var(--purple)}
.stat-value.green{color:var(--green)}
table{width:100%;border-collapse:collapse;background:var(--card);border-radius:12px;overflow:hidden}
th,td{padding:12px 16px;text-align:left;border-bottom:1px solid var(--border)}
th{font-size:.8rem;color:var(--muted);text-transform:uppercase;font-weight:500}
td{font-size:.9rem}
.mono{font-family:'JetBrains Mono',monospace;font-size:.85rem}
.nav{margin-bottom:24px}
.nav a{color:var(--purple);font-size:.9rem;margin-right:16px}
#loading{text-align:center;color:var(--muted);padding:40px}
</style>
</head>
<body>
<div class="container">
  <div class="nav"><a href="/">Chat</a><a href="/usage">Uso</a><a href="/onboarding">Config</a></div>
  <h1>Dashboard de Uso</h1>
  <div id="loading">Carregando...</div>
  <div id="content" style="display:none">
    <div class="cards">
      <div class="stat"><div class="stat-label">Tokens Hoje</div><div class="stat-value purple" id="today-tokens">-</div></div>
      <div class="stat"><div class="stat-label">Custo Hoje (USD)</div><div class="stat-value green" id="today-cost">-</div></div>
      <div class="stat"><div class="stat-label">Mensagens Hoje</div><div class="stat-value" id="today-calls">-</div></div>
      <div class="stat"><div class="stat-label">Total Acumulado</div><div class="stat-value" id="total-tokens">-</div></div>
    </div>
    <h2 style="font-size:1.1rem;margin-bottom:12px">Ultimos 7 dias</h2>
    <table>
      <thead><tr><th>Data</th><th>Tokens In</th><th>Tokens Out</th><th>Custo (USD)</th><th>Msgs</th></tr></thead>
      <tbody id="daily-table"></tbody>
    </table>
    <p style="margin-top:16px;font-size:.8rem;color:var(--muted)">Modelo: Claude Sonnet 4 — $3/MTok input, $15/MTok output. Custo pago direto na sua conta Anthropic.</p>
  </div>
</div>
<script>
function fmt(n){return n>=1000000?(n/1000000).toFixed(1)+'M':n>=1000?(n/1000).toFixed(1)+'K':n.toString()}
async function load(){
  try{
    const r=await fetch('/api/v1/usage/detailed');
    const d=await r.json();
    if(d.error)return;
    document.getElementById('today-tokens').textContent=fmt(d.today.total_tokens);
    document.getElementById('today-cost').textContent='$'+d.today.estimated_cost_usd.toFixed(4);
    document.getElementById('today-calls').textContent=d.today.calls;
    document.getElementById('total-tokens').textContent=fmt(d.total.total_tokens);
    const tbody=document.getElementById('daily-table');
    tbody.innerHTML='';
    d.daily.forEach(day=>{
      tbody.innerHTML+=`<tr><td>${day.date}</td><td class="mono">${fmt(day.input_tokens)}</td><td class="mono">${fmt(day.output_tokens)}</td><td class="mono">$${day.estimated_cost_usd.toFixed(4)}</td><td>${day.calls}</td></tr>`;
    });
    document.getElementById('loading').style.display='none';
    document.getElementById('content').style.display='block';
  }catch(e){document.getElementById('loading').textContent='Erro ao carregar dados';}
}
load();
</script>
</body>
</html>"""
