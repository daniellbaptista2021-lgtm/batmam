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


# ── Classificação de ações por risco ──────────────────────────

ACTION_CLASSIFICATIONS = {
    "read": {"reversible": True, "external": False, "level": "safe"},
    "glob": {"reversible": True, "external": False, "level": "safe"},
    "grep": {"reversible": True, "external": False, "level": "safe"},
    "web_search": {"reversible": True, "external": False, "level": "safe"},
    "web_fetch": {"reversible": True, "external": False, "level": "safe"},
    "task_list": {"reversible": True, "external": False, "level": "safe"},
    "task_get": {"reversible": True, "external": False, "level": "safe"},
    "write": {"reversible": True, "external": False, "level": "write"},
    "edit": {"reversible": True, "external": False, "level": "write"},
    "task_create": {"reversible": True, "external": False, "level": "write"},
    "task_update": {"reversible": True, "external": False, "level": "write"},
    "notebook_edit": {"reversible": True, "external": False, "level": "write"},
    "bash": {"reversible": None, "external": None, "level": "varies"},
    "agent": {"reversible": None, "external": None, "level": "varies"},
}

BASH_RISK_LEVELS = {
    "safe": [
        r"^ls\b", r"^cat\b", r"^head\b", r"^tail\b", r"^wc\b",
        r"^echo\b", r"^pwd\b", r"^which\b", r"^whoami\b",
        r"^date\b", r"^env\b", r"^printenv\b",
        r"^git\s+status", r"^git\s+log", r"^git\s+diff",
        r"^git\s+branch\b(?!.*-[dD])", r"^git\s+show",
        r"^python\s+-c\b", r"^node\s+-e\b",
        r"^pip\s+list", r"^pip\s+show", r"^npm\s+list",
    ],
    "write": [
        r"^git\s+add\b", r"^git\s+commit\b",
        r"^pip\s+install\b", r"^npm\s+install\b",
        r"^mkdir\b", r"^touch\b", r"^cp\b", r"^mv\b",
    ],
    "dangerous": [
        r"^rm\b", r"^git\s+push\b", r"^git\s+reset\b",
        r"^git\s+checkout\s+--", r"^git\s+clean\b",
        r"^git\s+branch\s+-[dD]\b", r"^git\s+stash\s+drop",
        r"^docker\s+rm\b", r"^docker\s+rmi\b",
        r"^kill\b", r"^pkill\b", r"^shutdown\b", r"^reboot\b",
        r"^chmod\b", r"^chown\b", r"^sudo\b",
    ],
}


def classify_bash_command(command: str) -> str:
    """Classifica comando bash: safe, write, dangerous, blocked."""
    cmd = command.strip()
    if is_dangerous_command(cmd):
        return "blocked"
    for level in ["safe", "dangerous", "write"]:
        for pattern in BASH_RISK_LEVELS.get(level, []):
            if re.match(pattern, cmd, re.IGNORECASE):
                return level
    return "write"


def classify_action(tool_name: str, arguments: dict) -> dict:
    """Classifica ação completa por risco, reversibilidade e visibilidade."""
    base = ACTION_CLASSIFICATIONS.get(tool_name, {"reversible": None, "external": None, "level": "write"})
    result = dict(base)
    if tool_name == "bash":
        cmd = arguments.get("command", "")
        risk = classify_bash_command(cmd)
        result["level"] = risk
        result["reversible"] = risk == "safe"
        result["external"] = bool(re.search(r"curl|wget|ssh|scp|git\s+push", cmd))
    return result
