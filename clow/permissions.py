"""Sistema de permissoes granulares do Clow v0.2.0.

Modelo de 5 camadas de permissao inspirado no Claude Code:

  ReadOnly         — apenas ferramentas de leitura
  WorkspaceWrite   — leitura + escrita em arquivos do workspace
  Prompt           — pede confirmacao antes de acoes perigosas (padrao)
  DangerFullAccess — acesso total sem restricoes
  Allow            — ignora todas as verificacoes

Cada ferramenta declara seu nivel minimo via TOOL_REQUIREMENTS.
Escalacao automatica: se o nivel atual nao atinge o requisito,
o sistema pede confirmacao ao usuario (se prompter disponivel).

Suporta rules customizaveis em settings.json com:
- path patterns (glob)
- command patterns (regex)
- tool-level overrides
"""

from __future__ import annotations
import re
import fnmatch
from enum import IntEnum
from . import config


# ── Niveis de Permissao (5 camadas) ────────────────────────────

class PermissionLevel(IntEnum):
    """Niveis de permissao em ordem crescente de acesso."""
    READ_ONLY = 0
    WORKSPACE_WRITE = 1
    PROMPT = 2          # Padrao — pede confirmacao para acoes perigosas
    DANGER_FULL_ACCESS = 3
    ALLOW = 4


# Nivel minimo necessario por ferramenta
TOOL_REQUIREMENTS: dict[str, PermissionLevel] = {
    # Leitura — nivel 0
    "read": PermissionLevel.READ_ONLY,
    "glob": PermissionLevel.READ_ONLY,
    "grep": PermissionLevel.READ_ONLY,
    "web_search": PermissionLevel.READ_ONLY,
    "web_fetch": PermissionLevel.READ_ONLY,
    "scraper": PermissionLevel.READ_ONLY,
    "task_list": PermissionLevel.READ_ONLY,
    "task_get": PermissionLevel.READ_ONLY,
    # Escrita no workspace — nivel 1
    "write": PermissionLevel.WORKSPACE_WRITE,
    "edit": PermissionLevel.WORKSPACE_WRITE,
    "task_create": PermissionLevel.WORKSPACE_WRITE,
    "task_update": PermissionLevel.WORKSPACE_WRITE,
    "notebook_edit": PermissionLevel.WORKSPACE_WRITE,
    "pdf_tool": PermissionLevel.WORKSPACE_WRITE,
    "spreadsheet": PermissionLevel.WORKSPACE_WRITE,
    "image_gen": PermissionLevel.WORKSPACE_WRITE,
    "agent": PermissionLevel.WORKSPACE_WRITE,
    # Acesso perigoso — nivel 3
    "bash": PermissionLevel.DANGER_FULL_ACCESS,
    "git_advanced": PermissionLevel.DANGER_FULL_ACCESS,
    "docker_manage": PermissionLevel.DANGER_FULL_ACCESS,
    "whatsapp_send": PermissionLevel.DANGER_FULL_ACCESS,
    "http_request": PermissionLevel.DANGER_FULL_ACCESS,
    "supabase_query": PermissionLevel.DANGER_FULL_ACCESS,
    "n8n_workflow": PermissionLevel.DANGER_FULL_ACCESS,
}

# Mapeamento de nomes de modo (settings.json) para nivel
PERMISSION_MODES: dict[str, PermissionLevel] = {
    "readonly": PermissionLevel.READ_ONLY,
    "read_only": PermissionLevel.READ_ONLY,
    "workspace": PermissionLevel.WORKSPACE_WRITE,
    "workspace_write": PermissionLevel.WORKSPACE_WRITE,
    "default": PermissionLevel.PROMPT,
    "prompt": PermissionLevel.PROMPT,
    "acceptEdits": PermissionLevel.WORKSPACE_WRITE,
    "danger": PermissionLevel.DANGER_FULL_ACCESS,
    "dontAsk": PermissionLevel.ALLOW,
    "allow": PermissionLevel.ALLOW,
}


def get_current_level() -> PermissionLevel:
    """Retorna o nivel de permissao atual baseado em config e settings."""
    settings = config.load_settings()
    mode = settings.get("permissions", {}).get("mode", "default")
    return PERMISSION_MODES.get(mode, PermissionLevel.PROMPT)


def get_tool_requirement(tool_name: str) -> PermissionLevel:
    """Retorna o nivel minimo necessario para uma ferramenta."""
    return TOOL_REQUIREMENTS.get(tool_name, PermissionLevel.DANGER_FULL_ACCESS)


# ── API Principal ──────────────────────────────────────────────

def is_dangerous_command(command: str) -> bool:
    """Verifica se um comando bash e perigoso."""
    cmd_lower = command.lower().strip()
    return any(danger in cmd_lower for danger in config.DANGEROUS_COMMANDS)


def needs_confirmation(tool_name: str, arguments: dict) -> bool:
    """Determina se uma chamada de ferramenta precisa de confirmacao.

    Logica de 5 camadas:
    1. Verifica regras customizadas (settings.json) — tem prioridade
    2. Verifica nivel atual vs requisito da ferramenta
    3. Para bash, classifica o comando para decidir
    """
    # Regras customizadas tem prioridade
    custom_result = _check_custom_rules(tool_name, arguments)
    if custom_result is not None:
        return custom_result

    current = get_current_level()
    required = get_tool_requirement(tool_name)

    # Allow: nunca pede confirmacao
    if current == PermissionLevel.ALLOW:
        return False

    # ReadOnly: bloqueia tudo que nao e leitura
    if current == PermissionLevel.READ_ONLY:
        return required > PermissionLevel.READ_ONLY

    # DangerFullAccess: nunca pede confirmacao (exceto comandos bloqueados)
    if current == PermissionLevel.DANGER_FULL_ACCESS:
        if tool_name == "bash" and is_dangerous_command(arguments.get("command", "")):
            return True  # Mesmo com full access, comandos bloqueados pedem confirmacao
        return False

    # WorkspaceWrite: permite leitura e escrita, pede confirmacao para danger
    if current == PermissionLevel.WORKSPACE_WRITE:
        if required <= PermissionLevel.WORKSPACE_WRITE:
            return False
        # Bash: depende do comando
        if tool_name == "bash":
            risk = classify_bash_command(arguments.get("command", ""))
            return risk in ("dangerous", "blocked")
        return True

    # Prompt (padrao): usa logica detalhada
    if tool_name in ("read", "glob", "grep", "task_list", "task_get"):
        return False

    if tool_name == "bash":
        cmd = arguments.get("command", "")
        if is_dangerous_command(cmd):
            return True
        risk = classify_bash_command(cmd)
        if risk == "safe":
            return False
        return not config.AUTO_APPROVE_BASH

    if tool_name in ("write", "edit"):
        return not config.AUTO_APPROVE_WRITE

    if tool_name in ("web_search", "web_fetch", "scraper"):
        return False

    if tool_name == "agent":
        return False

    if tool_name in ("whatsapp_send", "docker_manage", "n8n_workflow",
                      "supabase_query", "image_gen"):
        return True

    if tool_name in ("pdf_tool", "spreadsheet"):
        return not config.AUTO_APPROVE_WRITE

    if tool_name in ("http_request", "git_advanced"):
        return not config.AUTO_APPROVE_BASH

    return True


def is_tool_allowed(tool_name: str) -> bool:
    """Verifica se a ferramenta e permitida no nivel atual (sem prompt)."""
    current = get_current_level()
    required = get_tool_requirement(tool_name)
    return current >= required


def format_confirmation_prompt(tool_name: str, arguments: dict) -> str:
    """Formata a mensagem de confirmacao para o usuario."""
    level = get_current_level()
    level_name = level.name.replace("_", " ").title()

    if tool_name == "bash":
        cmd = arguments.get("command", "")
        cwd = arguments.get("cwd", "")
        danger = " COMANDO PERIGOSO!" if is_dangerous_command(cmd) else ""
        location = f" (em {cwd})" if cwd else ""
        return f"[{level_name}] Executar bash{location}?{danger}\n  $ {cmd}"

    elif tool_name == "write":
        path = arguments.get("file_path", "")
        content = arguments.get("content", "")
        lines = content.count("\n") + 1
        return f"[{level_name}] Escrever arquivo?\n  {path} ({lines} linhas)"

    elif tool_name == "edit":
        path = arguments.get("file_path", "")
        old = arguments.get("old_string", "")[:80]
        new = arguments.get("new_string", "")[:80]
        return f"[{level_name}] Editar arquivo?\n  {path}\n  - {old!r}\n  + {new!r}"

    return f"[{level_name}] Executar {tool_name} com {arguments}?"


def _check_custom_rules(tool_name: str, arguments: dict) -> bool | None:
    """Verifica regras customizadas de settings.json.

    Retorna True (needs confirmation), False (auto-approve), ou None (use default).

    Formato em settings.json:
    {
      "permissions": {
        "mode": "default",
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
        rule_tool = rule.get("tool", "")
        if rule_tool and rule_tool != tool_name:
            continue

        matched = False

        cmd_pattern = rule.get("command_pattern", "")
        if cmd_pattern and tool_name == "bash":
            cmd = arguments.get("command", "")
            try:
                if re.match(cmd_pattern, cmd):
                    matched = True
            except re.error:
                continue

        path_pattern = rule.get("path_pattern", "")
        if path_pattern and tool_name in ("write", "edit", "read"):
            path = arguments.get("file_path", "")
            if fnmatch.fnmatch(path, path_pattern):
                matched = True

        if not cmd_pattern and not path_pattern and rule_tool == tool_name:
            matched = True

        if matched:
            action = rule.get("action", "")
            if action == "allow":
                return False
            elif action == "deny":
                return True
            elif action == "block":
                return True

    return None


# ── Classificacao de acoes por risco ──────────────────────────

ACTION_CLASSIFICATIONS = {
    "read": {"reversible": True, "external": False, "level": "safe"},
    "glob": {"reversible": True, "external": False, "level": "safe"},
    "grep": {"reversible": True, "external": False, "level": "safe"},
    "web_search": {"reversible": True, "external": False, "level": "safe"},
    "web_fetch": {"reversible": True, "external": False, "level": "safe"},
    "scraper": {"reversible": True, "external": False, "level": "safe"},
    "task_list": {"reversible": True, "external": False, "level": "safe"},
    "task_get": {"reversible": True, "external": False, "level": "safe"},
    "write": {"reversible": True, "external": False, "level": "write"},
    "edit": {"reversible": True, "external": False, "level": "write"},
    "task_create": {"reversible": True, "external": False, "level": "write"},
    "task_update": {"reversible": True, "external": False, "level": "write"},
    "notebook_edit": {"reversible": True, "external": False, "level": "write"},
    "pdf_tool": {"reversible": True, "external": False, "level": "write"},
    "spreadsheet": {"reversible": True, "external": False, "level": "write"},
    "image_gen": {"reversible": True, "external": True, "level": "write"},
    "git_advanced": {"reversible": False, "external": False, "level": "dangerous"},
    "bash": {"reversible": None, "external": None, "level": "varies"},
    "agent": {"reversible": None, "external": None, "level": "varies"},
    "whatsapp_send": {"reversible": False, "external": True, "level": "dangerous"},
    "http_request": {"reversible": None, "external": True, "level": "varies"},
    "supabase_query": {"reversible": False, "external": True, "level": "dangerous"},
    "n8n_workflow": {"reversible": False, "external": True, "level": "dangerous"},
    "docker_manage": {"reversible": False, "external": False, "level": "dangerous"},
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
    """Classifica acao completa por risco, reversibilidade e visibilidade."""
    base = ACTION_CLASSIFICATIONS.get(tool_name, {"reversible": None, "external": None, "level": "write"})
    result = dict(base)
    if tool_name == "bash":
        cmd = arguments.get("command", "")
        risk = classify_bash_command(cmd)
        result["level"] = risk
        result["reversible"] = risk == "safe"
        result["external"] = bool(re.search(r"curl|wget|ssh|scp|git\s+push", cmd))
    return result
