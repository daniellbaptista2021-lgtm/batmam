"""Sandbox para execucao segura de comandos bash.

Features:
- Timeout configuravel (padrao 120s, max 600s)
- Background execution com notificacao
- Bloqueio de comandos perigosos
- Output truncation (50KB)
- Deteccao automatica de container (Docker, Podman, LXC)
- Modos de isolamento: Off, WorkspaceOnly, AllowList
"""

from __future__ import annotations
import subprocess
import threading
import time
import os
import platform
from enum import Enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from .logging import log_action


class IsolationMode(Enum):
    """Modos de isolamento do sandbox."""
    OFF = "off"                     # Sem restricao de filesystem
    WORKSPACE_ONLY = "workspace"    # Restringe ao workspace
    ALLOWLIST = "allowlist"         # Apenas diretorios permitidos


@dataclass
class ContainerInfo:
    """Informacao sobre o ambiente containerizado."""
    is_container: bool = False
    runtime: str = ""       # "docker", "podman", "lxc", "wsl", ""
    details: str = ""


@dataclass
class SandboxResult:
    """Resultado de execucao no sandbox."""
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


def detect_container() -> ContainerInfo:
    """Detecta automaticamente se esta rodando dentro de um container.

    Verifica:
    - /.dockerenv (Docker)
    - /run/.containerenv (Podman)
    - Variaveis de ambiente container-related
    - /proc/1/cgroup (cgroups com docker/lxc)
    - WSL detection
    """
    info = ContainerInfo()

    # Docker: arquivo sentinela
    if os.path.exists("/.dockerenv"):
        info.is_container = True
        info.runtime = "docker"
        info.details = "Detectado via /.dockerenv"
        return info

    # Podman: arquivo sentinela
    if os.path.exists("/run/.containerenv"):
        info.is_container = True
        info.runtime = "podman"
        info.details = "Detectado via /run/.containerenv"
        return info

    # Variaveis de ambiente
    container_env_vars = {
        "DOCKER_CONTAINER": "docker",
        "container": "lxc",  # systemd-nspawn e LXC setam isso
        "KUBERNETES_SERVICE_HOST": "kubernetes",
        "ECS_CONTAINER_METADATA_URI": "ecs",
    }
    for var, runtime in container_env_vars.items():
        if os.getenv(var):
            info.is_container = True
            info.runtime = runtime
            info.details = f"Detectado via env ${var}"
            return info

    # Linux: /proc/1/cgroup
    if platform.system() == "Linux":
        try:
            cgroup = Path("/proc/1/cgroup").read_text()
            if "docker" in cgroup:
                info.is_container = True
                info.runtime = "docker"
                info.details = "Detectado via /proc/1/cgroup"
                return info
            if "lxc" in cgroup:
                info.is_container = True
                info.runtime = "lxc"
                info.details = "Detectado via /proc/1/cgroup"
                return info
        except (OSError, PermissionError):
            pass

    # WSL detection
    if platform.system() == "Linux":
        try:
            version = Path("/proc/version").read_text().lower()
            if "microsoft" in version or "wsl" in version:
                info.is_container = True
                info.runtime = "wsl"
                info.details = "Detectado via /proc/version (WSL)"
                return info
        except (OSError, PermissionError):
            pass

    return info


class Sandbox:
    """Execucao segura de comandos bash com deteccao de container."""

    def __init__(
        self,
        cwd: str | None = None,
        isolation: IsolationMode = IsolationMode.OFF,
        allowed_dirs: list[str] | None = None,
    ) -> None:
        self.cwd = cwd or os.getcwd()
        self.isolation = isolation
        self.allowed_dirs = allowed_dirs or []
        self._background_jobs: dict[str, SandboxResult] = {}
        self._lock = threading.Lock()

        # Detecta container automaticamente
        self.container_info = detect_container()
        if self.container_info.is_container:
            log_action(
                "sandbox_container_detected",
                f"{self.container_info.runtime}: {self.container_info.details}",
            )

    def is_blocked(self, command: str) -> str | None:
        cmd_lower = command.lower().strip()
        for pattern in BLOCKED_PATTERNS:
            if pattern in cmd_lower:
                return f"Comando bloqueado por seguranca: contem '{pattern}'"
        return None

    def is_dangerous(self, command: str) -> bool:
        cmd_lower = command.lower().strip()
        return any(p in cmd_lower for p in DANGEROUS_PATTERNS)

    def _check_isolation(self, command: str, cwd: str) -> str | None:
        """Verifica se o comando viola restricoes de isolamento.

        Retorna mensagem de erro ou None se permitido.
        """
        if self.isolation == IsolationMode.OFF:
            return None

        if self.isolation == IsolationMode.WORKSPACE_ONLY:
            # Verifica se o cwd esta dentro do workspace
            workspace = Path(self.cwd).resolve()
            target = Path(cwd).resolve()
            try:
                target.relative_to(workspace)
            except ValueError:
                return f"Isolamento workspace: execucao fora do workspace bloqueada ({target})"

        if self.isolation == IsolationMode.ALLOWLIST:
            target = Path(cwd).resolve()
            allowed = False
            for allowed_dir in self.allowed_dirs:
                try:
                    target.relative_to(Path(allowed_dir).resolve())
                    allowed = True
                    break
                except ValueError:
                    continue
            if not allowed:
                return f"Isolamento allowlist: diretorio {target} nao esta na lista permitida"

        return None

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

        # Verifica isolamento
        isolation_error = self._check_isolation(command, work_dir)
        if isolation_error:
            result.stderr = isolation_error
            result.return_code = -1
            log_action("sandbox_isolation_blocked", command[:80], level="warning")
            return result

        timeout = min(max(timeout, 1), 600)

        run_env = os.environ.copy()
        if env:
            run_env.update(env)

        # Adiciona info de container ao ambiente
        if self.container_info.is_container:
            run_env["CLOW_CONTAINER"] = self.container_info.runtime
            run_env["CLOW_CONTAINER_DETECTED"] = "true"

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
