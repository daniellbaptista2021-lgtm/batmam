"""Configuração central do Clow."""

import os
import json
from pathlib import Path
from dotenv import load_dotenv

# Carrega .env — busca em vários locais possíveis
_env_candidates = [
    Path(__file__).resolve().parent.parent / ".env",   # ./clow/../.env (dev)
    Path.home() / ".clow" / "app" / ".env",          # ~/.clow/app/.env (instalado)
    Path.home() / ".clow" / ".env",                  # ~/.clow/.env
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

# ── Diretórios ──────────────────────────────────────────────
CLOW_HOME = Path.home() / ".clow"
SESSIONS_DIR = CLOW_HOME / "sessions"
MEMORY_DIR = CLOW_HOME / "memory"
CONFIG_FILE = CLOW_HOME / "settings.json"

CLOW_HOME.mkdir(parents=True, exist_ok=True)
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
MEMORY_DIR.mkdir(parents=True, exist_ok=True)

# ── API ─────────────────────────────────────────────────────
# Provider: "anthropic", "openai" ou "ollama"
CLOW_PROVIDER = os.getenv("CLOW_PROVIDER", "anthropic").lower()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")

# Modelo fixo: Sonnet 4.5 em todos os posicionamentos
CLOW_MODEL = "claude-sonnet-4-20250514"

# Modelo pesado — mesmo modelo (Sonnet 4.5 em tudo)
CLOW_MODEL_HEAVY = "claude-sonnet-4-20250514"

# ── Limites ─────────────────────────────────────────────────
MAX_TOKENS = 16384
MAX_CONTEXT_MESSAGES = 200
TEMPERATURE = 0.2
MAX_RETRY_ATTEMPTS = 3
MAX_TOOL_RESULT_CHARS = 5000

# ── Permissões ──────────────────────────────────────────────
AUTO_APPROVE_READ = True       # Leitura sempre liberada
AUTO_APPROVE_WRITE = False     # Escrita pede confirmação
AUTO_APPROVE_BASH = False      # Bash pede confirmação
DANGEROUS_COMMANDS = [
    "rm -rf", "rm -r /", "mkfs", "dd if=", ":(){:|:&};:",
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
