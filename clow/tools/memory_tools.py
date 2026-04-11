"""Memory Tools - read and write persistent memories across sessions."""

from __future__ import annotations
import json
from typing import Any
from .base import BaseTool


class MemoryReadTool(BaseTool):
    """Read stored memories from previous sessions."""

    name = "memory_read"
    description = (
        "Read persistent memories stored across sessions. Returns all "
        "memories or filters by type. Memories persist between conversations."
    )
    requires_confirmation = False
    _is_read_only = True
    _is_concurrency_safe = True
    _is_destructive = False
    _search_hint = "memory read recall remember context"
    _aliases = ["recall", "get_memory"]

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of a specific memory to read. If omitted, lists all memories.",
                },
            },
        }

    def execute(self, **kwargs: Any) -> str:
        name = kwargs.get("name", "")

        try:
            from ..memory import list_memories, load_memory_context

            if name:
                # Load specific memory
                memories = list_memories()
                for m in memories:
                    if m.get("name") == name:
                        return (
                            f"Memory: {m['name']}\n"
                            f"  Type: {m.get('type', 'general')}\n"
                            f"  Content: {m.get('content', '(empty)')}\n"
                            f"  Updated: {m.get('updated_at', 'unknown')}"
                        )
                return f"Memory '{name}' not found."

            # List all memories
            memories = list_memories()
            if not memories:
                return "No memories stored."

            lines = [f"Memories ({len(memories)}):"]
            for m in memories:
                mem_type = m.get("type", "general")
                content_preview = m.get("content", "")[:80]
                lines.append(f"  - {m['name']} [{mem_type}]: {content_preview}")

            return "\n".join(lines)

        except Exception as e:
            return f"[ERROR] Failed to read memories: {e}"


class MemoryWriteTool(BaseTool):
    """Write/save a memory for persistence across sessions."""

    name = "memory_write"
    description = (
        "Save a memory that persists across sessions. Use to remember "
        "important context, user preferences, project details, or "
        "technical decisions."
    )
    requires_confirmation = False
    _is_read_only = False
    _is_concurrency_safe = False
    _is_destructive = False
    _search_hint = "memory write save remember store persist"
    _aliases = ["remember", "save_memory"]

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name/key for the memory (unique identifier).",
                },
                "content": {
                    "type": "string",
                    "description": "Content to remember.",
                },
                "memory_type": {
                    "type": "string",
                    "enum": ["general", "preference", "project", "technical", "user"],
                    "description": "Type of memory. Default: general.",
                },
            },
            "required": ["name", "content"],
        }

    def execute(self, **kwargs: Any) -> str:
        name = kwargs.get("name", "")
        content = kwargs.get("content", "")
        memory_type = kwargs.get("memory_type", "general")

        if not name or not content:
            return "[ERROR] name and content are required."

        try:
            from ..memory import save_memory
            save_memory(name=name, content=content, memory_type=memory_type)
            return f"Memory saved: '{name}' ({memory_type}, {len(content)} chars)"
        except Exception as e:
            return f"[ERROR] Failed to save memory: {e}"


class MemoryDeleteTool(BaseTool):
    """Delete a stored memory."""

    name = "memory_delete"
    description = "Delete a stored memory by name."
    requires_confirmation = True
    _is_read_only = False
    _is_concurrency_safe = False
    _is_destructive = True
    _search_hint = "memory delete forget remove"
    _aliases = ["forget", "delete_memory"]

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the memory to delete.",
                },
            },
            "required": ["name"],
        }

    def execute(self, **kwargs: Any) -> str:
        name = kwargs.get("name", "")

        if not name:
            return "[ERROR] name is required."

        try:
            from ..memory import delete_memory
            success = delete_memory(name)
            if success:
                return f"Memory '{name}' deleted."
            return f"[ERROR] Memory '{name}' not found."
        except Exception as e:
            return f"[ERROR] Failed to delete memory: {e}"
