"""Workflow Tool - execute workflow scripts from .clow/workflows/."""

from __future__ import annotations
import json
import subprocess
from pathlib import Path
from typing import Any
from .base import BaseTool


class WorkflowTool(BaseTool):
    """Execute a workflow script from .clow/workflows/."""

    name = "workflow"
    description = (
        "Execute a workflow script from the .clow/workflows/ directory. "
        "Workflows are shell scripts or Python files that automate "
        "multi-step processes."
    )
    requires_confirmation = True
    _is_read_only = False
    _is_concurrency_safe = False
    _is_destructive = False
    _search_hint = "workflow automate script pipeline"
    _aliases = ["run_workflow"]

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the workflow to execute (without extension).",
                },
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Arguments to pass to the workflow script.",
                },
                "env": {
                    "type": "object",
                    "description": "Additional environment variables for the workflow.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds. Default: 300.",
                },
                "list_workflows": {
                    "type": "boolean",
                    "description": "If true, list available workflows instead of running one.",
                },
            },
        }

    def execute(self, **kwargs: Any) -> str:
        name = kwargs.get("name", "")
        args = kwargs.get("args", [])
        env_extra = kwargs.get("env", {})
        timeout = kwargs.get("timeout", 300)
        list_workflows = kwargs.get("list_workflows", False)

        # Search paths for workflows
        search_paths = [
            Path.cwd() / ".clow" / "workflows",
        ]
        try:
            from .. import config
            search_paths.append(config.CLOW_HOME / "workflows")
        except Exception:
            pass

        if list_workflows:
            workflows = []
            for wf_dir in search_paths:
                if wf_dir.exists():
                    for f in sorted(wf_dir.iterdir()):
                        if f.is_file() and f.suffix in (".sh", ".py", ".bash"):
                            workflows.append(f"{f.stem} ({f.suffix}) - {wf_dir}")
            if not workflows:
                return "No workflows found. Create scripts in .clow/workflows/."
            lines = [f"Available workflows ({len(workflows)}):"]
            for w in workflows:
                lines.append(f"  - {w}")
            return "\n".join(lines)

        if not name:
            return "[ERROR] name is required (or set list_workflows=true)."

        # Find the workflow file
        workflow_file = None
        for wf_dir in search_paths:
            for ext in (".sh", ".py", ".bash"):
                candidate = wf_dir / f"{name}{ext}"
                if candidate.exists() and candidate.is_file():
                    workflow_file = candidate
                    break
            if workflow_file:
                break

        if not workflow_file:
            return f"[ERROR] Workflow '{name}' not found in .clow/workflows/."

        # Determine executor
        ext = workflow_file.suffix
        if ext == ".py":
            cmd = ["python3", str(workflow_file)] + list(args)
        elif ext in (".sh", ".bash"):
            cmd = ["bash", str(workflow_file)] + list(args)
        else:
            cmd = [str(workflow_file)] + list(args)

        # Build environment
        import os
        env = dict(os.environ)
        env.update(env_extra)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(Path.cwd()),
                env=env,
            )

            parts = [f"Workflow '{name}' completed (exit code: {result.returncode})"]
            if result.stdout:
                stdout = result.stdout[:5000]
                if len(result.stdout) > 5000:
                    stdout += "\n... (truncated)"
                parts.append(f"Output:\n{stdout}")
            if result.stderr:
                stderr = result.stderr[:2000]
                parts.append(f"Stderr:\n{stderr}")

            return "\n".join(parts)

        except subprocess.TimeoutExpired:
            return f"[ERROR] Workflow '{name}' timed out after {timeout}s."
        except PermissionError:
            return f"[ERROR] Permission denied. Try: chmod +x {workflow_file}"
        except Exception as e:
            return f"[ERROR] Workflow execution failed: {e}"
