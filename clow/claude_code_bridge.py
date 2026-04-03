"""Bridge para Claude Code CLI — permite usar o CLI como backend de chat."""

import subprocess
import os
import time
import json
import logging
from typing import Callable
from .database import get_db

logger = logging.getLogger(__name__)

CLAUDE_BIN = "/root/.local/bin/claude"


def ask_claude_code(prompt: str, work_dir: str = "/root/clow") -> tuple[str, float]:
    """Executa prompt via Claude Code CLI (sem streaming).

    Returns:
        Tuple (response_text, elapsed_seconds)
    """
    start = time.time()
    try:
        result = subprocess.run(
            [CLAUDE_BIN, "-p", prompt, "--permission-mode", "dontAsk"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=work_dir,
            env={**os.environ, "CLAUDE_CODE_NO_INTERACTIVE": "1"},
        )
        elapsed = time.time() - start
        print(f"BRIDGE RETURNCODE: {result.returncode}", flush=True)
        print(f"BRIDGE STDOUT: {result.stdout[:200]!r}", flush=True)
        print(f"BRIDGE STDERR: {result.stderr[:200]!r}", flush=True)
        if result.returncode == 0:
            return result.stdout.strip(), elapsed
        else:
            err_msg = result.stderr.strip() or result.stdout.strip()
            return f"Erro: {err_msg}", elapsed
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start
        return "Timeout: Claude Code demorou mais de 120 segundos.", elapsed
    except FileNotFoundError:
        elapsed = time.time() - start
        return "Claude Code CLI nao encontrado. Verifique a instalacao.", elapsed


def ask_claude_code_stream(
    prompt: str,
    on_delta: Callable[[str], None],
    on_done: Callable[[str], None],
    on_error: Callable[[str], None],
    work_dir: str = "/root/clow",
) -> float:
    """Executa prompt via Claude Code CLI com streaming de texto.

    Usa --output-format stream-json para receber content_block_delta
    e chama on_delta(text) para cada chunk.

    Returns:
        elapsed_seconds
    """
    start = time.time()
    full_text = ""
    try:
        proc = subprocess.Popen(
            [
                CLAUDE_BIN, "-p", prompt,
                "--permission-mode", "dontAsk",
                "--output-format", "stream-json",
                "--verbose",
                "--include-partial-messages",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=work_dir,
            env={**os.environ, "CLAUDE_CODE_NO_INTERACTIVE": "1"},
        )

        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                evt_type = data.get("type", "")
                logger.info(f"BRIDGE STREAM evt_type={evt_type}")

                if evt_type == "stream_event":
                    event = data.get("event", {})
                    if event.get("type") == "content_block_delta":
                        delta_text = event.get("delta", {}).get("text", "")
                        if delta_text:
                            full_text += delta_text
                            on_delta(delta_text)
                            logger.info(f"BRIDGE DELTA: {delta_text[:100]}")

            except (json.JSONDecodeError, KeyError):
                continue

        proc.wait(timeout=10)
        elapsed = time.time() - start
        logger.info(f"BRIDGE STREAM DONE full_text={full_text[:200]}")
        on_done(full_text)
        return elapsed

    except subprocess.TimeoutExpired:
        if proc:
            proc.kill()
        elapsed = time.time() - start
        on_error("Timeout: Claude Code demorou demais.")
        return elapsed
    except FileNotFoundError:
        elapsed = time.time() - start
        on_error("Claude Code CLI nao encontrado.")
        return elapsed
    except Exception as e:
        elapsed = time.time() - start
        on_error(f"Erro: {str(e)}")
        return elapsed


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
