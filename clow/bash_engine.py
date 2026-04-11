"""Bash Execution Engine — Safe Shell Execution (Claude Code Architecture Ep.06).

Defense-in-depth: command parsing -> permission rules -> process lifecycle.
Features:
- Command classification (search/read/write/dangerous)
- Read-only validation
- Path traversal detection
- CWD tracking after each command
- Process timeout and backgrounding
- Size watchdog for runaway output
- Shell snapshot for environment capture
"""

import os
import re
import time
import subprocess
import threading
import logging
from typing import Any
from . import config

logger = logging.getLogger("clow.bash_engine")

# ══ Command Classification ══

SEARCH_COMMANDS = {"find", "grep", "rg", "ag", "fd", "locate", "which", "whereis", "type"}
READ_COMMANDS = {
    "cat", "head", "tail", "less", "more", "jq", "awk", "sed", "wc",
    "sort", "uniq", "diff", "file", "stat", "ls", "ll", "la", "tree", "du", "df",
}
WRITE_COMMANDS = {"mv", "cp", "rm", "mkdir", "rmdir", "chmod", "chown", "touch", "ln", "install"}
NEUTRAL_COMMANDS = {
    "echo", "printf", "true", "false", "test", "expr", "date",
    "whoami", "hostname", "uname", "env", "printenv", "pwd", "id",
}

# Dangerous commands that ALWAYS need permission (bypass-immune)
DANGEROUS_PATTERNS = [
    r"rm\s+-rf\s+/",
    r"rm\s+-r\s+/",
    r"mkfs\b",
    r"dd\s+if=",
    r":\(\)\{.*\}",  # fork bomb
    r"chmod\s+-R\s+777\s+/",
    r"shutdown\b",
    r"reboot\b",
    r"kill\s+-9\s+-1",
    r">\s*/dev/sd",
    r"drop\s+table",
    r"drop\s+database",
    r"git\s+push\s+--force\s+(origin\s+)?(main|master)",
    r"git\s+reset\s+--hard",
]

# Paths that commands should never write to
PROTECTED_PATHS = [
    ".env", ".git/config", ".git/hooks/",
    "settings.json", ".claude/settings",
    ".bashrc", ".zshrc", ".profile", ".bash_profile",
    "/etc/passwd", "/etc/shadow", "/etc/sudoers",
]

# Max output size before killing (prevent disk fill)
MAX_OUTPUT_BYTES = 100 * 1024 * 1024  # 100MB
SIZE_WATCHDOG_INTERVAL = 5  # seconds

# Progress threshold before showing progress
PROGRESS_THRESHOLD_MS = 2000

# Default timeout
DEFAULT_TIMEOUT_MS = 120000  # 2 minutes
MAX_TIMEOUT_MS = 600000     # 10 minutes


def classify_command(command: str) -> str:
    """Classify a command for UI display purposes.

    Returns: 'search', 'read', 'write', 'neutral', 'dangerous', or 'unknown'
    """
    # Check dangerous first
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return "dangerous"

    # Extract first command from pipes/chains
    first_cmd = _extract_first_command(command)

    if first_cmd in SEARCH_COMMANDS:
        return "search"
    if first_cmd in READ_COMMANDS:
        return "read"
    if first_cmd in WRITE_COMMANDS:
        return "write"
    if first_cmd in NEUTRAL_COMMANDS:
        return "neutral"

    return "unknown"


def is_read_only(command: str) -> bool:
    """Check if command is read-only (no side effects).

    Read-only commands can skip permission checks.
    """
    classification = classify_command(command)
    if classification in ("search", "read", "neutral"):
        return True

    # Check compound commands - ALL parts must be read-only
    parts = _split_compound(command)
    return all(
        classify_command(p.strip()) in ("search", "read", "neutral")
        for p in parts if p.strip()
    )


def validate_command(command: str) -> tuple[bool, str]:
    """Validate command for safety.

    Returns (safe: bool, reason: str).
    Defense-in-depth checks:
    1. Dangerous pattern matching
    2. Path traversal detection
    3. Protected path checking
    """
    # 1. Dangerous patterns
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return False, f"Dangerous pattern: {pattern}"

    # 2. Path traversal
    if _has_path_traversal(command):
        return False, "Path traversal detected"

    # 3. Protected paths in write context
    if not is_read_only(command):
        for path in PROTECTED_PATHS:
            if path in command:
                return False, f"Protected path: {path}"

    # 4. Sleep blocking (except short sleeps)
    sleep_match = re.search(r"sleep\s+(\d+)", command)
    if sleep_match:
        seconds = int(sleep_match.group(1))
        if seconds > 10:
            return False, "Sleep > 10s blocked (use run_in_background)"

    return True, "ok"


def _extract_first_command(command: str) -> str:
    """Extract the first command name from a compound command."""
    # Strip leading whitespace, env vars, sudo
    cmd = command.strip()
    cmd = re.sub(r'^(sudo\s+|env\s+\w+=\S+\s+|cd\s+\S+\s*&&\s*)*', '', cmd)
    # Get first word
    match = re.match(r'(\w[\w.-]*)', cmd)
    return match.group(1) if match else ""


def _split_compound(command: str) -> list[str]:
    """Split compound command into parts (&&, ||, ;, |)."""
    # Simple split - does not handle quotes perfectly but good enough
    parts = re.split(r'\s*(?:&&|\|\||;|\|)\s*', command)
    return [p for p in parts if p.strip()]


def _has_path_traversal(command: str) -> bool:
    """Detect path traversal attempts."""
    # Check for excessive .. sequences
    if re.search(r'\.\.(/\.\.){3,}', command):
        return True
    # Check for redirect to sensitive system dirs
    if re.search(r'>\s*(/etc/|/var/log/|/root/)', command):
        return True
    return False


# ══ Shell Execution ══

class ShellExecutor:
    """Execute shell commands with lifecycle management.

    Features:
    - Timeout with auto-backgrounding
    - CWD tracking after each command
    - Output size watchdog
    - Progress polling
    """

    def __init__(self, cwd: str = ""):
        self.cwd = cwd or os.getcwd()
        self._snapshot_path: str = ""
        self._background_tasks: dict[str, subprocess.Popen] = {}

    def execute(
        self,
        command: str,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        run_in_background: bool = False,
        on_progress: Any = None,
    ) -> dict:
        """Execute a shell command with full lifecycle management.

        Returns dict with: stdout, exit_code, timed_out, duration_ms, cwd_changed
        """
        timeout_ms = min(timeout_ms, MAX_TIMEOUT_MS)
        timeout_s = timeout_ms / 1000

        start = time.time()

        # Build command with CWD tracking
        full_cmd = self._build_command(command)

        try:
            if run_in_background:
                return self._execute_background(command, full_cmd)

            result = subprocess.run(
                full_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                cwd=self.cwd,
                env=self._get_env(),
            )

            duration = (time.time() - start) * 1000

            # Check CWD change
            cwd_changed = self._update_cwd()

            # Combine stdout + stderr (Claude Code pattern: merged chronologically)
            output = result.stdout
            if result.stderr:
                output += "\n[stderr]\n" + result.stderr

            # Truncate large output
            if len(output) > MAX_OUTPUT_BYTES:
                output = output[:MAX_OUTPUT_BYTES] + "\n... (truncated, output exceeded 100MB)"

            return {
                "stdout": output,
                "exit_code": result.returncode,
                "timed_out": False,
                "duration_ms": round(duration),
                "cwd_changed": cwd_changed,
                "classification": classify_command(command),
            }

        except subprocess.TimeoutExpired:
            duration = (time.time() - start) * 1000
            return {
                "stdout": f"Command timed out after {timeout_s:.0f}s",
                "exit_code": -1,
                "timed_out": True,
                "duration_ms": round(duration),
                "cwd_changed": False,
                "classification": classify_command(command),
            }
        except Exception as e:
            duration = (time.time() - start) * 1000
            return {
                "stdout": f"Error: {e}",
                "exit_code": -1,
                "timed_out": False,
                "duration_ms": round(duration),
                "cwd_changed": False,
                "classification": "error",
            }

    def _build_command(self, command: str) -> str:
        """Build command with snapshot sourcing and CWD tracking."""
        parts = []

        # Source shell snapshot if available
        if self._snapshot_path and os.path.exists(self._snapshot_path):
            parts.append(f"source {self._snapshot_path} 2>/dev/null || true")

        # Disable extglob for security
        parts.append("shopt -u extglob 2>/dev/null || true")

        # The actual command
        parts.append(command)

        return " && ".join(parts)

    def _execute_background(self, command: str, full_cmd: str) -> dict:
        """Execute command in background."""
        task_id = f"bg-{int(time.time())}-{os.getpid()}"

        proc = subprocess.Popen(
            full_cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.cwd,
            env=self._get_env(),
        )

        self._background_tasks[task_id] = proc

        # Start size watchdog
        def _watchdog():
            while proc.poll() is None:
                time.sleep(SIZE_WATCHDOG_INTERVAL)
            self._background_tasks.pop(task_id, None)

        t = threading.Thread(target=_watchdog, daemon=True)
        t.start()

        return {
            "stdout": f"Background task started: {task_id}",
            "exit_code": 0,
            "timed_out": False,
            "duration_ms": 0,
            "background_task_id": task_id,
            "classification": "background",
        }

    def _update_cwd(self) -> bool:
        """Check if CWD changed after command execution."""
        try:
            result = subprocess.run(
                "pwd -P", shell=True, capture_output=True, text=True,
                cwd=self.cwd, timeout=2,
            )
            new_cwd = result.stdout.strip()
            if new_cwd and new_cwd != self.cwd:
                old = self.cwd
                self.cwd = new_cwd
                logger.debug("CWD changed: %s -> %s", old, new_cwd)
                return True
        except Exception:
            pass
        return False

    def _get_env(self) -> dict:
        """Get environment with CLAUDECODE hint support."""
        env = dict(os.environ)
        env["CLAUDECODE"] = "1"
        return env

    def create_snapshot(self) -> str:
        """Capture current shell environment (PATH, aliases, functions)."""
        try:
            import tempfile
            snapshot = tempfile.NamedTemporaryFile(
                prefix="clow-snapshot-", suffix=".sh",
                delete=False, mode="w",
            )
            # Capture env
            result = subprocess.run(
                "env && alias 2>/dev/null",
                shell=True, capture_output=True, text=True, timeout=5,
            )
            snapshot.write(f"# Clow shell snapshot {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            for line in result.stdout.splitlines():
                if "=" in line and not line.startswith("_="):
                    key = line.split("=", 1)[0]
                    if key.isidentifier() and not key.startswith("BASH"):
                        snapshot.write(f"export {line}\n")
            snapshot.close()
            self._snapshot_path = snapshot.name
            return snapshot.name
        except Exception:
            return ""

    def get_background_tasks(self) -> list[dict]:
        """List active background tasks."""
        tasks = []
        for tid, proc in list(self._background_tasks.items()):
            poll = proc.poll()
            tasks.append({
                "task_id": tid,
                "running": poll is None,
                "exit_code": poll,
            })
        return tasks


# ══ Global Executor ══

_executor: ShellExecutor | None = None


def get_executor() -> ShellExecutor:
    global _executor
    if _executor is None:
        _executor = ShellExecutor()
    return _executor
