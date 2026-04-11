"""Sleep Tool - wait for a specified duration."""

from __future__ import annotations
import time
from typing import Any
from .base import BaseTool


class SleepTool(BaseTool):
    """Wait for a specified duration (max 300 seconds)."""

    name = "sleep"
    description = (
        "Wait for a specified duration in seconds. Maximum 300 seconds. "
        "Use for polling background tasks or waiting for external processes."
    )
    requires_confirmation = False
    _is_read_only = True
    _is_concurrency_safe = True
    _is_destructive = False
    _search_hint = "sleep wait pause delay poll"
    _aliases = ["wait", "delay"]

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "seconds": {
                    "type": "number",
                    "description": "Duration to sleep in seconds. Max: 300.",
                },
                "reason": {
                    "type": "string",
                    "description": "Reason for sleeping (for logging).",
                },
            },
            "required": ["seconds"],
        }

    def execute(self, **kwargs: Any) -> str:
        seconds = kwargs.get("seconds", 0)
        reason = kwargs.get("reason", "")

        if not seconds or seconds <= 0:
            return "[ERROR] seconds must be a positive number."

        # Cap at 300 seconds
        seconds = min(float(seconds), 300.0)

        start = time.time()
        time.sleep(seconds)
        elapsed = time.time() - start

        msg = f"Slept for {elapsed:.1f} seconds."
        if reason:
            msg += f" Reason: {reason}"
        return msg
