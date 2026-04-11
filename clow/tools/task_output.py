"""Task Output Tool - return structured output from a task/agent execution."""

from __future__ import annotations
import json
from typing import Any
from .base import BaseTool


class TaskOutputTool(BaseTool):
    """Return structured output from a task or agent execution."""

    name = "task_output"
    description = (
        "Return structured output from a task or agent execution. "
        "Use to collect and format the results of completed tasks. "
        "Supports JSON and plain text output formats."
    )
    requires_confirmation = False
    _is_read_only = True
    _is_concurrency_safe = True
    _is_destructive = False
    _search_hint = "task output result return structured"
    _aliases = ["get_output", "task_result"]

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "ID of the task to get output from.",
                },
                "format": {
                    "type": "string",
                    "enum": ["text", "json"],
                    "description": "Output format. Default: text.",
                },
            },
            "required": ["task_id"],
        }

    def execute(self, **kwargs: Any) -> str:
        task_id = kwargs.get("task_id", "")
        output_format = kwargs.get("format", "text")

        if not task_id:
            return "[ERROR] task_id is required."

        try:
            from ..tasks import get_task_manager
            manager = get_task_manager()
            task = manager.get(task_id)

            if not task:
                return f"[ERROR] Task '{task_id}' not found."

            if output_format == "json":
                import time as _time
                output_data = {
                    "task_id": task.id,
                    "title": task.title,
                    "status": task.status.value,
                    "description": task.description,
                    "output": task.output,
                    "created_at": task.created_at,
                    "updated_at": task.updated_at,
                    "dependencies": task.dependencies,
                }
                return json.dumps(output_data, indent=2, ensure_ascii=False)
            else:
                lines = [
                    f"Task: {task.title}",
                    f"  ID: {task.id}",
                    f"  Status: {task.status.value}",
                ]
                if task.output:
                    lines.append(f"  Output: {task.output}")
                else:
                    lines.append("  Output: (no output yet)")
                if task.dependencies:
                    lines.append(f"  Dependencies: {', '.join(task.dependencies)}")
                return "\n".join(lines)

        except Exception as e:
            return f"[ERROR] Failed to get task output: {e}"
