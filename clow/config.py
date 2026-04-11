"""Configuração central do Clow."""

import os
import json
from pathlib import Path
from dotenv import load_dotenv

# Carrega .env �� busca em vários locais possíveis
_env_candidates = [
    Path.home() / ".clow" / "app" / ".env",          # ~/.clow/app/.env (producao — prioridade)
    Path.home() / ".clow" / ".env",                  # ~/.clow/.env
    Path(__file__).resolve().parent.parent / ".env",   # ./clow/../.env (dev)
    Path.cwd() / ".env",                               # diretório atual
]

_loaded_env = False
for _env_path in _env_candidates:
    if _env_path.exists():
        load_dotenv(_env_path)
        _loaded_env = True
        break

if not _loaded_env:
    load_dotenv()

# ── Diretórios ───────────────────────────��──────────────────
CLOW_HOME = Path.home() / ".clow"
SESSIONS_DIR = CLOW_HOME / "sessions"
MEMORY_DIR = CLOW_HOME / "memory"
CONFIG_FILE = CLOW_HOME / "settings.json"

CLOW_HOME.mkdir(parents=True, exist_ok=True)
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
MEMORY_DIR.mkdir(parents=True, exist_ok=True)

# ── API ──────────────────────────────���──────────────────────
# ── DeepSeek (unico provider — compativel com OpenAI SDK) ────
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_REASONER_MODEL = os.getenv("DEEPSEEK_REASONER_MODEL", "deepseek-reasoner")

# Modelo principal (deepseek-chat padrao, deepseek-reasoner para tasks complexas)
CLOW_MODEL = os.getenv("CLOW_MODEL", DEEPSEEK_MODEL)

# Modelo pesado (deepseek-reasoner para tasks complexas)
CLOW_MODEL_HEAVY = os.getenv("CLOW_MODEL_HEAVY", DEEPSEEK_REASONER_MODEL)

# ── Limites ─────────────────────────────────────────────────
MAX_TOKENS = int(os.getenv("CLOW_MAX_TOKENS", "16384"))

# Limites de mensagens por usuário (0 = sem limite)
CLOW_DAILY_LIMIT = int(os.getenv("CLOW_DAILY_LIMIT", "0"))
CLOW_WEEKLY_LIMIT = int(os.getenv("CLOW_WEEKLY_LIMIT", "0"))
MAX_CONTEXT_MESSAGES = 100
TEMPERATURE = 0.0
MAX_RETRY_ATTEMPTS = 5
MAX_TOOL_RESULT_CHARS = 30000

# ── Permissões ──────────────────────────────────────────────
AUTO_APPROVE_READ = True       # Leitura sempre liberada
AUTO_APPROVE_WRITE = True      # Escrita liberada — agente executor
AUTO_APPROVE_BASH = True       # Bash liberado — agente executor

# ── Extended Thinking ────────��─────────────────────────────
CLOW_EXTENDED_THINKING = os.getenv("CLOW_EXTENDED_THINKING", "true").lower() in ("true", "1", "yes")
CLOW_THINKING_BUDGET = int(os.getenv("CLOW_THINKING_BUDGET", "32000"))

# ── Auto-Correction ───────────────────────────────────────
CLOW_AUTO_CORRECT = os.getenv("CLOW_AUTO_CORRECT", "true").lower() in ("true", "1", "yes")
CLOW_AUTO_CORRECT_MAX = int(os.getenv("CLOW_AUTO_CORRECT_MAX", "5"))

# ── Vision Feedback Loop ──────────────────────────────────
CLOW_VISION_FEEDBACK = os.getenv("CLOW_VISION_FEEDBACK", "false").lower() in ("true", "1", "yes")

# ── Tool Pruning Dinâmico ─────────────────────────────────
CLOW_TOOL_PRUNING = os.getenv("CLOW_TOOL_PRUNING", "true").lower() in ("true", "1", "yes")

# ── Time Travel (Checkpoints) ─────────────────────────────
CLOW_CHECKPOINTS = os.getenv("CLOW_CHECKPOINTS", "true").lower() in ("true", "1", "yes")
CLOW_MAX_CHECKPOINTS = int(os.getenv("CLOW_MAX_CHECKPOINTS", "200"))

# ── Agent Swarm ───────────────────────────────────────────
CLOW_SWARM = os.getenv("CLOW_SWARM", "true").lower() in ("true", "1", "yes")
CLOW_SWARM_MAX_AGENTS = int(os.getenv("CLOW_SWARM_MAX_AGENTS", "10"))

# ── Self-Learning ─────────────────────────────────────────
CLOW_SELF_LEARN = os.getenv("CLOW_SELF_LEARN", "true").lower() in ("true", "1", "yes")

# ── GitHub Issue Autopilot ────────────────────────────────
CLOW_AUTOPILOT = False  # Desabilitado permanentemente — deploy via GitHub bloqueado
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")

# ── Automations Engine ────────────────────────────────────
CLOW_AUTOMATIONS = os.getenv("CLOW_AUTOMATIONS", "true").lower() in ("true", "1", "yes")

# ── Live Pair Programming (Spectator) ────────────────────
CLOW_SPECTATOR = os.getenv("CLOW_SPECTATOR", "true").lower() in ("true", "1", "yes")

# ── Teleport ──────────────────────────────────────────────
CLOW_TELEPORT = os.getenv("CLOW_TELEPORT", "true").lower() in ("true", "1", "yes")

# ── Agent Teams ───────────────────────────────────────────
CLOW_TEAMS = os.getenv("CLOW_TEAMS", "true").lower() in ("true", "1", "yes")
CLOW_TEAM_MAX_AGENTS = int(os.getenv("CLOW_TEAM_MAX_AGENTS", "10"))

# ── Natural Language Automations ──────────────────────────
CLOW_NL_AUTOMATIONS = os.getenv("CLOW_NL_AUTOMATIONS", "true").lower() in ("true", "1", "yes")


# ── Compaction (Claude Code 3-tier) ───────────────
MICROCOMPACT_KEEP_LAST = 10         # Keep last N tool results full
MICROCOMPACT_TRUNCATE_TO = 2000     # Truncate older tool results to N chars
SESSION_COMPACT_MIN_TOKENS = 30000  # Keep at least this many tokens after compact
SESSION_COMPACT_MAX_TOKENS = 120000 # Hard cap after compact
AUTOCOMPACT_THRESHOLD = 500000      # Chars (~125K tokens) to trigger autocompact
AUTOCOMPACT_MAX_FAILURES = 5        # Stop trying after N failures

# ── Stripe Billing ────────────────────────────────────────
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
# Novos price IDs (planos ONE/SMART/PROFISSIONAL/BUSINESS)
STRIPE_PRICE_ONE = os.getenv("STRIPE_PRICE_ONE", "")
STRIPE_PRICE_SMART = os.getenv("STRIPE_PRICE_SMART", "")
STRIPE_PRICE_PROFISSIONAL = os.getenv("STRIPE_PRICE_PROFISSIONAL", "")
STRIPE_PRICE_BUSINESS = os.getenv("STRIPE_PRICE_BUSINESS", "")
# Aliases legados (fallback se novas vars nao definidas)
STRIPE_LITE_PRICE_ID = STRIPE_PRICE_ONE or os.getenv("STRIPE_LITE_PRICE_ID", "")
STRIPE_STARTER_PRICE_ID = STRIPE_PRICE_SMART or os.getenv("STRIPE_STARTER_PRICE_ID", "")
STRIPE_PRO_PRICE_ID = STRIPE_PRICE_PROFISSIONAL or os.getenv("STRIPE_PRO_PRICE_ID", "")
STRIPE_BUSINESS_PRICE_ID = STRIPE_PRICE_BUSINESS or os.getenv("STRIPE_BUSINESS_PRICE_ID", "")
STRIPE_PAYMENT_METHODS = os.getenv("STRIPE_PAYMENT_METHODS", "card,pix").split(",")
STRIPE_WHATSAPP_ADDON_PRICE_ID = os.getenv("STRIPE_WHATSAPP_ADDON_PRICE_ID", "")

# Precos de referencia por 1M tokens (USD) — DeepSeek
DEEPSEEK_INPUT_PRICE_PER_MTOK = 0.27
DEEPSEEK_OUTPUT_PRICE_PER_MTOK = 1.10
DEEPSEEK_REASONER_INPUT_PRICE_PER_MTOK = 0.55
DEEPSEEK_REASONER_OUTPUT_PRICE_PER_MTOK = 2.19

DANGEROUS_COMMANDS = [
    "rm -rf", "rm -r /", "mkfs", "dd if=", ":(){:|:&};:", ":()", ":|:",
    "chmod -R 777 /", "shutdown", "reboot", "kill -9",
    "git push --force", "git reset --hard", "drop table",
    "drop database", "> /dev/sda",
]


def load_settings() -> dict:
    """Carrega settings com merge hierarquico de 4 fontes.

    Ordem (maior prioridade por ultimo):
    1. ~/.clow/settings.json          (global do usuario)
    2. .clow/settings.json            (projeto)
    3. .clow/settings.local.json      (local, nao commitado)
    4. CLOW_SETTINGS env var          (override via ambiente)
    """
    merged: dict = {}

    # 1. Global do usuario
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                merged = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    # 2. Projeto: .clow/settings.json
    project_settings = Path.cwd() / ".clow" / "settings.json"
    if project_settings.exists():
        try:
            with open(project_settings) as f:
                project_data = json.load(f)
            merged = _deep_merge(merged, project_data)
        except (json.JSONDecodeError, OSError):
            pass

    # 3. Local: .clow/settings.local.json (gitignored)
    local_settings = Path.cwd() / ".clow" / "settings.local.json"
    if local_settings.exists():
        try:
            with open(local_settings) as f:
                local_data = json.load(f)
            merged = _deep_merge(merged, local_data)
        except (json.JSONDecodeError, OSError):
            pass

    # 4. Override via env var (JSON string)
    env_settings = os.getenv("CLOW_SETTINGS", "")
    if env_settings:
        try:
            env_data = json.loads(env_settings)
            merged = _deep_merge(merged, env_data)
        except (json.JSONDecodeError, TypeError):
            pass

    return merged


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge profundo de dicts. Override tem prioridade.

    Arrays sao substituidos integralmente (nao concatenados).
    Chave 'mcp_servers' e preservada com merge especial por nome.
    """
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def save_settings(settings: dict) -> None:
    """Salva settings.json global do usuario."""
    with open(CONFIG_FILE, "w") as f:
        json.dump(settings, f, indent=2)


def save_project_settings(settings: dict) -> None:
    """Salva settings.json especifico do projeto em .clow/settings.json."""
    project_dir = Path.cwd() / ".clow"
    project_dir.mkdir(parents=True, exist_ok=True)
    project_file = project_dir / "settings.json"
    with open(project_file, "w") as f:
        json.dump(settings, f, indent=2)


def get_deepseek_client_kwargs() -> dict:
    """Retorna kwargs para OpenAI() apontando pro DeepSeek."""
    base = DEEPSEEK_BASE_URL.rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    return {"api_key": DEEPSEEK_API_KEY, "base_url": base}
