"""Sistema de permissões do Batmam."""

from __future__ import annotations
from . import config


def is_dangerous_command(command: str) -> bool:
    """Verifica se um comando bash é perigoso."""
    cmd_lower = command.lower().strip()
    return any(danger in cmd_lower for danger in config.DANGEROUS_COMMANDS)


def needs_confirmation(tool_name: str, arguments: dict) -> bool:
    """Determina se uma chamada de ferramenta precisa de confirmação do usuário."""

    # Leitura nunca precisa de confirmação
    if tool_name in ("read", "glob", "grep"):
        return False

    # Bash: depende do comando
    if tool_name == "bash":
        cmd = arguments.get("command", "")
        if is_dangerous_command(cmd):
            return True
        return not config.AUTO_APPROVE_BASH

    # Write e Edit: depende da config
    if tool_name in ("write", "edit"):
        return not config.AUTO_APPROVE_WRITE

    # Default: pede confirmação
    return True


def format_confirmation_prompt(tool_name: str, arguments: dict) -> str:
    """Formata a mensagem de confirmação para o usuário."""

    if tool_name == "bash":
        cmd = arguments.get("command", "")
        cwd = arguments.get("cwd", "")
        danger = " ⚠️  COMANDO PERIGOSO!" if is_dangerous_command(cmd) else ""
        location = f" (em {cwd})" if cwd else ""
        return f"Executar bash{location}?{danger}\n  $ {cmd}"

    elif tool_name == "write":
        path = arguments.get("file_path", "")
        content = arguments.get("content", "")
        lines = content.count("\n") + 1
        return f"Escrever arquivo?\n  {path} ({lines} linhas)"

    elif tool_name == "edit":
        path = arguments.get("file_path", "")
        old = arguments.get("old_string", "")[:80]
        new = arguments.get("new_string", "")[:80]
        return f"Editar arquivo?\n  {path}\n  - {old!r}\n  + {new!r}"

    return f"Executar {tool_name} com {arguments}?"
