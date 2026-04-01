"""Ferramenta Bash — execução segura via Sandbox com Git Safety Protocol."""

from __future__ import annotations
import uuid
from typing import Any
from .base import BaseTool
from ..sandbox import Sandbox
from ..git_safety import GitSafety
from ..logging import log_action


class BashTool(BaseTool):
    name = "bash"
    description = (
        "Executa comando bash no terminal com sandbox de segurança. "
        "Timeout configurável (1-600s), background execution, Git Safety Protocol."
    )
    requires_confirmation = True

    def __init__(self) -> None:
        self._sandbox = Sandbox()

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Comando bash a executar"},
                "description": {"type": "string", "description": "Descrição curta do que o comando faz"},
                "timeout": {"type": "integer", "description": "Timeout em milissegundos (max 600000). Padrão: 120000"},
                "cwd": {"type": "string", "description": "Diretório de trabalho (opcional)"},
                "run_in_background": {"type": "boolean", "description": "Executar em background (não bloqueia)"},
            },
            "required": ["command"],
        }

    def execute(self, **kwargs: Any) -> str:
        command: str = kwargs.get("command", "")
        if not command:
            return "Erro: comando vazio."

        timeout_ms: int = kwargs.get("timeout", 120000)
        timeout_s = min(max(timeout_ms // 1000, 1), 600)
        cwd: str = kwargs.get("cwd", "")
        run_bg: bool = kwargs.get("run_in_background", False)

        # Git Safety Protocol
        if command.strip().startswith("git "):
            git_safety = GitSafety(cwd or self._sandbox.cwd)
            allowed, reason = git_safety.validate_command(command)
            if not allowed:
                return f"[GIT SAFETY] {reason}"

        # Bloqueio de segurança
        blocked = self._sandbox.is_blocked(command)
        if blocked:
            return f"[SANDBOX] {blocked}"

        # Background execution
        if run_bg:
            job_id = uuid.uuid4().hex[:8]
            self._sandbox.execute_background(command, job_id, timeout=timeout_s, cwd=cwd or None)
            return f"[Background] Job {job_id} iniciado. O resultado será notificado quando completar."

        # Execução normal
        result = self._sandbox.execute(command, timeout=timeout_s, cwd=cwd or None)

        parts = []
        if result.stdout:
            parts.append(result.stdout)
        if result.stderr:
            parts.append(f"[stderr]\n{result.stderr}")
        if result.timed_out:
            parts.append(f"[TIMEOUT] Comando excedeu {timeout_s}s")
        if result.return_code != 0 and not result.timed_out:
            parts.append(f"[exit code: {result.return_code}]")
        if result.truncated:
            parts.append("[output truncado]")

        return "\n".join(parts) if parts else "(sem output)"
