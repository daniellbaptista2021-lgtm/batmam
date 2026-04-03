"""Bridge para Claude Code CLI — permite usar o CLI como backend de chat."""

import subprocess
import os
import time
import logging
from .database import get_db

logger = logging.getLogger(__name__)


def ask_claude_code(prompt: str, work_dir: str = "/root/clow") -> tuple[str, float]:
    """Executa prompt via Claude Code CLI.

    Returns:
        Tuple (response_text, elapsed_seconds)
    """
    start = time.time()
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--no-input"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=work_dir,
            env={**os.environ, "CLAUDE_CODE_NO_INTERACTIVE": "1"},
        )
        elapsed = time.time() - start
        if result.returncode == 0:
            return result.stdout.strip(), elapsed
        else:
            return f"Erro: {result.stderr.strip()}", elapsed
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start
        return "Timeout: Claude Code demorou mais de 120 segundos.", elapsed
    except FileNotFoundError:
        elapsed = time.time() - start
        return "Claude Code CLI nao encontrado. Verifique a instalacao.", elapsed


def log_claude_code_usage(user_id: str, prompt: str, elapsed: float):
    """Registra uso do Claude Code CLI no SQLite."""
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS claude_code_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                prompt_preview TEXT NOT NULL,
                elapsed_seconds REAL NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        db.execute(
            "INSERT INTO claude_code_log (user_id, prompt_preview, elapsed_seconds, created_at) VALUES (?,?,?,?)",
            (user_id, prompt[:50], elapsed, time.time()),
        )
