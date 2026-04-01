"""Sandbox para execução segura de comandos bash.

Features:
- Timeout configurável (padrão 120s, max 600s)
- Background execution com notificação
- Bloqueio de comandos perigosos
- Output truncation (50KB)
"""

from __future__ import annotations
import subprocess
import threading
import time
import os
from dataclasses import dataclass, field
from typing import Callable
from .logging import log_action


@dataclass
class SandboxResult:
    """Resultado de execução no sandbox."""
    stdout: str = ""
    stderr: str = ""
    return_code: int = 0
    timed_out: bool = False
    duration: float = 0.0
    truncated: bool = False
    background_id: str = ""


BLOCKED_PATTERNS = [
    "rm -rf /", "rm -rf /*", "mkfs.", "dd if=/dev/zero",
    ":(){:|:&};:", "chmod -R 777 /", "> /dev/sda",
    "wget | sh", "curl | sh", "wget | bash", "curl | bash",
]

DANGEROUS_PATTERNS = [
    "rm -rf", "rm -r", "git push --force", "git push -f",
    "git reset --hard", "git checkout -- .", "git clean -f",
    "git branch -D", "drop table", "drop database",
    "shutdown", "reboot", "kill -9", "pkill",
    "chmod", "chown", "docker rm", "docker rmi",
]

MAX_OUTPUT_BYTES = 50 * 1024


class Sandbox:
    """Execução segura de comandos bash."""

    def __init__(self, cwd: str | None = None) -> None:
        self.cwd = cwd or os.getcwd()
        self._background_jobs: dict[str, SandboxResult] = {}
        self._lock = threading.Lock()

    def is_blocked(self, command: str) -> str | None:
        cmd_lower = command.lower().strip()
        for pattern in BLOCKED_PATTERNS:
            if pattern in cmd_lower:
                return f"Comando bloqueado por segurança: contém '{pattern}'"
        return None

    def is_dangerous(self, command: str) -> bool:
        cmd_lower = command.lower().strip()
        return any(p in cmd_lower for p in DANGEROUS_PATTERNS)

    def execute(
        self,
        command: str,
        timeout: int = 120,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> SandboxResult:
        result = SandboxResult()
        work_dir = cwd or self.cwd
        start_time = time.time()

        blocked = self.is_blocked(command)
        if blocked:
            result.stderr = blocked
            result.return_code = -1
            log_action("sandbox_blocked", command[:80], level="warning")
            return result

        timeout = min(max(timeout, 1), 600)

        run_env = os.environ.copy()
        if env:
            run_env.update(env)

        try:
            proc = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                timeout=timeout, cwd=work_dir, env=run_env,
            )
            result.stdout = proc.stdout
            result.stderr = proc.stderr
            result.return_code = proc.returncode
        except subprocess.TimeoutExpired:
            result.timed_out = True
            result.stderr = f"Comando excedeu timeout de {timeout}s"
            result.return_code = -1
            log_action("sandbox_timeout", f"{command[:60]} ({timeout}s)", level="warning")
        except Exception as e:
            result.stderr = str(e)
            result.return_code = -1

        result.duration = time.time() - start_time

        if len(result.stdout) > MAX_OUTPUT_BYTES:
            result.stdout = result.stdout[:MAX_OUTPUT_BYTES] + f"\n... [truncado, {len(result.stdout)} bytes total]"
            result.truncated = True

        log_action("sandbox_exec", f"rc={result.return_code} {command[:60]}", duration=result.duration)
        return result

    def execute_background(
        self,
        command: str,
        job_id: str,
        timeout: int = 600,
        cwd: str | None = None,
        on_complete: Callable[[SandboxResult], None] | None = None,
    ) -> str:
        result = SandboxResult(background_id=job_id)
        with self._lock:
            self._background_jobs[job_id] = result

        def _run():
            r = self.execute(command, timeout=timeout, cwd=cwd)
            with self._lock:
                self._background_jobs[job_id] = r
                r.background_id = job_id
            if on_complete:
                on_complete(r)

        thread = threading.Thread(target=_run, daemon=True, name=f"sandbox-bg-{job_id}")
        thread.start()
        log_action("sandbox_background", f"job={job_id} {command[:60]}")
        return job_id

    def get_background_result(self, job_id: str) -> SandboxResult | None:
        with self._lock:
            return self._background_jobs.get(job_id)

    def list_background_jobs(self) -> dict[str, SandboxResult]:
        with self._lock:
            return dict(self._background_jobs)
