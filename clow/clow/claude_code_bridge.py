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
WORKSPACE = "/root/clow/static/files"

# Session persistence: maps conversation_id -> claude session_id
_session_map: dict[str, str] = {}

os.makedirs(WORKSPACE, exist_ok=True)


def _get_claude_env():
    """Build environment for Claude Code CLI subprocess.
    Removes ANTHROPIC_API_KEY so CLI uses OAuth instead of API key.
    Reads OAuth token dynamically from ~/.claude/.credentials.json.
    """
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
    env["CLAUDE_CODE_NO_INTERACTIVE"] = "1"
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


def _build_cmd(prompt: str, stream: bool = False, conversation_id: str | None = None) -> list[str]:
    """Build Claude Code CLI command with all flags."""
    cmd = [CLAUDE_BIN, "-p", prompt, "--model", "claude-opus-4-6", "--permission-mode", "dontAsk"]
    if stream:
        cmd.extend(["--output-format", "stream-json", "--verbose"])
    cmd.extend(["--max-turns", "50"])
    if conversation_id and conversation_id in _session_map:
        cmd.extend(["--resume", _session_map[conversation_id]])
    return cmd


def ask_claude_code(prompt: str, work_dir: str = WORKSPACE, conversation_id: str | None = None) -> tuple[str, float]:
    """Executa prompt via Claude Code CLI (sem streaming).

    Returns:
        Tuple (response_text, elapsed_seconds)
    """
    start = time.time()
    try:
        result = subprocess.run(
            _build_cmd(prompt, stream=False, conversation_id=conversation_id),
            capture_output=True,
            text=True,
            timeout=600,
            cwd=work_dir,
            env=_get_claude_env(),
        )
        elapsed = time.time() - start
        if result.returncode == 0:
            return result.stdout.strip(), elapsed
        else:
            err_msg = result.stderr.strip() or result.stdout.strip()
            return f"Erro: {err_msg}", elapsed
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start
        return "Timeout: Claude Code demorou mais de 10 minutos.", elapsed
    except FileNotFoundError:
        elapsed = time.time() - start
        return "Claude Code CLI nao encontrado. Verifique a instalacao.", elapsed


def ask_claude_code_stream(
    prompt: str,
    on_delta: Callable[[str], None],
    on_done: Callable[[str], None],
    on_error: Callable[[str], None],
    work_dir: str = WORKSPACE,
    on_tool_call: Callable[[str, dict], None] | None = None,
    on_tool_result: Callable[[str, str, str], None] | None = None,
    conversation_id: str | None = None,
) -> float:
    """Executa prompt via Claude Code CLI com streaming.

    Returns:
        elapsed_seconds
    """
    start = time.time()
    full_text = ""
    proc = None
    try:
        proc = subprocess.Popen(
            _build_cmd(prompt, stream=True, conversation_id=conversation_id),
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

                # Capture session_id for resume
                if "session_id" in data and conversation_id:
                    _session_map[conversation_id] = data["session_id"]

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
                    tool_result_info = data.get("tool_use_result", {})
                    msg = data.get("message", {})
                    for block in msg.get("content", []):
                        if block.get("type") == "tool_result":
                            is_error = block.get("is_error", False)
                            output = tool_result_info.get("stdout", "") or block.get("content", "")
                            if isinstance(output, list):
                                output = str(output)
                            if on_tool_result:
                                on_tool_result("", "error" if is_error else "success", str(output)[:500])

                elif evt_type == "result":
                    # Final result — extract session_id
                    if "session_id" in data and conversation_id:
                        _session_map[conversation_id] = data["session_id"]

            except (json.JSONDecodeError, KeyError, TypeError):
                continue

        proc.wait(timeout=30)
        elapsed = time.time() - start
        on_done(full_text)
        return elapsed

    except Exception as e:
        elapsed = time.time() - start
        if proc and proc.poll() is None:
            proc.kill()
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
