"""Git Worktree tools - create and cleanup git worktrees for isolated work."""

from __future__ import annotations
import subprocess
import uuid
from pathlib import Path
from typing import Any
from .base import BaseTool


class EnterWorktreeTool(BaseTool):
    """Creates a git worktree for isolated work."""

    name = "enter_worktree"
    description = (
        "Create a git worktree for isolated work. Creates a new branch "
        "and working directory. Use for parallel development without "
        "affecting the main working tree."
    )
    requires_confirmation = False
    _is_read_only = False
    _is_concurrency_safe = False
    _is_destructive = False
    _search_hint = "worktree git isolate branch parallel"
    _aliases = ["create_worktree"]

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "branch_name": {
                    "type": "string",
                    "description": "Name for the new branch. Auto-generated if not provided.",
                },
                "base_branch": {
                    "type": "string",
                    "description": "Branch to base the worktree on. Default: current branch.",
                },
                "path": {
                    "type": "string",
                    "description": "Path for the worktree directory. Auto-generated if not provided.",
                },
                "cwd": {
                    "type": "string",
                    "description": "Repository directory. Default: current working directory.",
                },
            },
        }

    def execute(self, **kwargs: Any) -> str:
        cwd = kwargs.get("cwd", "") or "."
        branch_name = kwargs.get("branch_name", "")
        base_branch = kwargs.get("base_branch", "")
        wt_path = kwargs.get("path", "")

        # Verify git repo
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                capture_output=True, text=True, cwd=cwd,
            )
            if result.returncode != 0:
                return "[ERROR] Not inside a git repository."
        except FileNotFoundError:
            return "[ERROR] git is not installed."

        # Generate names if not provided
        wt_id = uuid.uuid4().hex[:8]
        if not branch_name:
            branch_name = f"clow-worktree-{wt_id}"
        if not wt_path:
            repo_root = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, cwd=cwd,
            ).stdout.strip()
            wt_path = str(Path(repo_root).parent / f".clow-wt-{wt_id}")

        # Build git worktree add command
        cmd = ["git", "worktree", "add"]
        if base_branch:
            cmd.extend(["-b", branch_name, wt_path, base_branch])
        else:
            cmd.extend(["-b", branch_name, wt_path])

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, cwd=cwd, timeout=30,
            )
            if result.returncode != 0:
                return f"[ERROR] git worktree add failed: {result.stderr.strip()}"

            base_info = base_branch if base_branch else "(current branch)"
            return (
                f"Worktree created successfully.\n"
                f"  Branch: {branch_name}\n"
                f"  Path: {wt_path}\n"
                f"  Base: {base_info}\n"
                f"Use this path as cwd for isolated work."
            )
        except subprocess.TimeoutExpired:
            return "[ERROR] git worktree add timed out."
        except Exception as e:
            return f"[ERROR] {e}"


class ExitWorktreeTool(BaseTool):
    """Cleans up a git worktree."""

    name = "exit_worktree"
    description = (
        "Remove a git worktree and optionally delete its branch. "
        "Use after finishing isolated work to clean up."
    )
    requires_confirmation = True
    _is_read_only = False
    _is_concurrency_safe = False
    _is_destructive = True
    _search_hint = "worktree git remove cleanup"
    _aliases = ["remove_worktree"]

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the worktree to remove.",
                },
                "delete_branch": {
                    "type": "boolean",
                    "description": "Also delete the branch. Default: false.",
                },
                "force": {
                    "type": "boolean",
                    "description": "Force removal even with uncommitted changes. Default: false.",
                },
                "cwd": {
                    "type": "string",
                    "description": "Main repository directory.",
                },
            },
            "required": ["path"],
        }

    def execute(self, **kwargs: Any) -> str:
        path = kwargs.get("path", "")
        delete_branch = kwargs.get("delete_branch", False)
        force = kwargs.get("force", False)
        cwd = kwargs.get("cwd", "") or "."

        if not path:
            return "[ERROR] path is required."

        # Get branch name before removing
        branch_name = ""
        if delete_branch:
            try:
                result = subprocess.run(
                    ["git", "worktree", "list", "--porcelain"],
                    capture_output=True, text=True, cwd=cwd,
                )
                for block in result.stdout.split("\n\n"):
                    if f"worktree {path}" in block:
                        for line in block.split("\n"):
                            if line.startswith("branch "):
                                branch_name = line.split("refs/heads/", 1)[-1]
                                break
            except Exception:
                pass

        # Remove worktree
        cmd = ["git", "worktree", "remove", path]
        if force:
            cmd.append("--force")

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, cwd=cwd, timeout=30,
            )
            if result.returncode != 0:
                return f"[ERROR] git worktree remove failed: {result.stderr.strip()}"

            msg = f"Worktree removed: {path}"

            if delete_branch and branch_name:
                br_result = subprocess.run(
                    ["git", "branch", "-D", branch_name],
                    capture_output=True, text=True, cwd=cwd, timeout=10,
                )
                if br_result.returncode == 0:
                    msg += f"\nBranch deleted: {branch_name}"
                else:
                    msg += f"\nFailed to delete branch: {br_result.stderr.strip()}"

            # Prune stale worktrees
            subprocess.run(
                ["git", "worktree", "prune"],
                capture_output=True, text=True, cwd=cwd, timeout=10,
            )

            return msg
        except subprocess.TimeoutExpired:
            return "[ERROR] git worktree remove timed out."
        except Exception as e:
            return f"[ERROR] {e}"
