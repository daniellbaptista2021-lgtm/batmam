"""Ferramenta Bash — execução segura via Sandbox com Git Safety Protocol."""

from __future__ import annotations
import uuid
from typing import Any
from .base import BaseTool
from ..sandbox import Sandbox
from ..git_safety import GitSafety
from ..logging import log_action
from ..bash_engine import validate_command, classify_command, is_read_only


class BashTool(BaseTool):
    name = "bash"
    description = (
        "Executa comando bash no terminal com sandbox de segurança. "
        "Timeout configurável (1-600s), background execution, Git Safety Protocol."
    )
    requires_confirmation = True

    # Behavioral flags (Claude Code Ep.02)
    _is_read_only = False   # Input-dependent — fail-closed
    _is_concurrency_safe = False
    _is_destructive = False  # Input-dependent — checked at runtime
    _search_hint = "bash shell command terminal"
    _aliases = ["Bash", "sh", "shell"]

    def __init__(self) -> None:
        self._sandbox = Sandbox()

    def is_read_only(self, **kwargs) -> bool:
        """Input-dependent: delegates to bash_engine.is_read_only."""
        command = kwargs.get("command", "")
        if command:
            return is_read_only(command)
        return False  # Fail-closed

    def is_destructive(self, **kwargs) -> bool:
        """Input-dependent: destructive if command modifies system state irreversibly."""
        command = kwargs.get("command", "")
        if not command:
            return False
        destructive_prefixes = (
            "rm ", "rm -", "rmdir", "mkfs", "dd ",
            "git push --force", "git reset --hard",
            "DROP ", "DELETE FROM", "TRUNCATE ",
        )
        return any(command.strip().startswith(p) for p in destructive_prefixes)

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

        # Bash Engine — defense-in-depth validation (Ep.06)
        safe, reason = validate_command(command)
        if not safe:
            return f"[BASH ENGINE] Command blocked: {reason}"

        # Classify for logging
        classification = classify_command(command)
        log_action("bash_classify", f"{classification}: {command[:80]}")

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
