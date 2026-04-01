"""Configuração central do Batmam."""

import os
import json
from pathlib import Path
from dotenv import load_dotenv

# Carrega .env — busca em vários locais possíveis
_env_candidates = [
    Path(__file__).resolve().parent.parent / ".env",   # ./batmam/../.env (dev)
    Path.home() / ".batmam" / "app" / ".env",          # ~/.batmam/app/.env (instalado)
    Path.home() / ".batmam" / ".env",                  # ~/.batmam/.env
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
BATMAM_HOME = Path.home() / ".batmam"
SESSIONS_DIR = BATMAM_HOME / "sessions"
MEMORY_DIR = BATMAM_HOME / "memory"
CONFIG_FILE = BATMAM_HOME / "settings.json"

BATMAM_HOME.mkdir(parents=True, exist_ok=True)
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
MEMORY_DIR.mkdir(parents=True, exist_ok=True)

# ── API ─────────────────────────────────────────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
BATMAM_MODEL = os.getenv("BATMAM_MODEL", "gpt-4.1")

# ── Limites ─────────────────────────────────────────────────
MAX_TOKENS = 16384
MAX_CONTEXT_MESSAGES = 200
TEMPERATURE = 0.2

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
    """Carrega settings.json customizado do usuário."""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}


def save_settings(settings: dict) -> None:
    """Salva settings.json."""
    with open(CONFIG_FILE, "w") as f:
        json.dump(settings, f, indent=2)
