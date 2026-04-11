"""Cron Tools - create, delete, and list cron jobs."""

from __future__ import annotations
from typing import Any
from .base import BaseTool


class CronCreateTool(BaseTool):
    """Create a cron job that runs a prompt on a schedule."""

    name = "cron_create"
    description = (
        "Create a cron job that executes a prompt at regular intervals. "
        "Supports intervals like 5m, 1h, 30s. The job runs in a background thread."
    )
    requires_confirmation = False
    _is_read_only = False
    _is_concurrency_safe = False
    _is_destructive = False
    _search_hint = "cron schedule interval recurring job"
    _aliases = ["schedule_job", "create_cron"]

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The prompt/command to execute on each interval.",
                },
                "interval": {
                    "type": "string",
                    "description": "Interval string: e.g. 5m, 1h, 30s.",
                },
            },
            "required": ["prompt", "interval"],
        }

    def execute(self, **kwargs: Any) -> str:
        prompt = kwargs.get("prompt", "")
        interval = kwargs.get("interval", "")

        if not prompt or not interval:
            return "[ERROR] prompt and interval are required."

        try:
            from ..cron import get_cron_manager
            manager = get_cron_manager()
            job = manager.create(prompt=prompt, interval_str=interval)
            formatted = manager.format_interval(job.interval_seconds)
            return (
                f"Cron job created.\n"
                f"  ID: {job.id}\n"
                f"  Prompt: {prompt[:100]}\n"
                f"  Interval: {formatted} ({job.interval_seconds}s)\n"
                f"  Status: active"
            )
        except ValueError as e:
            return f"[ERROR] Invalid interval: {e}"
        except Exception as e:
            return f"[ERROR] Failed to create cron job: {e}"


class CronDeleteTool(BaseTool):
    """Delete a cron job."""

    name = "cron_delete"
    description = "Delete a cron job by its ID. This stops and removes the job."
    requires_confirmation = True
    _is_read_only = False
    _is_concurrency_safe = False
    _is_destructive = True
    _search_hint = "cron delete remove stop job"
    _aliases = ["delete_cron", "remove_cron"]

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "ID of the cron job to delete.",
                },
            },
            "required": ["job_id"],
        }

    def execute(self, **kwargs: Any) -> str:
        job_id = kwargs.get("job_id", "")

        if not job_id:
            return "[ERROR] job_id is required."

        try:
            from ..cron import get_cron_manager
            manager = get_cron_manager()
            success = manager.delete(job_id)
            if success:
                return f"Cron job '{job_id}' deleted."
            return f"[ERROR] Cron job '{job_id}' not found."
        except Exception as e:
            return f"[ERROR] Failed to delete cron job: {e}"


class CronListTool(BaseTool):
    """List all cron jobs."""

    name = "cron_list"
    description = "List all active and inactive cron jobs with their status."
    requires_confirmation = False
    _is_read_only = True
    _is_concurrency_safe = True
    _is_destructive = False
    _search_hint = "cron list jobs schedule"
    _aliases = ["list_crons"]

    def get_schema(self) -> dict:
        return {"type": "object", "properties": {}}

    def execute(self, **kwargs: Any) -> str:
        try:
            from ..cron import get_cron_manager
            manager = get_cron_manager()
            jobs = manager.list_all()

            if not jobs:
                return "No cron jobs found."

            lines = [f"Cron jobs ({len(jobs)}):"]
            for job in jobs:
                status = "active" if job.active else "paused"
                formatted = manager.format_interval(job.interval_seconds)
                import time
                last_run = time.strftime("%H:%M:%S", time.localtime(job.last_run)) if job.last_run else "never"
                lines.append(
                    f"  - [{job.id}] {status} | every {formatted} | "
                    f"runs: {job.run_count} | last: {last_run}\n"
                    f"    prompt: {job.prompt[:80]}"
                )

            return "\n".join(lines)
        except Exception as e:
            return f"[ERROR] Failed to list cron jobs: {e}"
