"""Install tokens — autenticacao segura para instalacao do Clow CLI.

Fluxo para assinantes pagos:
1. Logado no web, clica "Gerar comando de instalacao"
2. Servidor gera token unico (24h, uso unico)
3. Usuario copia comando com token embutido
4. curl baixa script que configura CLI com auth_token (sem expor API key)
5. CLI usa modo proxy: chama servidor Clow, que chama DeepSeek com SUA key

A DEEPSEEK_API_KEY NUNCA e exposta ao assinante.
"""

from __future__ import annotations

import logging
import secrets
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from .auth import _get_user_session
from ..database import get_db

logger = logging.getLogger(__name__)

# Token TTL: 24 hours
TOKEN_TTL = 86400

# Plan → model mapping
PLAN_MODELS = {
    "lite": "deepseek-chat",
    "starter": "deepseek-chat",
    "pro": "deepseek-chat",
    "business": "deepseek-reasoner",
}

PAID_PLANS = {"lite", "starter", "pro", "business"}


def _init_tokens_table() -> None:
    """Cria tabela de tokens se nao existe."""
    with get_db() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS install_tokens (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            plan TEXT NOT NULL,
            model TEXT NOT NULL,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            used INTEGER DEFAULT 0,
            used_at REAL DEFAULT 0
        )""")


def _generate_token(user_id: str, tenant_id: str, plan: str) -> dict:
    """Gera token de instalacao unico."""
    _init_tokens_table()
    token = f"clow_install_{secrets.token_urlsafe(32)}"
    now = time.time()
    expires_at = now + TOKEN_TTL
    model = PLAN_MODELS.get(plan, "deepseek-chat")

    with get_db() as db:
        db.execute(
            "INSERT INTO install_tokens (token, user_id, tenant_id, plan, model, created_at, expires_at) VALUES (?,?,?,?,?,?,?)",
            (token, user_id, tenant_id, plan, model, now, expires_at),
        )

    return {
        "token": token,
        "plan": plan,
        "model": model,
        "expires_at": expires_at,
    }


def _validate_token(token: str) -> dict | None:
    """Valida token. Retorna dados ou None."""
    _init_tokens_table()
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM install_tokens WHERE token=?", (token,)
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        if data["used"]:
            return None
        if time.time() > data["expires_at"]:
            return None
        return data


def _mark_token_used(token: str) -> None:
    """Marca token como usado (single use)."""
    with get_db() as db:
        db.execute(
            "UPDATE install_tokens SET used=1, used_at=? WHERE token=?",
            (time.time(), token),
        )


def _generate_auth_token(user_id: str) -> str:
    """Gera auth token persistente para o CLI do assinante."""
    from .auth import _create_session
    from ..database import get_user_by_id
    user = get_user_by_id(user_id)
    if not user:
        return ""
    return _create_session(user)


def register_install_token_routes(app: FastAPI) -> None:
    """Registra rotas de install tokens."""

    @app.post("/api/v1/install/generate-token", tags=["install"])
    async def generate_install_token(request: Request):
        """Gera token de instalacao para assinante pago."""
        sess = _get_user_session(request)
        if not sess:
            return JSONResponse({"error": "Login necessario"}, status_code=401)

        plan = sess.get("plan", "lite")
        # Map legacy plans
        if plan in ("free", "basic"):
            plan = "byok_free"

        if plan not in PAID_PLANS:
            return JSONResponse(
                {"error": "Disponivel apenas para planos pagos (Lite, Starter, Pro, Business)"},
                status_code=403,
            )

        user_id = sess.get("user_id", "")
        tenant_id = user_id  # In Clow, tenant_id == user_id

        token_data = _generate_token(user_id, tenant_id, plan)
        base_url = "https://clow.pvcorretor01.com.br"

        return JSONResponse({
            "token": token_data["token"],
            "plan": plan,
            "model": token_data["model"],
            "expires_at": token_data["expires_at"],
            "command_windows": (
                f'powershell -c "irm {base_url}/api/v1/install/setup?token={token_data["token"]} | iex"'
            ),
            "command_unix": (
                f'curl -sSL {base_url}/api/v1/install/setup?token={token_data["token"]} | bash'
            ),
        })

    @app.get("/api/v1/install/setup", tags=["install"])
    async def install_setup_script(token: str = ""):
        """Retorna script de instalacao com auth token embutido (sem API key)."""
        if not token:
            return PlainTextResponse("echo 'Erro: token nao fornecido'", status_code=400)

        token_data = _validate_token(token)
        if not token_data:
            return PlainTextResponse(
                "echo 'Erro: token invalido, expirado ou ja usado. Gere um novo em clow.pvcorretor01.com.br/install'",
                status_code=403,
            )

        # Generate persistent auth token for the CLI
        auth_token = _generate_auth_token(token_data["user_id"])
        if not auth_token:
            return PlainTextResponse("echo 'Erro: usuario nao encontrado'", status_code=500)

        # Mark install token as used (single use)
        _mark_token_used(token)

        model = token_data["model"]
        plan = token_data["plan"]
        server_url = "https://clow.pvcorretor01.com.br"

        script = f"""#!/bin/bash
# ══════════════════════════════════════════
# Clow Installer — Plano {plan.title()}
# Token validado. Configurando...
# ══════════════════════════════════════════

set -e

echo ""
echo "  Clow Installer — Plano {plan.title()}"
echo "  ======================================"
echo ""

# 1. Verifica dependencias
command -v python3 >/dev/null 2>&1 || {{ echo "Erro: Python3 nao encontrado. Instale em python.org"; exit 1; }}
command -v git >/dev/null 2>&1 || {{ echo "Erro: Git nao encontrado. Instale em git-scm.com"; exit 1; }}

echo "  [1/4] Dependencias OK"

# 2. Clone repo
if [ ! -d "$HOME/clow" ]; then
    git clone --quiet https://github.com/daniellbaptista2021-lgtm/batmam.git "$HOME/clow"
    echo "  [2/4] Repositorio clonado"
else
    cd "$HOME/clow" && git pull --quiet origin main
    echo "  [2/4] Repositorio atualizado"
fi

# 3. Instala
cd "$HOME/clow"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
.venv/bin/pip install --quiet -e .
echo "  [3/4] Dependencias instaladas"

# 4. Configura .env com MODO PROXY (sem API key exposta)
mkdir -p "$HOME/.clow/app"
cat > "$HOME/.clow/app/.env" << 'ENVEOF'
CLOW_SERVER_URL={server_url}
CLOW_AUTH_TOKEN={auth_token}
CLOW_MODEL={model}
# Modo proxy: o CLI chama o servidor Clow, que chama a DeepSeek.
# Sua API key NUNCA fica no seu computador.
ENVEOF
chmod 600 "$HOME/.clow/app/.env"
echo "  [4/4] Configuracao salva"

# Setup PATH
WRAPPER="$HOME/.clow/bin/clow"
mkdir -p "$HOME/.clow/bin"
cat > "$WRAPPER" << 'WEOF'
#!/bin/bash
exec "$HOME/clow/.venv/bin/python" -m clow "$@"
WEOF
chmod +x "$WRAPPER"

# Add to PATH
for RC in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.profile"; do
    if [ -f "$RC" ] && ! grep -q '.clow/bin' "$RC" 2>/dev/null; then
        echo 'export PATH="$HOME/.clow/bin:$PATH"' >> "$RC"
    fi
done
export PATH="$HOME/.clow/bin:$PATH"

# Symlink
if [ -w /usr/local/bin ]; then
    ln -sf "$WRAPPER" /usr/local/bin/clow 2>/dev/null || true
fi

echo ""
echo "  ======================================"
echo "  Clow instalado com sucesso!"
echo "  Plano: {plan.title()}"
echo "  Modelo: {model}"
echo "  ======================================"
echo ""
echo "  Para comecar:"
echo "    clow"
echo ""
echo "  Reinicie o terminal ou rode:"
echo "    source ~/.bashrc"
echo ""
"""
        return PlainTextResponse(script, media_type="text/plain")

    @app.post("/api/v1/install/validate-token", tags=["install"])
    async def validate_install_token(request: Request):
        """Verifica se um token de instalacao e valido."""
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"valid": False, "error": "JSON invalido"}, status_code=400)

        token = body.get("token", "")
        data = _validate_token(token)
        if not data:
            return JSONResponse({"valid": False})

        expires_in = int(data["expires_at"] - time.time())
        hours = expires_in // 3600
        return JSONResponse({
            "valid": True,
            "plan": data["plan"],
            "model": data["model"],
            "expires_in": f"{hours}h",
        })

    @app.post("/api/v1/proxy/chat", tags=["proxy"])
    async def proxy_chat(request: Request):
        """Proxy de chat: CLI do assinante chama aqui, servidor chama Anthropic.

        O assinante NUNCA ve a API key. O servidor:
        1. Valida auth_token → identifica tenant
        2. Verifica plano ativo
        3. Verifica franquia
        4. Chama Anthropic com SUA API key
        5. Registra tokens consumidos
        6. Retorna resposta
        """
        # Auth
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return JSONResponse({"error": "Token ausente"}, status_code=401)

        token = auth[7:]
        from .auth import _validate_session
        sess = _validate_session(token)
        if not sess:
            return JSONResponse({"error": "Token invalido ou expirado"}, status_code=401)

        user_id = sess.get("user_id", "")
        plan = sess.get("plan", "lite")

        # Check paid plan
        if plan not in PAID_PLANS and plan != "unlimited":
            return JSONResponse(
                {"error": "Plano cancelado ou nao pago. Renove em clow.pvcorretor01.com.br/app/settings"},
                status_code=403,
            )

        # Check quota
        from ..billing import check_quota
        quota = check_quota(user_id, plan)
        if not quota.get("allowed"):
            return JSONResponse(
                {"error": quota.get("reason", "Franquia excedida"), "quota_exceeded": True},
                status_code=429,
            )

        # Parse request
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "JSON invalido"}, status_code=400)

        messages = body.get("messages", [])
        model_req = body.get("model", "")
        max_tokens = body.get("max_tokens", 4096)
        system_prompt = body.get("system", "")
        tools = body.get("tools", [])

        # Force model by plan (ignore client request)
        model = PLAN_MODELS.get(plan, "deepseek-chat")

        # Call DeepSeek with SERVER key
        from .. import config
        if not config.DEEPSEEK_API_KEY:
            return JSONResponse({"error": "Servidor nao configurado"}, status_code=500)

        try:
            from openai import OpenAI
            client = OpenAI(**config.get_deepseek_client_kwargs())

            oai_msgs = []
            if system_prompt:
                oai_msgs.append({"role": "system", "content": system_prompt})
            oai_msgs.extend(messages)

            kwargs: dict[str, Any] = {
                "model": model,
                "messages": oai_msgs,
                "max_tokens": min(max_tokens, 8192),  # DeepSeek max: 8192
            }
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"

            start = time.time()
            response = client.chat.completions.create(**kwargs)
            latency = (time.time() - start) * 1000

            # Log usage
            inp = response.usage.prompt_tokens if response.usage else 0
            out = response.usage.completion_tokens if response.usage else 0

            from ..database import log_usage
            cost = (inp * config.DEEPSEEK_INPUT_PRICE_PER_MTOK + out * config.DEEPSEEK_OUTPUT_PRICE_PER_MTOK) / 1_000_000
            log_usage(user_id, model, inp, out, cost, action="proxy")

            # Stats aggregator
            try:
                from ..stats_aggregator import stats
                stats.record_request(user_id, inp, out, latency, True, model=model,
                                     user_id=user_id, user_name=sess.get("email", ""))
            except Exception:
                pass

            choice = response.choices[0] if response.choices else None
            content_text = choice.message.content if choice else ""
            return JSONResponse({
                "id": response.id,
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": content_text}],
                "model": response.model,
                "usage": {"input_tokens": inp, "output_tokens": out},
                "stop_reason": choice.finish_reason if choice else "stop",
            })

        except Exception as e:
            logger.error("Proxy chat error: %s", e)
            return JSONResponse({"error": str(e)[:200]}, status_code=502)
