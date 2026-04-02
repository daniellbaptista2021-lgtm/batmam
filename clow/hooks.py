"""Sistema de Hooks do Clow.

Hooks executam shell commands automaticamente em resposta a eventos.
Usa protocolo padronizado de exit-code inspirado no Claude Code:

  Exit code 0 = ALLOW  — hook aprova a acao; stdout opcional e injetado como feedback
  Exit code 2 = DENY   — hook bloqueia a acao; stdout usado como motivo
  Qualquer outro = WARN — hook avisa mas permite; stdout injetado como aviso

O hook recebe um payload JSON via stdin com todo o contexto do evento,
alem de variaveis de ambiente HOOK_EVENT, HOOK_TOOL_NAME, HOOK_TOOL_INPUT,
HOOK_TOOL_OUTPUT, HOOK_TOOL_STATUS.

Configurados em ~/.clow/settings.json:

{
  "hooks": {
    "pre_tool_call": [
      {
        "event": "pre_tool_call",
        "tool": "bash",
        "command": "python my_validator.py",
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

# Codigos de saida padronizados
EXIT_ALLOW = 0
EXIT_DENY = 2


@dataclass
class Hook:
    """Definição de um hook."""
    event: str                      # pre_tool_call, post_tool_call, etc
    command: str                    # Comando shell a executar
    tool: str = ""                  # Filtro: só roda para esta tool (vazio = todas)
    enabled: bool = True
    timeout: int = 30              # Timeout em segundos
    stop_on_failure: bool = False  # Legado — mantido para compatibilidade

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

        Protocolo de exit-code:
          0 = ALLOW  — aprova; stdout e injetado como feedback
          2 = DENY   — bloqueia a acao; stdout e o motivo
          * = WARN   — avisa mas permite; stdout e injetado como aviso

        context pode conter:
          - tool_name: nome da ferramenta
          - tool_args: argumentos da ferramenta
          - tool_output: saída da ferramenta (post_tool_call)
          - tool_status: status da ferramenta (post_tool_call)
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

            # DENY (exit 2) interrompe a cadeia imediatamente
            if result.action == "deny":
                break

            # Compatibilidade legada: stop_on_failure
            if hook.stop_on_failure and not result.success:
                break

        return results

    def _execute_hook(
        self,
        hook: Hook,
        context: dict[str, Any],
        cwd: str | None,
    ) -> HookResult:
        """Executa um hook individual com payload JSON via stdin."""
        # Substitui variáveis de contexto no comando
        command = hook.command
        for key, value in context.items():
            command = command.replace(f"${{{key}}}", str(value))
            command = command.replace(f"${key}", str(value))

        # Payload JSON enviado via stdin ao hook
        payload = {
            "event": hook.event,
            "cwd": cwd or os.getcwd(),
            **{k: str(v)[:2000] for k, v in context.items()},
        }
        payload_json = json.dumps(payload, ensure_ascii=False)

        # Variáveis de ambiente padronizadas (compativel com Claude Code)
        env = {**os.environ}
        env["HOOK_EVENT"] = hook.event
        env["HOOK_CWD"] = cwd or os.getcwd()
        # Variaveis especificas por tipo de contexto
        if "tool_name" in context:
            env["HOOK_TOOL_NAME"] = str(context["tool_name"])
        if "tool_args" in context:
            env["HOOK_TOOL_INPUT"] = str(context["tool_args"])[:2000]
        if "tool_output" in context:
            env["HOOK_TOOL_OUTPUT"] = str(context["tool_output"])[:2000]
        if "tool_status" in context:
            env["HOOK_TOOL_IS_ERROR"] = "true" if context["tool_status"] == "error" else "false"
        if "user_message" in context:
            env["HOOK_USER_MESSAGE"] = str(context["user_message"])[:2000]
        if "error" in context:
            env["HOOK_ERROR"] = str(context["error"])[:2000]
        # Mantém variaveis legadas CLOW_* para compatibilidade
        env["CLOW_EVENT"] = hook.event
        env["CLOW_CWD"] = cwd or os.getcwd()
        for key, value in context.items():
            env[f"CLOW_{key.upper()}"] = str(value)[:1000]

        try:
            proc = subprocess.run(
                command,
                shell=True,
                input=payload_json,
                capture_output=True,
                text=True,
                cwd=cwd or os.getcwd(),
                timeout=hook.timeout,
                env=env,
            )

            # Determina acao pelo exit-code
            if proc.returncode == EXIT_ALLOW:
                action = "allow"
            elif proc.returncode == EXIT_DENY:
                action = "deny"
            else:
                action = "warn"

            return HookResult(
                hook=hook,
                success=proc.returncode == EXIT_ALLOW,
                output=proc.stdout,
                error=proc.stderr,
                return_code=proc.returncode,
                action=action,
            )
        except subprocess.TimeoutExpired:
            return HookResult(
                hook=hook,
                success=False,
                output="",
                error=f"Hook expirou apos {hook.timeout}s",
                return_code=-1,
                action="warn",
            )
        except Exception as e:
            return HookResult(
                hook=hook,
                success=False,
                output="",
                error=str(e),
                return_code=-1,
                action="warn",
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
    """Resultado da execução de um hook.

    Protocolo de exit-code:
      action="allow" (exit 0) — hook aprova; stdout opcional como feedback
      action="deny"  (exit 2) — hook bloqueia; stdout como motivo
      action="warn"  (outro)  — hook avisa mas permite; stdout como aviso
    """
    hook: Hook
    success: bool
    output: str
    error: str
    return_code: int
    action: str = "allow"  # "allow", "deny", "warn"

    @property
    def blocked(self) -> bool:
        """Se o hook bloqueia a acao (exit-code 2 ou legado stop_on_failure)."""
        if self.action == "deny":
            return True
        return self.hook.stop_on_failure and not self.success

    @property
    def is_warning(self) -> bool:
        """Se o hook emitiu um aviso (exit-code != 0 e != 2)."""
        return self.action == "warn"

    @property
    def feedback(self) -> str:
        """Feedback para injetar na conversa."""
        parts = []
        if self.output.strip():
            if self.action == "deny":
                parts.append(f"[hook DENIED] {self.output.strip()}")
            elif self.action == "warn":
                parts.append(f"[hook WARNING] {self.output.strip()}")
            else:
                parts.append(self.output.strip())
        if self.error.strip() and not self.success:
            parts.append(f"[hook error] {self.error.strip()}")
        return "\n".join(parts)
