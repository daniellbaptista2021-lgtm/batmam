"""Snip Tool - remove old messages from conversation to free context."""

from __future__ import annotations
from typing import Any
from .base import BaseTool


class SnipTool(BaseTool):
    """Snip/remove old messages from conversation history to free context."""

    name = "snip"
    description = (
        "Snip (remove) old messages from conversation history to free up "
        "context window space. Applies micro-compaction to trim old tool "
        "results and optionally removes the oldest messages entirely."
    )
    requires_confirmation = False
    _is_read_only = False
    _is_concurrency_safe = False
    _is_destructive = False
    _search_hint = "snip trim compact context memory"
    _aliases = ["compact", "trim_context"]

    # Reference to conversation messages (set by agent)
    _messages = None

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "message_count": {
                    "type": "integer",
                    "description": "Number of oldest messages to remove. Default: auto (micro-compact only).",
                },
                "mode": {
                    "type": "string",
                    "enum": ["micro", "session", "full"],
                    "description": "Compaction mode. micro=trim tool results, session=pre-built summary, full=LLM summary. Default: micro.",
                },
            },
        }

    def execute(self, **kwargs: Any) -> str:
        message_count = kwargs.get("message_count", 0)
        mode = kwargs.get("mode", "micro")

        try:
            from ..compaction import microcompact, session_memory_compact
        except ImportError:
            return "[ERROR] Compaction module not available."

        if self._messages is None:
            return "[ERROR] No conversation messages available. Snip must be bound to a session."

        original_count = len(self._messages)

        if mode == "micro":
            # Apply micro-compaction (trim old tool results)
            compacted = microcompact(self._messages)
            self._messages.clear()
            self._messages.extend(compacted)

            removed = original_count - len(self._messages)
            return (
                f"Micro-compaction applied.\n"
                f"  Messages before: {original_count}\n"
                f"  Messages after: {len(self._messages)}\n"
                f"  Trimmed: {removed} message(s)\n"
                f"  Old tool results have been truncated."
            )

        elif mode == "session":
            # Session memory compact
            try:
                compacted = session_memory_compact(self._messages)
                self._messages.clear()
                self._messages.extend(compacted)
                return (
                    f"Session compaction applied.\n"
                    f"  Messages before: {original_count}\n"
                    f"  Messages after: {len(self._messages)}"
                )
            except Exception as e:
                return f"[ERROR] Session compaction failed: {e}"

        elif mode == "full":
            # Full LLM-powered compaction
            try:
                from ..compaction import full_compact
                compacted = full_compact(self._messages)
                self._messages.clear()
                self._messages.extend(compacted)
                return (
                    f"Full compaction applied (LLM summary).\n"
                    f"  Messages before: {original_count}\n"
                    f"  Messages after: {len(self._messages)}"
                )
            except Exception as e:
                return f"[ERROR] Full compaction failed: {e}"

        # Manual message removal
        if message_count > 0:
            to_remove = min(message_count, len(self._messages) - 1)
            # Keep system message if present
            start = 1 if self._messages and self._messages[0].get("role") == "system" else 0
            del self._messages[start:start + to_remove]
            return (
                f"Removed {to_remove} oldest messages.\n"
                f"  Messages before: {original_count}\n"
                f"  Messages after: {len(self._messages)}"
            )

        return "[ERROR] Invalid mode. Use 'micro', 'session', or 'full'."
