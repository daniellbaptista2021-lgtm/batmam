"""Bridge para Claude Code CLI — permite usar o CLI como backend de chat.

Usa OAuth Max (lê token de ~/.claude/.credentials.json).
Injeta system prompt do Clow para manter identidade e skills.
Suporta session resume para conversas contínuas.
"""

import subprocess
import os
import time
from pathlib import Path
import json
import logging
from typing import Callable
from .database import get_db

logger = logging.getLogger(__name__)

CLAUDE_BIN = "/root/.local/bin/claude"
WORKSPACE = str(Path(__file__).parent.parent)

# Session persistence: maps conversation_id -> claude session_id
_session_map: dict[str, str] = {}

# Ensure static/files exists for generated content
_static_files = Path(__file__).parent.parent / "static" / "files"
_static_files.mkdir(parents=True, exist_ok=True)


def _get_claude_env():
    """Build environment for Claude Code CLI subprocess.
    Reads OAuth token dynamically from ~/.claude/.credentials.json.
    """
    env = os.environ.copy()
    env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
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
    """Build Claude Code CLI command — identical to running claude directly."""
    cmd = [
        CLAUDE_BIN, "-p", prompt,
        "--model", "claude-sonnet-4-6",
        "--permission-mode", "dontAsk",
        "--max-turns", "50",
    ]
    if stream:
        cmd.extend(["--output-format", "stream-json", "--verbose"])
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
            except json.JSONDecodeError:
                continue

            try:
                evt_type = data.get("type", "")

                # Capture session_id for resume
                if "session_id" in data and conversation_id:
                    _session_map[conversation_id] = data["session_id"]

                if evt_type == "assistant":
                    msg = data.get("message")
                    if not isinstance(msg, dict):
                        continue
                    content = msg.get("content")
                    if not isinstance(content, list):
                        continue
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        btype = block.get("type", "")
                        if btype == "tool_use":
                            tool_name = block.get("name", "")
                            tool_input = block.get("input", {})
                            if on_tool_call:
                                on_tool_call(tool_name, tool_input)
                        elif btype == "text":
                            text = block.get("text", "")
                            if text:
                                full_text += text
                                on_delta(text)

                elif evt_type == "user":
                    msg = data.get("message")
                    if not isinstance(msg, dict):
                        continue
                    content = msg.get("content")
                    if not isinstance(content, list):
                        continue
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") == "tool_result":
                            is_error = block.get("is_error", False)
                            # content inside tool_result can be string or list
                            raw_output = block.get("content", "")
                            if isinstance(raw_output, list):
                                # Extract text from content blocks
                                parts = []
                                for part in raw_output:
                                    if isinstance(part, dict):
                                        parts.append(part.get("text", ""))
                                    else:
                                        parts.append(str(part))
                                raw_output = "\n".join(parts)
                            elif not isinstance(raw_output, str):
                                raw_output = str(raw_output)
                            if on_tool_result:
                                on_tool_result("", "error" if is_error else "success", raw_output[:2000])

                elif evt_type == "result":
                    if "session_id" in data and conversation_id:
                        _session_map[conversation_id] = data["session_id"]

            except (KeyError, TypeError, AttributeError) as e:
                logger.debug("Stream parse skip: %s", e)
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
    """Registra uso do Claude Code CLI no SQLite.
    Table created by migrations.py (v3).
    """
    with get_db() as db:
        db.execute(
            "INSERT INTO claude_code_log (user_id, prompt_preview, elapsed_seconds, created_at) VALUES (?,?,?,?)",
            (user_id, prompt[:50], elapsed, time.time()),
        )
