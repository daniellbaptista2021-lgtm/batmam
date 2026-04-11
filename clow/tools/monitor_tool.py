"""Monitor Tool - monitor background processes and get output."""

from __future__ import annotations
from typing import Any
from .base import BaseTool


class MonitorTool(BaseTool):
    """Monitor a background process, check if still running, get output."""

    name = "monitor"
    description = (
        "Monitor a background process or job. Check if it is still running "
        "and retrieve its output. Use after launching background tasks."
    )
    requires_confirmation = False
    _is_read_only = True
    _is_concurrency_safe = True
    _is_destructive = False
    _search_hint = "monitor process background job status"
    _aliases = ["check_job", "job_status"]

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "ID of the background job to monitor.",
                },
                "list_all": {
                    "type": "boolean",
                    "description": "List all background jobs. Default: false.",
                },
            },
        }

    def execute(self, **kwargs: Any) -> str:
        job_id = kwargs.get("job_id", "")
        list_all = kwargs.get("list_all", False)

        try:
            from ..sandbox import Sandbox
            sandbox = Sandbox()
        except Exception as e:
            return f"[ERROR] Cannot access sandbox: {e}"

        if list_all:
            jobs = sandbox.list_background_jobs()
            if not jobs:
                return "No background jobs found."
            lines = [f"Background jobs ({len(jobs)}):"]
            for jid, result in jobs.items():
                status = "running" if result is None else "completed"
                if result and result.timed_out:
                    status = "timed_out"
                elif result and result.return_code != 0:
                    status = f"failed (exit {result.return_code})"
                lines.append(f"  - {jid}: {status}")
            return "\n".join(lines)

        if not job_id:
            return "[ERROR] Provide job_id or set list_all=true."

        result = sandbox.get_background_result(job_id)
        if result is None:
            return f"Job {job_id}: still running (no result yet)."

        parts = [f"Job {job_id}: completed"]
        if result.return_code is not None:
            parts.append(f"Exit code: {result.return_code}")
        if result.timed_out:
            parts.append("Status: TIMED OUT")
        if result.stdout:
            stdout = result.stdout[:2000]
            if len(result.stdout) > 2000:
                stdout += "\n... (truncated)"
            parts.append(f"Output:\n{stdout}")
        if result.stderr:
            stderr = result.stderr[:1000]
            parts.append(f"Stderr:\n{stderr}")
        if result.truncated:
            parts.append("(output was truncated)")

        return "\n".join(parts)
