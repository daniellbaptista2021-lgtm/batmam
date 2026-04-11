"""Config Tool - read/write Clow configuration."""

from __future__ import annotations
import json
from typing import Any
from .base import BaseTool


class ConfigTool(BaseTool):
    """Read and write Clow configuration."""

    name = "config"
    description = (
        "Read or write Clow configuration settings. Can read all settings, "
        "get a specific key, or set a key-value pair. Settings are stored "
        "in ~/.clow/settings.json and .clow/settings.json."
    )
    requires_confirmation = False
    _is_read_only = False  # Input-dependent
    _is_concurrency_safe = False
    _is_destructive = False
    _search_hint = "config settings configuration read write"
    _aliases = ["settings", "configure"]

    def is_read_only(self, **kwargs) -> bool:
        """Read-only when action is 'get' or 'list'."""
        action = kwargs.get("action", "list")
        return action in ("get", "list")

    def is_destructive(self, **kwargs) -> bool:
        """Destructive when writing config."""
        action = kwargs.get("action", "list")
        return action == "set"

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["get", "set", "list", "delete"],
                    "description": "Action: get (read key), set (write key), list (all settings), delete (remove key). Default: list.",
                },
                "key": {
                    "type": "string",
                    "description": "Configuration key (dot notation supported, e.g. 'mcp_servers.name').",
                },
                "value": {
                    "type": ["string", "number", "boolean", "object", "array"],
                    "description": "Value to set (for 'set' action). JSON strings are parsed automatically.",
                },
                "scope": {
                    "type": "string",
                    "enum": ["global", "project"],
                    "description": "Scope: global (~/.clow/settings.json) or project (.clow/settings.json). Default: global.",
                },
            },
        }

    def execute(self, **kwargs: Any) -> str:
        action = kwargs.get("action", "list")
        key = kwargs.get("key", "")
        value = kwargs.get("value")
        scope = kwargs.get("scope", "global")

        try:
            from .. import config

            if action == "list":
                settings = config.load_settings()
                if not settings:
                    return "No settings configured."
                return f"Settings:\n{json.dumps(settings, indent=2, ensure_ascii=False)}"

            elif action == "get":
                if not key:
                    return "[ERROR] key is required for 'get' action."
                settings = config.load_settings()
                # Support dot notation
                parts = key.split(".")
                current = settings
                for part in parts:
                    if isinstance(current, dict) and part in current:
                        current = current[part]
                    else:
                        return f"Key '{key}' not found."
                if isinstance(current, (dict, list)):
                    return f"{key} = {json.dumps(current, indent=2, ensure_ascii=False)}"
                return f"{key} = {current}"

            elif action == "set":
                if not key:
                    return "[ERROR] key is required for 'set' action."
                if value is None:
                    return "[ERROR] value is required for 'set' action."

                # Parse JSON string values
                if isinstance(value, str):
                    try:
                        value = json.loads(value)
                    except (json.JSONDecodeError, TypeError):
                        pass  # Keep as string

                if scope == "project":
                    from pathlib import Path
                    project_file = Path.cwd() / ".clow" / "settings.json"
                    settings = {}
                    if project_file.exists():
                        try:
                            settings = json.loads(project_file.read_text(encoding="utf-8"))
                        except (json.JSONDecodeError, OSError):
                            settings = {}
                    self._set_nested(settings, key, value)
                    config.save_project_settings(settings)
                else:
                    settings = config.load_settings()
                    self._set_nested(settings, key, value)
                    config.save_settings(settings)

                return f"Set {key} = {json.dumps(value, ensure_ascii=False)} (scope: {scope})"

            elif action == "delete":
                if not key:
                    return "[ERROR] key is required for 'delete' action."

                if scope == "project":
                    from pathlib import Path
                    project_file = Path.cwd() / ".clow" / "settings.json"
                    if not project_file.exists():
                        return f"[ERROR] No project settings file."
                    settings = json.loads(project_file.read_text(encoding="utf-8"))
                    if self._delete_nested(settings, key):
                        config.save_project_settings(settings)
                        return f"Deleted key '{key}' from project settings."
                    return f"Key '{key}' not found in project settings."
                else:
                    settings = config.load_settings()
                    if self._delete_nested(settings, key):
                        config.save_settings(settings)
                        return f"Deleted key '{key}' from global settings."
                    return f"Key '{key}' not found in global settings."

            return f"[ERROR] Unknown action: {action}"

        except Exception as e:
            return f"[ERROR] Config operation failed: {e}"

    @staticmethod
    def _set_nested(d: dict, key: str, value: Any) -> None:
        """Set a value using dot notation key."""
        parts = key.split(".")
        current = d
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value

    @staticmethod
    def _delete_nested(d: dict, key: str) -> bool:
        """Delete a key using dot notation. Returns True if found."""
        parts = key.split(".")
        current = d
        for part in parts[:-1]:
            if not isinstance(current, dict) or part not in current:
                return False
            current = current[part]
        if isinstance(current, dict) and parts[-1] in current:
            del current[parts[-1]]
            return True
        return False
