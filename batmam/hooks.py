"""Sistema de Hooks do Batmam.

Hooks executam shell commands automaticamente em resposta a eventos.
Configurados em ~/.batmam/settings.json:

{
  "hooks": {
    "pre_tool_call": [
      {
        "event": "pre_tool_call",
        "tool": "bash",
        "command": "echo 'Executando bash...'",
        "enabled": true
      }
    ],
    "post_tool_call": [...],
    "pre_turn": [...],
    "post_turn": [...],
    "on_error": [...],
    "on_start": [...],
    "on_exit": [...]
  }
}
"""

from __future__ import annotations
import subprocess
import os
import json
from typing import Any
from dataclasses import dataclass, field
from . import config


@dataclass
class Hook:
    """Definição de um hook."""
    event: str                      # pre_tool_call, post_tool_call, etc
    command: str                    # Comando shell a executar
    tool: str = ""                  # Filtro: só roda para esta tool (vazio = todas)
    enabled: bool = True
    timeout: int = 30              # Timeout em segundos
    stop_on_failure: bool = False  # Se True, bloqueia a ação se hook falhar

    @classmethod
    def from_dict(cls, data: dict) -> Hook:
        return cls(
            event=data.get("event", ""),
            command=data.get("command", ""),
            tool=data.get("tool", ""),
            enabled=data.get("enabled", True),
            timeout=data.get("timeout", 30),
            stop_on_failure=data.get("stop_on_failure", False),
        )

    def to_dict(self) -> dict:
        return {
            "event": self.event,
            "command": self.command,
            "tool": self.tool,
            "enabled": self.enabled,
            "timeout": self.timeout,
            "stop_on_failure": self.stop_on_failure,
        }


class HookRunner:
    """Executa hooks configurados."""

    VALID_EVENTS = {
        "pre_tool_call",
        "post_tool_call",
        "pre_turn",
        "post_turn",
        "on_error",
        "on_start",
        "on_exit",
    }

    def __init__(self) -> None:
        self._hooks: dict[str, list[Hook]] = {e: [] for e in self.VALID_EVENTS}
        self._load_hooks()

    def _load_hooks(self) -> None:
        """Carrega hooks do settings.json."""
        settings = config.load_settings()
        hooks_config = settings.get("hooks", {})

        for event, hook_list in hooks_config.items():
            if event not in self.VALID_EVENTS:
                continue
            for hook_data in hook_list:
                hook = Hook.from_dict(hook_data)
                hook.event = event
                if hook.enabled:
                    self._hooks[event].append(hook)

    def reload(self) -> None:
        """Recarrega hooks do disco."""
        self._hooks = {e: [] for e in self.VALID_EVENTS}
        self._load_hooks()

    def run_hooks(
        self,
        event: str,
        context: dict[str, Any] | None = None,
        cwd: str | None = None,
    ) -> list[HookResult]:
        """Executa todos os hooks para um evento.

        context pode conter:
          - tool_name: nome da ferramenta
          - tool_args: argumentos da ferramenta
          - tool_output: saída da ferramenta (post_tool_call)
          - user_message: mensagem do usuário (pre_turn/post_turn)
          - error: mensagem de erro (on_error)
        """
        if event not in self.VALID_EVENTS:
            return []

        context = context or {}
        results = []

        for hook in self._hooks[event]:
            # Filtro por tool
            if hook.tool and hook.tool != context.get("tool_name", ""):
                continue

            result = self._execute_hook(hook, context, cwd)
            results.append(result)

            # Para execução se hook falhou e é blocking
            if hook.stop_on_failure and not result.success:
                break

        return results

    def _execute_hook(
        self,
        hook: Hook,
        context: dict[str, Any],
        cwd: str | None,
    ) -> HookResult:
        """Executa um hook individual."""
        # Substitui variáveis de contexto no comando
        command = hook.command
        for key, value in context.items():
            command = command.replace(f"${{{key}}}", str(value))
            command = command.replace(f"${key}", str(value))

        # Variáveis de ambiente para o hook
        env = {**os.environ}
        env["BATMAM_EVENT"] = hook.event
        env["BATMAM_CWD"] = cwd or os.getcwd()
        for key, value in context.items():
            env[f"BATMAM_{key.upper()}"] = str(value)[:1000]  # Limita tamanho

        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=cwd or os.getcwd(),
                timeout=hook.timeout,
                env=env,
            )
            return HookResult(
                hook=hook,
                success=proc.returncode == 0,
                output=proc.stdout,
                error=proc.stderr,
                return_code=proc.returncode,
            )
        except subprocess.TimeoutExpired:
            return HookResult(
                hook=hook,
                success=False,
                output="",
                error=f"Hook expirou após {hook.timeout}s",
                return_code=-1,
            )
        except Exception as e:
            return HookResult(
                hook=hook,
                success=False,
                output="",
                error=str(e),
                return_code=-1,
            )

    def has_hooks(self, event: str) -> bool:
        return bool(self._hooks.get(event))

    def add_hook(self, hook: Hook) -> None:
        """Adiciona hook e salva no settings."""
        if hook.event in self.VALID_EVENTS:
            self._hooks[hook.event].append(hook)
            self._save_hooks()

    def remove_hook(self, event: str, index: int) -> bool:
        """Remove hook por índice."""
        hooks = self._hooks.get(event, [])
        if 0 <= index < len(hooks):
            hooks.pop(index)
            self._save_hooks()
            return True
        return False

    def list_hooks(self) -> dict[str, list[Hook]]:
        return {e: hooks for e, hooks in self._hooks.items() if hooks}

    def _save_hooks(self) -> None:
        """Persiste hooks no settings.json."""
        settings = config.load_settings()
        settings["hooks"] = {
            event: [h.to_dict() for h in hooks]
            for event, hooks in self._hooks.items()
            if hooks
        }
        config.save_settings(settings)


@dataclass
class HookResult:
    """Resultado da execução de um hook."""
    hook: Hook
    success: bool
    output: str
    error: str
    return_code: int

    @property
    def blocked(self) -> bool:
        """Se o hook bloqueia a ação."""
        return self.hook.stop_on_failure and not self.success

    @property
    def feedback(self) -> str:
        """Feedback para injetar na conversa."""
        parts = []
        if self.output.strip():
            parts.append(self.output.strip())
        if self.error.strip() and not self.success:
            parts.append(f"[hook error] {self.error.strip()}")
        return "\n".join(parts)
