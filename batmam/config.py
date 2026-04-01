"""Configuração central do Batmam."""

import os
import json
from pathlib import Path
from dotenv import load_dotenv

# Carrega .env do diretório do projeto OU do home
_project_env = Path(__file__).resolve().parent.parent / ".env"
_home_env = Path.home() / ".batmam" / ".env"

if _project_env.exists():
    load_dotenv(_project_env)
elif _home_env.exists():
    load_dotenv(_home_env)
else:
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
