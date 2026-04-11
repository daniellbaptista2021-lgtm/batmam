"""Permission Pipeline — Claude Code Architecture.

7-step defense-in-depth tool permission evaluation.
Each tool declares its required permission level.
The pipeline evaluates in order, first match wins.

Compat exports: needs_confirmation, format_confirmation_prompt,
get_current_level, PermissionLevel, is_dangerous_command,
classify_bash_command, classify_action, BashRiskLevel,
TOOL_REQUIREMENTS, is_tool_allowed, PERMISSION_MODES,
ACTION_CLASSIFICATIONS, BASH_RISK_LEVELS.
"""

from __future__ import annotations
import re
import fnmatch
from enum import IntEnum, Enum
from . import config


# ── Permission Levels (5 tiers) ────────────────────────────────

class PermissionLevel(IntEnum):
    """Permission levels in ascending order of access."""
    READ_ONLY = 0
    WORKSPACE_WRITE = 1
    PROMPT = 2           # Default — ask user
    FULL_ACCESS = 3
    ALLOW = 4


# Legacy alias
DANGER_FULL_ACCESS = PermissionLevel.FULL_ACCESS


# Permission requirements per tool (Claude Code pattern)
TOOL_PERMISSIONS: dict[str, PermissionLevel] = {
    # Read-only — always allowed, no permission needed
    "read": PermissionLevel.READ_ONLY,
    "glob": PermissionLevel.READ_ONLY,
    "grep": PermissionLevel.READ_ONLY,
    "web_search": PermissionLevel.READ_ONLY,
    "web_fetch": PermissionLevel.READ_ONLY,
    "scraper": PermissionLevel.READ_ONLY,
    "task_list": PermissionLevel.READ_ONLY,
    "task_get": PermissionLevel.READ_ONLY,

    # Workspace write — needs permission for writes
    "write": PermissionLevel.WORKSPACE_WRITE,
    "edit": PermissionLevel.WORKSPACE_WRITE,
    "task_create": PermissionLevel.WORKSPACE_WRITE,
    "task_update": PermissionLevel.WORKSPACE_WRITE,
    "notebook_edit": PermissionLevel.WORKSPACE_WRITE,
    "pdf_tool": PermissionLevel.WORKSPACE_WRITE,
    "spreadsheet": PermissionLevel.WORKSPACE_WRITE,
    "agent": PermissionLevel.WORKSPACE_WRITE,

    # Full access — dangerous tools
    "bash": PermissionLevel.FULL_ACCESS,
    "git_ops": PermissionLevel.FULL_ACCESS,
    "git_advanced": PermissionLevel.FULL_ACCESS,
    "docker_manage": PermissionLevel.FULL_ACCESS,
    "ssh_connect": PermissionLevel.FULL_ACCESS,
    "deploy_vercel": PermissionLevel.FULL_ACCESS,
    "deploy_vps": PermissionLevel.FULL_ACCESS,
    "whatsapp_send": PermissionLevel.FULL_ACCESS,
    "http_request": PermissionLevel.FULL_ACCESS,
    "supabase_query": PermissionLevel.FULL_ACCESS,
    "n8n_workflow": PermissionLevel.FULL_ACCESS,
}

# Backward compat alias
TOOL_REQUIREMENTS = TOOL_PERMISSIONS

# Tools that are NEVER allowed regardless of permission
DENIED_TOOLS: set[str] = set()

# Safety-critical paths that require permission even in auto mode
SAFETY_PATHS = [".env", ".git/", ".claude/", "settings.json", "credentials"]

# Dangerous bash commands that always need confirmation
DANGEROUS_COMMANDS = config.DANGEROUS_COMMANDS

# Mode name -> level mapping (settings.json)
PERMISSION_MODES: dict[str, PermissionLevel] = {
    "readonly": PermissionLevel.READ_ONLY,
    "read_only": PermissionLevel.READ_ONLY,
    "workspace": PermissionLevel.WORKSPACE_WRITE,
    "workspace_write": PermissionLevel.WORKSPACE_WRITE,
    "default": PermissionLevel.PROMPT,
    "prompt": PermissionLevel.PROMPT,
    "acceptEdits": PermissionLevel.WORKSPACE_WRITE,
    "danger": PermissionLevel.FULL_ACCESS,
    "dontAsk": PermissionLevel.ALLOW,
    "allow": PermissionLevel.ALLOW,
}


# ── Bash Risk Classification ────────────────────────────────────

class BashRiskLevel(str, Enum):
    """Risk levels for bash commands."""
    SAFE = "safe"
    WRITE = "write"
    DANGEROUS = "dangerous"
    BLOCKED = "blocked"


BASH_RISK_LEVELS = {
    BashRiskLevel.SAFE: [
        r"^ls\b", r"^cat\b", r"^head\b", r"^tail\b", r"^wc\b",
        r"^echo\b", r"^pwd\b", r"^which\b", r"^whoami\b",
        r"^date\b", r"^env\b", r"^printenv\b",
        r"^git\s+status", r"^git\s+log", r"^git\s+diff",
        r"^git\s+branch\b(?!.*-[dD])", r"^git\s+show",
        r"^python\s+-c\b", r"^node\s+-e\b",
        r"^pip\s+list", r"^pip\s+show", r"^npm\s+list",
    ],
    BashRiskLevel.WRITE: [
        r"^git\s+add\b", r"^git\s+commit\b",
        r"^pip\s+install\b", r"^npm\s+install\b",
        r"^mkdir\b", r"^touch\b", r"^cp\b", r"^mv\b",
    ],
    BashRiskLevel.DANGEROUS: [
        r"^rm\b", r"^git\s+push\b", r"^git\s+reset\b",
        r"^git\s+checkout\s+--", r"^git\s+clean\b",
        r"^git\s+branch\s+-[dD]\b", r"^git\s+stash\s+drop",
        r"^docker\s+rm\b", r"^docker\s+rmi\b",
        r"^kill\b", r"^pkill\b", r"^shutdown\b", r"^reboot\b",
        r"^chmod\b", r"^chown\b", r"^sudo\b",
    ],
}


# Action risk classifications
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
    "git_advanced": {"reversible": False, "external": False, "level": "dangerous"},
    "bash": {"reversible": None, "external": None, "level": "varies"},
    "agent": {"reversible": None, "external": None, "level": "varies"},
    "whatsapp_send": {"reversible": False, "external": True, "level": "dangerous"},
    "http_request": {"reversible": None, "external": True, "level": "varies"},
    "supabase_query": {"reversible": False, "external": True, "level": "dangerous"},
    "n8n_workflow": {"reversible": False, "external": True, "level": "dangerous"},
    "docker_manage": {"reversible": False, "external": False, "level": "dangerous"},
}


# ── Core API ────────────────────────────────────────────────────

def get_current_level() -> PermissionLevel:
    """Return current permission level from config and settings."""
    settings = config.load_settings()
    mode = settings.get("permissions", {}).get("mode", "default")
    return PERMISSION_MODES.get(mode, PermissionLevel.PROMPT)


def get_tool_requirement(tool_name: str) -> PermissionLevel:
    """Return minimum permission level for a tool."""
    return TOOL_PERMISSIONS.get(tool_name, PermissionLevel.FULL_ACCESS)


def is_dangerous_command(command: str) -> bool:
    """Check if a bash command is in the dangerous list."""
    cmd_lower = command.lower().strip()
    return any(danger in cmd_lower for danger in DANGEROUS_COMMANDS)


def classify_bash_command(command: str) -> str:
    """Classify bash command risk: safe, write, dangerous, blocked."""
    cmd = command.strip()
    if is_dangerous_command(cmd):
        return BashRiskLevel.BLOCKED
    for level in [BashRiskLevel.SAFE, BashRiskLevel.DANGEROUS, BashRiskLevel.WRITE]:
        for pattern in BASH_RISK_LEVELS.get(level, []):
            if re.match(pattern, cmd, re.IGNORECASE):
                return level
    return BashRiskLevel.WRITE


def classify_action(tool_name: str, arguments: dict) -> dict:
    """Classify full action by risk, reversibility and visibility."""
    base = ACTION_CLASSIFICATIONS.get(
        tool_name, {"reversible": None, "external": None, "level": "write"}
    )
    result = dict(base)
    if tool_name == "bash":
        cmd = arguments.get("command", "")
        risk = classify_bash_command(cmd)
        result["level"] = risk
        result["reversible"] = risk == BashRiskLevel.SAFE
        result["external"] = bool(re.search(r"curl|wget|ssh|scp|git\s+push", cmd))
    return result


def is_tool_allowed(tool_name: str) -> bool:
    """Check if tool is allowed at current level (no prompt)."""
    current = get_current_level()
    required = get_tool_requirement(tool_name)
    return current >= required


# ── 7-Step Permission Pipeline ──────────────────────────────────

def check_tool_permission(
    tool_name: str,
    tool_args: dict,
    user_mode: str | None = None,
) -> tuple[bool, str]:
    """7-step defense-in-depth permission check pipeline.

    Returns (allowed: bool, reason: str).

    Steps:
      1. Tool-level deny rules          — hard deny
      2. Tool-level ask rules            — sandbox override
      3. Tool-specific content check     — content validation
      4. Tool denials                    — bypass-immune
      5. User interaction required       — bypass-immune
      6. Content-specific ask rules      — bypass-immune
      7. Safety checks (.git, .env, etc) — bypass-immune
    """
    if user_mode is None:
        level = get_current_level()
        if level == PermissionLevel.ALLOW:
            user_mode = "allow"
        elif level == PermissionLevel.READ_ONLY:
            user_mode = "deny"
        elif level == PermissionLevel.FULL_ACCESS:
            user_mode = "allow"
        else:
            user_mode = "prompt"

    # Step 1: Hard deny rules — tool is blacklisted
    if tool_name in DENIED_TOOLS:
        return False, f"Tool '{tool_name}' is denied"

    # Step 2: Custom rules from settings.json (tool-level ask/allow/deny)
    custom_result = _check_custom_rules(tool_name, tool_args)
    if custom_result is not None:
        if custom_result:  # needs confirmation -> deny in pipeline
            return False, "Custom rule: deny"
        else:
            return True, "Custom rule: allow"

    # Step 3: Tool permission level check
    required = TOOL_PERMISSIONS.get(tool_name, PermissionLevel.PROMPT)

    # Read-only tools always allowed
    if required == PermissionLevel.READ_ONLY:
        return True, "read-only"

    # Step 4: User mode evaluation
    if user_mode == "allow":
        # Auto-approve mode — continue to safety checks
        pass
    elif user_mode == "deny":
        if required > PermissionLevel.READ_ONLY:
            return False, "User mode: deny non-read tools"

    # Step 5: Content-specific safety checks for bash
    if tool_name == "bash":
        command = tool_args.get("command", "")
        for dangerous in DANGEROUS_COMMANDS:
            if dangerous in command.lower():
                return False, f"Dangerous command: {dangerous}"

    # Step 6: File path safety checks for write/edit
    if tool_name in ("write", "edit"):
        file_path = tool_args.get("file_path", "")
        for safe_path in SAFETY_PATHS:
            if safe_path in file_path:
                # Safety paths need explicit confirmation
                if user_mode != "allow":
                    return False, f"Safety path: {safe_path}"

    # Step 7: Prompt mode — non-read tools need confirmation
    if user_mode == "prompt":
        if tool_name == "bash":
            risk = classify_bash_command(tool_args.get("command", ""))
            if risk == BashRiskLevel.SAFE:
                return True, "bash: safe command"
            if risk == BashRiskLevel.WRITE and config.AUTO_APPROVE_BASH:
                return True, "bash: auto-approved write"
            return False, "bash: needs confirmation"

        if tool_name in ("write", "edit"):
            if config.AUTO_APPROVE_WRITE:
                return True, "write: auto-approved"
            return False, "write: needs confirmation"

        if tool_name in ("web_search", "web_fetch", "scraper"):
            return True, "web: always allowed"

        if tool_name == "agent":
            return True, "agent: allowed"

        if tool_name in ("pdf_tool", "spreadsheet"):
            if config.AUTO_APPROVE_WRITE:
                return True, "office: auto-approved"
            return False, "office: needs confirmation"

        if tool_name in ("http_request", "git_advanced"):
            if config.AUTO_APPROVE_BASH:
                return True, "advanced: auto-approved"
            return False, "advanced: needs confirmation"

        # Default for prompt mode: require confirmation
        if required > PermissionLevel.WORKSPACE_WRITE:
            return False, "dangerous tool: needs confirmation"
        return False, "prompt mode: needs confirmation"

    # Default — allow
    return True, "allowed"


# ── Legacy Compat API ───────────────────────────────────────────

def needs_confirmation(tool_name: str, arguments: dict) -> bool:
    """Check if tool needs user confirmation (legacy compat).

    Uses the 7-step pipeline internally.
    """
    allowed, reason = check_tool_permission(tool_name, arguments)
    return not allowed


def format_confirmation_prompt(tool_name: str, arguments: dict) -> str:
    """Format confirmation prompt for user (Claude Code style)."""
    if tool_name == "bash":
        cmd = arguments.get("command", "")
        danger = " \033[31m[DANGER]\033[0m" if is_dangerous_command(cmd) else ""
        return f"Run bash command?{danger}\n  \033[36m$\033[0m {cmd}"

    elif tool_name == "write":
        path = arguments.get("file_path", "")
        content = arguments.get("content", "")
        lines = content.count("\n") + 1
        return f"Create file {path}?\n  {lines} lines"

    elif tool_name == "edit":
        path = arguments.get("file_path", "")
        old = arguments.get("old_string", "")[:100]
        new = arguments.get("new_string", "")[:100]
        return f"Edit {path}?\n  \033[31m- {old!r}\033[0m\n  \033[32m+ {new!r}\033[0m"

    elif tool_name == "notebook_edit":
        path = arguments.get("file_path", "")
        return f"Edit notebook {path}?"

    return f"Execute {tool_name}?"


# ── Custom Rules Engine ─────────────────────────────────────────

def _check_custom_rules(tool_name: str, arguments: dict) -> bool | None:
    """Check custom rules from settings.json.

    Returns True (needs confirmation), False (auto-approve), or None (use default).

    Format in settings.json:
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
            elif action in ("deny", "block"):
                return True

    return None
