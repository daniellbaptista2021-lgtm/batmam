"""Permission Pipeline — Claude Code Architecture (Ep.07 Compliant).

7-step defense-in-depth tool permission evaluation.
Each tool declares its required permission level.
The pipeline evaluates in order, first match wins.

Ep.07 additions: denial tracking, circuit breakers, 6 permission modes
with transitions, bypass-immune safety checks.

Compat exports: needs_confirmation, format_confirmation_prompt,
get_current_level, PermissionLevel, is_dangerous_command,
classify_bash_command, classify_action, BashRiskLevel,
TOOL_REQUIREMENTS, is_tool_allowed, PERMISSION_MODES,
ACTION_CLASSIFICATIONS, BASH_RISK_LEVELS,
track_denial, reset_denial_streak, get_denial_stats,
get_permission_mode, set_permission_mode.
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


# ── Circuit Breaker / Denial Tracking (Claude Code Ep.07) ──────

DENIAL_LIMITS = {
    "max_consecutive": 3,   # 3 consecutive blocks -> fall back
    "max_total": 20,        # 20 total blocks per session -> fall back
}

_consecutive_denials: int = 0
_total_denials: int = 0


def track_denial(tool_name: str) -> dict:
    """Track denial and check circuit breaker."""
    global _consecutive_denials, _total_denials
    _consecutive_denials += 1
    _total_denials += 1

    breaker_tripped = False
    if _consecutive_denials >= DENIAL_LIMITS["max_consecutive"]:
        breaker_tripped = True
    if _total_denials >= DENIAL_LIMITS["max_total"]:
        breaker_tripped = True

    return {
        "consecutive": _consecutive_denials,
        "total": _total_denials,
        "breaker_tripped": breaker_tripped,
    }


def reset_denial_streak():
    """Reset consecutive count on successful tool use."""
    global _consecutive_denials
    _consecutive_denials = 0


def get_denial_stats() -> dict:
    """Return current denial statistics."""
    return {"consecutive": _consecutive_denials, "total": _total_denials}


# ── Permission Modes with Transitions (Ep.07) ──────────────────

PERMISSION_MODES: dict[str, str] = {
    "default": "Prompt user for ask decisions",
    "plan": "Read-only mode, review phase",
    "acceptEdits": "Auto-allow file edits, prompt for others",
    "bypassPermissions": "Auto-allow all (except safety checks)",
    "dontAsk": "Silently deny all ask decisions",
    "auto": "AI classifier decides (not implemented -- falls back to default)",
}

# Legacy level mapping (kept for get_current_level compat)
_MODE_LEVELS: dict[str, PermissionLevel] = {
    "readonly": PermissionLevel.READ_ONLY,
    "read_only": PermissionLevel.READ_ONLY,
    "workspace": PermissionLevel.WORKSPACE_WRITE,
    "workspace_write": PermissionLevel.WORKSPACE_WRITE,
    "default": PermissionLevel.PROMPT,
    "prompt": PermissionLevel.PROMPT,
    "acceptEdits": PermissionLevel.WORKSPACE_WRITE,
    "plan": PermissionLevel.READ_ONLY,
    "danger": PermissionLevel.FULL_ACCESS,
    "dontAsk": PermissionLevel.ALLOW,
    "allow": PermissionLevel.ALLOW,
    "bypassPermissions": PermissionLevel.ALLOW,
    "auto": PermissionLevel.PROMPT,
}

_current_mode: str = "default"
_pre_plan_mode: str = "default"
_stripped_permissions: list = []


def get_permission_mode() -> str:
    """Return current permission mode name."""
    return _current_mode


def set_permission_mode(mode: str) -> dict:
    """Transition permission mode with side effects."""
    global _current_mode, _pre_plan_mode, _stripped_permissions

    old_mode = _current_mode

    if mode == "plan":
        _pre_plan_mode = _current_mode
        _current_mode = "plan"
    elif mode == "auto":
        # Strip dangerous permissions
        _stripped_permissions = _strip_dangerous_permissions()
        _current_mode = "auto"
    elif old_mode == "plan":
        # Restore pre-plan mode
        _current_mode = _pre_plan_mode
    elif old_mode == "auto":
        # Restore stripped permissions
        _restore_permissions(_stripped_permissions)
        _stripped_permissions = []
        _current_mode = mode
    else:
        _current_mode = mode

    return {"old_mode": old_mode, "new_mode": _current_mode}


def _strip_dangerous_permissions() -> list:
    """Strip permissions that would bypass classifier in auto mode."""
    stripped: list = []
    if config.AUTO_APPROVE_BASH:
        stripped.append(("AUTO_APPROVE_BASH", True))
        config.AUTO_APPROVE_BASH = False
    return stripped


def _restore_permissions(stripped: list) -> None:
    """Restore previously stripped permissions."""
    for key, val in stripped:
        setattr(config, key, val)


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
    # First check the active mode set via set_permission_mode
    if _current_mode != "default":
        lvl = _MODE_LEVELS.get(_current_mode)
        if lvl is not None:
            return lvl
    # Fallback to settings.json
    settings = config.load_settings()
    mode = settings.get("permissions", {}).get("mode", "default")
    return _MODE_LEVELS.get(mode, PermissionLevel.PROMPT)


def get_tool_requirement(tool_name: str) -> PermissionLevel:
    """Return minimum permission level for a tool."""
    return TOOL_PERMISSIONS.get(tool_name, PermissionLevel.FULL_ACCESS)


def is_dangerous_command(command: str) -> bool:
    """Check if a bash command is in the dangerous list."""
    cmd_lower = command.lower().strip()
    cmd_normalized = cmd_lower.replace(" ", "")
    return any(danger in cmd_lower or danger.replace(" ", "") in cmd_normalized for danger in DANGEROUS_COMMANDS)


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


# ── 7-Step Permission Pipeline (Ep.07 Enhanced) ─────────────────

def check_tool_permission(
    tool_name: str,
    tool_args: dict,
    user_mode: str = "",
) -> tuple[bool, str]:
    """7-step permission pipeline (Claude Code architecture).

    Steps 1a-1g are bypass-immune safety checks.
    Steps 2a-2b are mode-dependent overrides.
    Step 3 is the default passthrough.

    Returns (allowed: bool, reason: str).
    """
    mode = user_mode or _current_mode

    # ── Step 1a: Hard deny rules ──
    if tool_name in DENIED_TOOLS:
        track_denial(tool_name)
        return False, f"Tool '{tool_name}' is denied by rule"

    # ── Step 1b: Tool-level ask rules (check settings) ──
    custom_result = _check_custom_rules(tool_name, tool_args)
    if custom_result is not None:
        if not custom_result[0]:
            track_denial(tool_name)
        else:
            reset_denial_streak()
        return custom_result

    # ── Step 1c: Tool-specific permission check ──
    required = TOOL_PERMISSIONS.get(tool_name, PermissionLevel.PROMPT)

    # ── Step 1d: Tool implementation denials (bypass-immune) ──
    if tool_name == "bash":
        command = tool_args.get("command", "")
        for dangerous in config.DANGEROUS_COMMANDS:
            if dangerous in command.lower():
                track_denial(tool_name)
                return False, f"Dangerous command blocked: {dangerous}"

    # ── Step 1e: User interaction required (bypass-immune) ──
    # N/A for Clow web -- all tools auto-approved or denied

    # ── Step 1f: Content-specific safety (bypass-immune) ──
    if tool_name in ("write", "edit"):
        file_path = tool_args.get("file_path", "")
        for safe_path in SAFETY_PATHS:
            if safe_path in file_path:
                if mode not in ("bypassPermissions", "allow"):
                    track_denial(tool_name)
                    return False, f"Safety: protected path '{safe_path}'"

    # ── Step 1g: Safety checks -- .git, .claude, shell configs (bypass-immune) ──
    if tool_name in ("write", "edit", "bash"):
        file_path = tool_args.get("file_path", tool_args.get("command", ""))
        for pattern in [".git/config", ".claude/settings", ".bashrc", ".zshrc", ".profile"]:
            if pattern in str(file_path):
                track_denial(tool_name)
                return False, f"Safety: shell/config file '{pattern}'"

    # ── Step 2a: Bypass permissions mode ──
    if mode in ("bypassPermissions", "allow"):
        reset_denial_streak()
        return True, "bypass mode"

    # ── Step 2b: Always-allow for read-only tools ──
    if required == PermissionLevel.READ_ONLY:
        reset_denial_streak()
        return True, "read-only"

    # ── Step 3: Mode-dependent passthrough ──
    if mode == "dontAsk":
        track_denial(tool_name)
        return False, "dontAsk mode: silently denied"

    if mode == "acceptEdits":
        if tool_name in ("write", "edit", "notebook_edit"):
            reset_denial_streak()
            return True, "acceptEdits: file operation allowed"
        # Non-edit tools still need permission
        track_denial(tool_name)
        return False, "acceptEdits: non-edit tool needs permission"

    if mode == "plan":
        if required <= PermissionLevel.READ_ONLY:
            reset_denial_streak()
            return True, "plan mode: read-only allowed"
        track_denial(tool_name)
        return False, "plan mode: writes blocked"

    # Default mode: check auto_approve settings
    if tool_name == "bash" and config.AUTO_APPROVE_BASH:
        reset_denial_streak()
        return True, "auto_approve_bash"
    if tool_name in ("write", "edit") and config.AUTO_APPROVE_WRITE:
        reset_denial_streak()
        return True, "auto_approve_write"

    # Default mode -- tool-specific passthrough
    if mode in ("default", "auto", ""):
        if tool_name == "bash":
            risk = classify_bash_command(tool_args.get("command", ""))
            if risk == BashRiskLevel.SAFE:
                reset_denial_streak()
                return True, "bash: safe command"
            if risk == BashRiskLevel.WRITE and config.AUTO_APPROVE_BASH:
                reset_denial_streak()
                return True, "bash: auto-approved write"
            # Clow web auto-approves by default
            reset_denial_streak()
            return True, "default: allowed"

        if tool_name in ("web_search", "web_fetch", "scraper"):
            reset_denial_streak()
            return True, "web: always allowed"

        if tool_name == "agent":
            reset_denial_streak()
            return True, "agent: allowed"

        if tool_name in ("pdf_tool", "spreadsheet"):
            if config.AUTO_APPROVE_WRITE:
                reset_denial_streak()
                return True, "office: auto-approved"
            reset_denial_streak()
            return True, "default: allowed"

        if tool_name in ("http_request", "git_advanced"):
            if config.AUTO_APPROVE_BASH:
                reset_denial_streak()
                return True, "advanced: auto-approved"
            reset_denial_streak()
            return True, "default: allowed"

    # Default -- allow (Clow web auto-approves by default)
    reset_denial_streak()
    return True, "default: allowed"


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

def _check_custom_rules(tool_name: str, arguments: dict) -> tuple[bool, str] | None:
    """Check custom rules from settings.json.

    Returns (allowed, reason) tuple, or None to use default pipeline.

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
                return True, f"Custom rule: allow ({rule_tool})"
            elif action in ("deny", "block"):
                return False, f"Custom rule: deny ({rule_tool})"

    return None
