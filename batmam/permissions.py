"""Sistema de permissões granulares do Batmam v0.2.0.

Suporta rules customizáveis em settings.json com:
- path patterns (glob)
- command patterns (regex)
- tool-level overrides
"""

from __future__ import annotations
import re
import fnmatch
from . import config


def is_dangerous_command(command: str) -> bool:
    """Verifica se um comando bash é perigoso."""
    cmd_lower = command.lower().strip()
    return any(danger in cmd_lower for danger in config.DANGEROUS_COMMANDS)


def needs_confirmation(tool_name: str, arguments: dict) -> bool:
    """Determina se uma chamada de ferramenta precisa de confirmação do usuário."""

    # Verifica regras customizadas primeiro
    custom_result = _check_custom_rules(tool_name, arguments)
    if custom_result is not None:
        return custom_result

    # Leitura nunca precisa de confirmação
    if tool_name in ("read", "glob", "grep", "task_create", "task_update", "task_list", "task_get"):
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

    # Web tools: normalmente livres
    if tool_name in ("web_search", "web_fetch"):
        return False

    # Agent tool: livre
    if tool_name == "agent":
        return False

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


def _check_custom_rules(tool_name: str, arguments: dict) -> bool | None:
    """Verifica regras customizadas de settings.json.

    Retorna True (needs confirmation), False (auto-approve), ou None (use default).

    Formato em settings.json:
    {
      "permissions": {
        "rules": [
          {
            "tool": "bash",
            "command_pattern": "git (add|commit|status|diff|log).*",
            "action": "allow"
          },
          {
            "tool": "write",
            "path_pattern": "*.test.*",
            "action": "allow"
          },
          {
            "tool": "bash",
            "command_pattern": "rm -rf.*",
            "action": "deny"
          }
        ]
      }
    }
    """
    settings = config.load_settings()
    rules = settings.get("permissions", {}).get("rules", [])

    if not rules:
        return None

    for rule in rules:
        # Filtra por tool
        rule_tool = rule.get("tool", "")
        if rule_tool and rule_tool != tool_name:
            continue

        matched = False

        # Command pattern (para bash)
        cmd_pattern = rule.get("command_pattern", "")
        if cmd_pattern and tool_name == "bash":
            cmd = arguments.get("command", "")
            try:
                if re.match(cmd_pattern, cmd):
                    matched = True
            except re.error:
                continue

        # Path pattern (para write/edit/read)
        path_pattern = rule.get("path_pattern", "")
        if path_pattern and tool_name in ("write", "edit", "read"):
            path = arguments.get("file_path", "")
            if fnmatch.fnmatch(path, path_pattern):
                matched = True

        # Tool-only rule (sem pattern = aplica pra toda tool)
        if not cmd_pattern and not path_pattern and rule_tool == tool_name:
            matched = True

        if matched:
            action = rule.get("action", "")
            if action == "allow":
                return False  # Não precisa confirmação
            elif action == "deny":
                return True  # Sempre pede confirmação
            elif action == "block":
                return True  # Bloqueia (pede confirmação que será negada)

    return None  # Nenhuma regra aplicável
