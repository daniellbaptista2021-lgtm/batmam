"""Hook System — 20 Event Types, Full Lifecycle Interception (Claude Code Ep.05).

Hooks intercept every action: tool execution, session lifecycle, permissions.
Hooks can approve, deny, modify inputs, inject context, or stop the session.

Hook types: command (shell), http (webhook), function (callback)
Communication: JSON protocol via stdin/stdout
Aggregation: most restrictive wins (deny > allow)

Exit code convention (command hooks):
  Exit code 0 = Proceed normally (ALLOW)
  Exit code 1 = Log warning and continue (NON-BLOCKING)
  Exit code 2 = Stop / deny the action (BLOCKING)

Configured in ~/.clow/settings.json:

{
  "hooks": {
    "PreToolUse": [
      {"type": "command", "command": "python my_guard.py", "matcher": "Bash(git *)"},
      {"type": "http", "url": "https://example.com/hook", "timeout": 10}
    ],
    "SessionStart": ["echo session starting"],
    "PostToolUse": [
      {"type": "command", "command": "python audit.py", "matcher": "*"}
    ]
  }
}

Backward-compatible: legacy events (pre_tool_call, post_tool_call, etc.) are
mapped to new event names automatically.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import logging
import threading
from typing import Any, Callable
from dataclasses import dataclass, field
from . import config

logger = logging.getLogger("clow.hooks")

# ======================================================================
#  20 Hook Events
# ======================================================================

HOOK_EVENTS = {
    # Session lifecycle
    "SessionStart",
    "SessionEnd",
    "Setup",

    # Tool execution
    "PreToolUse",            # Most important -- can approve/deny/modify
    "PostToolUse",
    "PostToolUseFailure",

    # Permissions
    "PermissionDenied",
    "PermissionRequest",

    # Agent lifecycle
    "SubagentStart",
    "SubagentStop",
    "TeammateIdle",

    # Context events
    "UserPromptSubmit",
    "ConfigChange",
    "CwdChanged",
    "FileChanged",
    "InstructionsLoaded",

    # Task events
    "TaskCreated",
    "TaskCompleted",

    # Output events
    "Stop",
    "StopFailure",
}

# Legacy event name mapping (old -> new)
_LEGACY_EVENT_MAP = {
    "pre_tool_call":  "PreToolUse",
    "post_tool_call": "PostToolUse",
    "pre_turn":       "UserPromptSubmit",
    "post_turn":      "Stop",
    "on_error":       "PostToolUseFailure",
    "on_start":       "SessionStart",
    "on_exit":        "SessionEnd",
}

# Exit code convention
EXIT_SUCCESS = 0         # Proceed normally
EXIT_NON_BLOCKING = 1    # Log and continue
EXIT_BLOCKING = 2        # Stop the tool / deny

# Legacy aliases (backward compat)
EXIT_ALLOW = EXIT_SUCCESS
EXIT_DENY = EXIT_BLOCKING


# ======================================================================
#  Data Classes
# ======================================================================

@dataclass
class HookConfig:
    """Configuration for a single hook."""
    event: str
    hook_type: str = "command"   # command, http, function
    command: str = ""
    url: str = ""
    callback: Callable | None = None
    matcher: str = ""            # Tool matcher: "Bash", "Bash(git *)", "*"
    timeout: int = 30            # seconds
    async_mode: bool = False
    description: str = ""
    enabled: bool = True

    # Legacy compat fields
    tool: str = ""               # Legacy tool filter
    stop_on_failure: bool = False

    @classmethod
    def from_dict(cls, data: dict, event: str = "") -> "HookConfig":
        """Create from dict (settings.json format)."""
        return cls(
            event=event or data.get("event", ""),
            hook_type=data.get("type", data.get("hook_type", "command")),
            command=data.get("command", ""),
            url=data.get("url", ""),
            matcher=data.get("matcher", ""),
            timeout=data.get("timeout", 30),
            async_mode=data.get("async", data.get("async_mode", False)),
            description=data.get("description", ""),
            enabled=data.get("enabled", True),
            tool=data.get("tool", ""),
            stop_on_failure=data.get("stop_on_failure", False),
        )

    def to_dict(self) -> dict:
        """Serialize for settings.json."""
        d: dict[str, Any] = {"type": self.hook_type}
        if self.command:
            d["command"] = self.command
        if self.url:
            d["url"] = self.url
        if self.matcher:
            d["matcher"] = self.matcher
        if self.timeout != 30:
            d["timeout"] = self.timeout
        if self.async_mode:
            d["async"] = True
        if self.description:
            d["description"] = self.description
        if not self.enabled:
            d["enabled"] = False
        if self.tool:
            d["tool"] = self.tool
        if self.stop_on_failure:
            d["stop_on_failure"] = True
        return d


# Legacy alias
Hook = HookConfig


@dataclass
class HookResult:
    """Result from a hook execution.

    Exit code protocol:
      exit 0 = allow   -- hook approves; stdout as optional feedback
      exit 1 = warn    -- hook warns but allows; stdout as warning
      exit 2 = deny    -- hook blocks action; stdout as reason
    """
    hook_name: str = ""
    event: str = ""
    exit_code: int = 0
    output: str = ""
    json_output: dict = field(default_factory=dict)
    error: str = ""
    duration_ms: float = 0

    # Legacy fields
    hook: HookConfig | None = field(default=None, repr=False)
    success: bool = True
    return_code: int = 0
    action: str = "allow"   # allow, deny, warn

    @property
    def blocked(self) -> bool:
        """Whether this hook blocks the action (exit 2 / deny)."""
        if self.exit_code == EXIT_BLOCKING:
            return True
        if self.action == "deny":
            return True
        if self.hook and self.hook.stop_on_failure and not self.success:
            return True
        return False

    @property
    def is_warning(self) -> bool:
        """Whether this hook emitted a warning (exit 1)."""
        return self.exit_code == EXIT_NON_BLOCKING or self.action == "warn"

    @property
    def feedback(self) -> str:
        """Feedback to inject into the conversation."""
        parts: list[str] = []
        out = self.output.strip() if self.output else ""
        err = self.error.strip() if self.error else ""

        if out:
            if self.blocked:
                parts.append(f"[hook DENIED] {out}")
            elif self.is_warning:
                parts.append(f"[hook WARNING] {out}")
            else:
                parts.append(out)
        if err and not self.success:
            parts.append(f"[hook error] {err}")
        return "\n".join(parts)

    @property
    def permission_decision(self) -> str:
        """Get permission decision from JSON output."""
        hso = self.json_output.get("hookSpecificOutput", {})
        return hso.get("permissionDecision", "")

    @property
    def updated_input(self) -> dict | None:
        """Get updated tool input from JSON output."""
        hso = self.json_output.get("hookSpecificOutput", {})
        return hso.get("updatedInput")

    @property
    def should_continue(self) -> bool:
        """Whether the session should continue."""
        return self.json_output.get("continue", True)


# ======================================================================
#  Hook Runner
# ======================================================================

class HookRunner:
    """Execute hooks with matching, aggregation, and lifecycle management.

    Supports three hook types:
      - command: shell scripts receiving JSON via stdin
      - http: webhook POST with JSON body
      - function: in-process Python callback

    Pattern matching:
      - "*"           -> matches everything
      - "Bash"        -> matches tool name exactly
      - "Bash(git *)" -> matches tool + command prefix
    """

    # Legacy class-level event set (backward compat)
    VALID_EVENTS = {
        "pre_tool_call", "post_tool_call", "pre_turn",
        "post_turn", "on_error", "on_start", "on_exit",
    } | HOOK_EVENTS

    def __init__(self, auto_load: bool = True) -> None:
        self._hooks: list[HookConfig] = []
        self._async_hooks: dict[str, threading.Thread] = {}
        self._hook_count: int = 0
        self._lock = threading.Lock()
        if auto_load:
            self.load_from_settings()

    # -- Registration ----------------------------------------------

    def register(self, hook: HookConfig) -> None:
        """Register a hook."""
        if hook.event not in HOOK_EVENTS and hook.event not in _LEGACY_EVENT_MAP:
            logger.warning(f"Unknown hook event: {hook.event}")
        with self._lock:
            self._hooks.append(hook)
        logger.debug(f"Hook registered: {hook.event} ({hook.hook_type})")

    def register_command(self, event: str, command: str, matcher: str = "") -> None:
        """Register a command (shell) hook."""
        self.register(HookConfig(
            event=event, hook_type="command",
            command=command, matcher=matcher,
        ))

    def register_http(self, event: str, url: str, matcher: str = "") -> None:
        """Register an HTTP webhook hook."""
        self.register(HookConfig(
            event=event, hook_type="http",
            url=url, matcher=matcher,
        ))

    def register_function(self, event: str, callback: Callable, matcher: str = "") -> None:
        """Register an in-process function hook."""
        self.register(HookConfig(
            event=event, hook_type="function",
            callback=callback, matcher=matcher,
        ))

    def unregister_all(self, event: str = "") -> int:
        """Unregister hooks. If event specified, only that event."""
        with self._lock:
            before = len(self._hooks)
            if event:
                self._hooks = [h for h in self._hooks if h.event != event]
            else:
                self._hooks.clear()
            return before - len(self._hooks)

    def add_hook(self, hook: HookConfig) -> None:
        """Add hook and persist to settings (legacy compat)."""
        if hook.event in _LEGACY_EVENT_MAP:
            hook.event = _LEGACY_EVENT_MAP[hook.event]
        self.register(hook)
        self._save_hooks()

    def remove_hook(self, event: str, index: int) -> bool:
        """Remove hook by index within an event (legacy compat)."""
        event_hooks = [h for h in self._hooks if h.event == event]
        if 0 <= index < len(event_hooks):
            target = event_hooks[index]
            with self._lock:
                self._hooks.remove(target)
            self._save_hooks()
            return True
        return False

    # -- Execution -------------------------------------------------

    def run_hooks(
        self,
        event: str,
        context: dict[str, Any] | None = None,
        cwd: str = "",
    ) -> list[HookResult]:
        """Run all matching hooks for an event.

        Aggregation: most restrictive wins.
        - Any "deny" -> deny
        - Any "blocking" (exit 2) -> stop
        - Multiple "updatedInput" -> last one wins

        Args:
            event: Hook event name (new or legacy).
            context: Dict with tool_name, tool_args, session_id, etc.
            cwd: Working directory for command hooks.

        Returns:
            List of HookResult for each executed hook.
        """
        context = context or {}

        # Resolve legacy event names
        canonical = _LEGACY_EVENT_MAP.get(event, event)

        matching = self._match_hooks(canonical, context)
        # Also match hooks registered under legacy names
        if event != canonical:
            matching += self._match_hooks(event, context)

        if not matching:
            return []

        results: list[HookResult] = []
        for hook in matching:
            if not hook.enabled:
                continue
            try:
                if hook.async_mode:
                    self._run_async(hook, context, cwd)
                    continue

                result = self._execute_hook(hook, context, cwd)
                results.append(result)
                self._hook_count += 1

                # Short-circuit on blocking error
                if result.blocked:
                    logger.warning(
                        f"Hook blocked: {hook.event} by "
                        f"{hook.command or hook.url or 'function'}"
                    )
                    break

                # Short-circuit on "continue: false"
                if not result.should_continue:
                    logger.info(f"Hook stopped session: {hook.event}")
                    break

            except Exception as e:
                logger.error(f"Hook execution error: {hook.event} - {e}")
                results.append(HookResult(
                    hook_name=hook.command or hook.url or "function",
                    event=canonical,
                    exit_code=EXIT_NON_BLOCKING,
                    error=str(e),
                    success=False,
                    action="warn",
                ))

        return results

    def has_hooks(self, event: str) -> bool:
        """Check if any hooks are registered for an event."""
        canonical = _LEGACY_EVENT_MAP.get(event, event)
        return any(
            h.event == canonical or h.event == event
            for h in self._hooks if h.enabled
        )

    # -- Matching --------------------------------------------------

    def _match_hooks(self, event: str, context: dict) -> list[HookConfig]:
        """Find hooks matching this event and context."""
        matching: list[HookConfig] = []
        tool_name = context.get("tool_name", "")

        with self._lock:
            for hook in self._hooks:
                if hook.event != event:
                    continue

                # Legacy tool filter
                if hook.tool and hook.tool != tool_name:
                    continue

                # New matcher pattern
                if hook.matcher:
                    if not self._matches_pattern(hook.matcher, tool_name, context):
                        continue

                matching.append(hook)

        return matching

    @staticmethod
    def _matches_pattern(pattern: str, tool_name: str, context: dict) -> bool:
        """Match hook pattern against tool name and context.

        Patterns:
          "*"              -> matches everything
          "Bash"           -> matches tool name exactly
          "Bash(git *)"    -> matches tool + command prefix
          "Read(*test*)"   -> matches tool + arg content
        """
        if pattern == "*":
            return True

        if "(" not in pattern:
            return pattern.lower() == tool_name.lower()

        # Pattern with content: "Bash(git *)"
        m = re.match(r"(\w+)\((.+)\)", pattern)
        if not m:
            return False

        pat_tool = m.group(1)
        pat_content = m.group(2)

        if pat_tool.lower() != tool_name.lower():
            return False

        # Match content against tool args
        tool_args = context.get("tool_args", "")
        if isinstance(tool_args, dict):
            tool_args = json.dumps(tool_args)

        # Convert glob-style pattern to regex
        content_re = pat_content.replace("*", ".*").replace("?", ".")
        return bool(re.match(content_re, str(tool_args), re.IGNORECASE))

    # -- Hook Execution --------------------------------------------

    def _execute_hook(
        self, hook: HookConfig, context: dict, cwd: str,
    ) -> HookResult:
        """Execute a single hook and parse the result."""
        start = time.time()

        # Build JSON input payload
        json_input = json.dumps({
            "session_id": context.get("session_id", ""),
            "event": hook.event,
            "cwd": cwd or os.getcwd(),
            "tool_name": context.get("tool_name", ""),
            "tool_input": context.get("tool_args", {}),
            "tool_output": context.get("tool_output", ""),
            "tool_status": context.get("tool_status", ""),
            "user_message": context.get("user_message", ""),
            "error": context.get("error", ""),
        }, ensure_ascii=False)

        if hook.hook_type == "command":
            return self._run_command(hook, json_input, context, cwd, start)
        elif hook.hook_type == "http":
            return self._run_http(hook, json_input, start)
        elif hook.hook_type == "function":
            return self._run_function(hook, context, start)
        else:
            return HookResult(
                hook_name=hook.command or hook.url or "function",
                event=hook.event,
                exit_code=EXIT_NON_BLOCKING,
                error=f"Unknown hook type: {hook.hook_type}",
                success=False,
                action="warn",
            )

    def _run_command(
        self, hook: HookConfig, json_input: str,
        context: dict, cwd: str, start: float,
    ) -> HookResult:
        """Run a command hook (shell script).

        The hook receives:
          - JSON payload via stdin
          - Environment variables: HOOK_EVENT, HOOK_TOOL_NAME, etc.
          - Legacy CLOW_* env vars for backward compat
        """
        # Substitute context variables in command (legacy compat)
        command = hook.command
        for key, value in context.items():
            command = command.replace(f"${{{key}}}", str(value))
            command = command.replace(f"${key}", str(value))

        # Build environment with HOOK_* and legacy CLOW_* vars
        env = {**os.environ}
        env["HOOK_EVENT"] = hook.event
        env["HOOK_CWD"] = cwd or os.getcwd()
        if "tool_name" in context:
            env["HOOK_TOOL_NAME"] = str(context["tool_name"])
        if "tool_args" in context:
            env["HOOK_TOOL_INPUT"] = str(context["tool_args"])[:2000]
        if "tool_output" in context:
            env["HOOK_TOOL_OUTPUT"] = str(context["tool_output"])[:2000]
        if "tool_status" in context:
            env["HOOK_TOOL_IS_ERROR"] = (
                "true" if context["tool_status"] == "error" else "false"
            )
        if "user_message" in context:
            env["HOOK_USER_MESSAGE"] = str(context["user_message"])[:2000]
        if "error" in context:
            env["HOOK_ERROR"] = str(context["error"])[:2000]
        # Legacy env vars
        env["CLOW_EVENT"] = hook.event
        env["CLOW_CWD"] = cwd or os.getcwd()
        for key, value in context.items():
            env[f"CLOW_{key.upper()}"] = str(value)[:1000]

        try:
            proc = subprocess.run(
                command,
                shell=True,
                input=json_input,
                capture_output=True,
                text=True,
                timeout=hook.timeout,
                cwd=cwd or None,
                env=env,
            )

            duration = (time.time() - start) * 1000
            output = proc.stdout.strip()
            error = proc.stderr.strip()

            # Determine action from exit code
            if proc.returncode == EXIT_SUCCESS:
                action = "allow"
            elif proc.returncode == EXIT_BLOCKING:
                action = "deny"
            else:
                action = "warn"

            # Try to parse JSON output from stdout
            json_output: dict = {}
            try:
                json_output = json.loads(output)
            except (json.JSONDecodeError, TypeError):
                pass  # Plain text output is fine

            return HookResult(
                hook_name=hook.command,
                event=hook.event,
                exit_code=proc.returncode,
                output=output,
                json_output=json_output,
                error=error,
                duration_ms=duration,
                hook=hook,
                success=(proc.returncode == EXIT_SUCCESS),
                return_code=proc.returncode,
                action=action,
            )
        except subprocess.TimeoutExpired:
            duration = (time.time() - start) * 1000
            return HookResult(
                hook_name=hook.command,
                event=hook.event,
                exit_code=EXIT_NON_BLOCKING,
                error=f"Hook timed out ({hook.timeout}s)",
                duration_ms=duration,
                hook=hook,
                success=False,
                return_code=-1,
                action="warn",
            )
        except Exception as e:
            return HookResult(
                hook_name=hook.command,
                event=hook.event,
                exit_code=EXIT_NON_BLOCKING,
                error=str(e),
                duration_ms=(time.time() - start) * 1000,
                hook=hook,
                success=False,
                return_code=-1,
                action="warn",
            )

    def _run_http(
        self, hook: HookConfig, json_input: str, start: float,
    ) -> HookResult:
        """Run an HTTP webhook hook (POST with JSON body)."""
        try:
            from urllib.request import urlopen, Request

            req = Request(
                hook.url,
                data=json_input.encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urlopen(req, timeout=hook.timeout)
            output = resp.read().decode("utf-8")
            duration = (time.time() - start) * 1000
            status_code = resp.getcode()

            json_output: dict = {}
            try:
                json_output = json.loads(output)
            except (json.JSONDecodeError, TypeError):
                pass

            # HTTP 2xx = success, 4xx/5xx = error
            if 200 <= status_code < 300:
                exit_code = EXIT_SUCCESS
                action = "allow"
            elif status_code == 403:
                exit_code = EXIT_BLOCKING
                action = "deny"
            else:
                exit_code = EXIT_NON_BLOCKING
                action = "warn"

            return HookResult(
                hook_name=hook.url,
                event=hook.event,
                exit_code=exit_code,
                output=output,
                json_output=json_output,
                duration_ms=duration,
                hook=hook,
                success=(exit_code == EXIT_SUCCESS),
                return_code=exit_code,
                action=action,
            )
        except Exception as e:
            return HookResult(
                hook_name=hook.url,
                event=hook.event,
                exit_code=EXIT_NON_BLOCKING,
                error=str(e),
                duration_ms=(time.time() - start) * 1000,
                hook=hook,
                success=False,
                return_code=-1,
                action="warn",
            )

    def _run_function(
        self, hook: HookConfig, context: dict, start: float,
    ) -> HookResult:
        """Run an in-process function hook."""
        try:
            result = hook.callback(context) if hook.callback else None
            duration = (time.time() - start) * 1000

            if isinstance(result, dict):
                # Function can return {"action": "deny", "reason": "..."}
                action = result.get("action", "allow")
                exit_code = (
                    EXIT_BLOCKING if action == "deny"
                    else EXIT_NON_BLOCKING if action == "warn"
                    else EXIT_SUCCESS
                )
                return HookResult(
                    hook_name="function",
                    event=hook.event,
                    exit_code=exit_code,
                    json_output=result,
                    output=result.get("reason", result.get("output", "")),
                    duration_ms=duration,
                    hook=hook,
                    success=(action != "deny"),
                    return_code=exit_code,
                    action=action,
                )
            elif isinstance(result, str):
                return HookResult(
                    hook_name="function",
                    event=hook.event,
                    exit_code=EXIT_SUCCESS,
                    output=result,
                    duration_ms=duration,
                    hook=hook,
                    success=True,
                    return_code=0,
                    action="allow",
                )
            else:
                return HookResult(
                    hook_name="function",
                    event=hook.event,
                    exit_code=EXIT_SUCCESS,
                    duration_ms=duration,
                    hook=hook,
                    success=True,
                    return_code=0,
                    action="allow",
                )
        except Exception as e:
            return HookResult(
                hook_name="function",
                event=hook.event,
                exit_code=EXIT_NON_BLOCKING,
                error=str(e),
                duration_ms=(time.time() - start) * 1000,
                hook=hook,
                success=False,
                return_code=-1,
                action="warn",
            )

    def _run_async(
        self, hook: HookConfig, context: dict, cwd: str,
    ) -> None:
        """Run hook asynchronously in a background thread."""
        def _worker() -> None:
            try:
                self._execute_hook(hook, context, cwd)
            except Exception as e:
                logger.error(f"Async hook error ({hook.event}): {e}")

        thread_name = f"hook-{hook.event}-{time.time():.0f}"
        t = threading.Thread(target=_worker, daemon=True, name=thread_name)
        with self._lock:
            self._async_hooks[thread_name] = t
        t.start()

    # -- Settings I/O ----------------------------------------------

    def load_from_settings(self) -> int:
        """Load hooks from settings.json.

        Supports both new-style and legacy formats:
          New: {"hooks": {"PreToolUse": [{"type": "command", ...}]}}
          Legacy: {"hooks": {"pre_tool_call": [{"event": "...", ...}]}}
        """
        settings = config.load_settings()
        hooks_config = settings.get("hooks", {})
        count = 0

        for event_name, hook_list in hooks_config.items():
            # Normalize legacy event names
            canonical = _LEGACY_EVENT_MAP.get(event_name, event_name)

            if canonical not in HOOK_EVENTS:
                logger.debug(f"Skipping unknown hook event: {event_name}")
                continue

            if not isinstance(hook_list, list):
                hook_list = [hook_list]

            for hook_def in hook_list:
                if isinstance(hook_def, str):
                    # Simple command string: "echo hello"
                    self.register_command(canonical, hook_def)
                    count += 1
                elif isinstance(hook_def, dict):
                    hook = HookConfig.from_dict(hook_def, event=canonical)
                    if hook.enabled:
                        self.register(hook)
                        count += 1

        if count:
            logger.info(f"Loaded {count} hooks from settings")
        return count

    def reload(self) -> None:
        """Reload hooks from disk (clear and re-load)."""
        with self._lock:
            self._hooks.clear()
        self.load_from_settings()

    def _save_hooks(self) -> None:
        """Persist current hooks to settings.json."""
        settings = config.load_settings()
        hooks_dict: dict[str, list[dict]] = {}

        for hook in self._hooks:
            event = hook.event
            if event not in hooks_dict:
                hooks_dict[event] = []
            hooks_dict[event].append(hook.to_dict())

        settings["hooks"] = hooks_dict
        config.save_settings(settings)

    # -- Introspection ---------------------------------------------

    def list_hooks(self) -> dict[str, list[HookConfig]]:
        """List all registered hooks grouped by event."""
        result: dict[str, list[HookConfig]] = {}
        for h in self._hooks:
            if h.event not in result:
                result[h.event] = []
            result[h.event].append(h)
        return {e: hooks for e, hooks in result.items() if hooks}

    def get_hooks_by_event(self) -> dict[str, int]:
        """Get count of hooks per event."""
        counts: dict[str, int] = {}
        for h in self._hooks:
            counts[h.event] = counts.get(h.event, 0) + 1
        return counts

    @property
    def hook_count(self) -> int:
        """Total number of hooks executed since creation."""
        return self._hook_count

    @property
    def registered_count(self) -> int:
        """Total number of registered hooks."""
        return len(self._hooks)


# ======================================================================
#  Aggregation
# ======================================================================

def aggregate_results(results: list[HookResult]) -> dict:
    """Aggregate multiple hook results (most restrictive wins).

    Rules:
      - Any "deny" -> deny
      - Any "blocking" (exit 2) -> stop
      - Multiple "updatedInput" -> last one wins
      - "continue: false" -> stop session

    Returns dict with:
      allowed: bool, blocked: bool, updated_input: dict|None,
      should_continue: bool, messages: list[str]
    """
    if not results:
        return {
            "allowed": True,
            "blocked": False,
            "updated_input": None,
            "should_continue": True,
            "messages": [],
        }

    allowed = True
    blocked = False
    messages: list[str] = []
    updated_input: dict | None = None
    should_continue = True

    for r in results:
        if r.blocked:
            blocked = True
            allowed = False

        if r.permission_decision == "deny":
            allowed = False

        if r.updated_input is not None:
            updated_input = r.updated_input

        if not r.should_continue:
            should_continue = False

        fb = r.feedback
        if fb:
            messages.append(fb)

    return {
        "allowed": allowed and not blocked,
        "blocked": blocked,
        "updated_input": updated_input,
        "should_continue": should_continue,
        "messages": messages,
    }


# ======================================================================
#  Convenience helpers
# ======================================================================

def run_event(
    runner: HookRunner,
    event: str,
    context: dict | None = None,
    cwd: str = "",
) -> dict:
    """Run hooks for an event and return aggregated result.

    Convenience wrapper combining run_hooks + aggregate_results.
    """
    results = runner.run_hooks(event, context or {}, cwd)
    return aggregate_results(results)


def check_tool_permission(
    runner: HookRunner,
    tool_name: str,
    tool_args: Any = None,
    cwd: str = "",
) -> dict:
    """Check PreToolUse hooks for a tool call.

    Returns aggregated dict -- caller checks result["allowed"].
    """
    context = {
        "tool_name": tool_name,
        "tool_args": tool_args or {},
    }
    return run_event(runner, "PreToolUse", context, cwd)


def notify_tool_result(
    runner: HookRunner,
    tool_name: str,
    tool_args: Any = None,
    tool_output: str = "",
    tool_status: str = "success",
    cwd: str = "",
) -> list[HookResult]:
    """Notify PostToolUse hooks of a tool result.

    If tool_status == "error", also fires PostToolUseFailure.
    """
    context = {
        "tool_name": tool_name,
        "tool_args": tool_args or {},
        "tool_output": tool_output,
        "tool_status": tool_status,
    }
    results = runner.run_hooks("PostToolUse", context, cwd)

    if tool_status == "error":
        results += runner.run_hooks("PostToolUseFailure", context, cwd)

    return results
