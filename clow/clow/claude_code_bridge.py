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

def _get_claude_env():
    """Build environment for Claude Code CLI subprocess.
    Removes ANTHROPIC_API_KEY so CLI uses OAuth instead of API key.
    Reads OAuth token dynamically from ~/.claude/.credentials.json.
    """
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
    env["CLAUDE_CODE_NO_INTERACTIVE"] = "1"
    # Read token dynamically so it stays valid after refresh
    creds_path = os.path.expanduser("~/.claude/.credentials.json")
    try:
        with open(creds_path) as f:
            creds = json.load(f)
        token = creds.get("claudeAiOauth", {}).get("accessToken", "")
        if token:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        logger.warning("Could not read OAuth token from %s", creds_path)
    return env



def ask_claude_code(prompt: str, work_dir: str = "/root/clow") -> tuple[str, float]:
    """Executa prompt via Claude Code CLI (sem streaming).

    Returns:
        Tuple (response_text, elapsed_seconds)
    """
    start = time.time()
    try:
        result = subprocess.run(
            [CLAUDE_BIN, "-p", prompt, "--model", "claude-opus-4-6", "--permission-mode", "dontAsk"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=work_dir,
            env=_get_claude_env(),
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
    on_tool_call: Callable[[str, dict], None] | None = None,
    on_tool_result: Callable[[str, str, str], None] | None = None,
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
                "--model", "claude-opus-4-6",
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
            env=_get_claude_env(),
        )

        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                evt_type = data.get("type", "")
                logger.info(f"BRIDGE STREAM evt_type={evt_type}")

                if evt_type == "assistant":
                    msg = data.get("message", {})
                    for block in msg.get("content", []):
                        if block.get("type") == "tool_use":
                            tool_name = block.get("name", "")
                            tool_input = block.get("input", {})
                            if on_tool_call:
                                on_tool_call(tool_name, tool_input)
                        elif block.get("type") == "text":
                            text = block.get("text", "")
                            if text:
                                full_text += text
                                on_delta(text)

                elif evt_type == "user":
                    msg = data.get("message", {})
                    tool_result_info = data.get("tool_use_result", {})
                    for block in msg.get("content", []):
                        if block.get("type") == "tool_result":
                            is_error = block.get("is_error", False)
                            output = tool_result_info.get("stdout", "") or block.get("content", "")
                            if on_tool_result:
                                on_tool_result("", "error" if is_error else "success", output[:500])

                # Keep old stream_event parsing for backwards compat
                elif evt_type == "stream_event":
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
