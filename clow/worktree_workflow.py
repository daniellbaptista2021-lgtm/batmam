"""Worktree Workflow — desenvolvimento paralelo com branches isoladas.

Inspirado no padrao worktree-init/deliver/check/cleanup do claude-code-templates.
Cada tarefa roda em um worktree Git separado com branch dedicada.

Usage:
    from clow.worktree_workflow import WorktreeWorkflow

    wf = WorktreeWorkflow("/path/to/repo")
    tasks = wf.init(["criar landing page", "fix bug login"])
    # ... work in each worktree ...
    wf.deliver(tasks[0].path, "feat: landing page inicial")
    wf.cleanup()
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class WorktreeTask:
    """Informacoes sobre um worktree de tarefa."""

    path: str
    branch: str
    base_branch: str
    task: str
    created_at: float = field(default_factory=time.time)


class WorktreeWorkflow:
    """Gerencia workflow completo de worktrees para desenvolvimento paralelo."""

    def __init__(self, repo_dir: str) -> None:
        self.repo_dir = str(Path(repo_dir).resolve())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def init(self, tasks: list[str], base_branch: str = "") -> list[WorktreeTask]:
        """Cria worktrees paralelos para multiplas tarefas.

        Args:
            tasks: Lista de descricoes de tarefas (ex: ["criar landing page", "fix bug login"])
            base_branch: Branch base (default: branch atual)

        Returns:
            Lista de WorktreeTask com path, branch e task description.
        """
        if not base_branch:
            base_branch = self._current_branch()

        created: list[WorktreeTask] = []
        for task_desc in tasks:
            slug = self._slugify(task_desc)
            branch = f"clow/{slug}"
            wt_path = str(Path(self.repo_dir).parent / f".clow-wt-{slug}")

            self._run_git(["worktree", "add", "-b", branch, wt_path, base_branch])

            # Write task metadata inside the worktree
            meta_path = Path(wt_path) / ".worktree-task.md"
            meta_path.write_text(
                f"# Worktree Task\n\n"
                f"- **task**: {task_desc}\n"
                f"- **branch**: {branch}\n"
                f"- **base**: {base_branch}\n"
                f"- **created**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n",
                encoding="utf-8",
            )

            created.append(
                WorktreeTask(
                    path=wt_path,
                    branch=branch,
                    base_branch=base_branch,
                    task=task_desc,
                )
            )

        return created

    def deliver(self, worktree_path: str, commit_msg: str = "") -> dict:
        """Faz commit, push e prepara PR de um worktree.

        Steps:
            1. git add -A
            2. git commit (conventional commit message)
            3. git push -u origin <branch>

        Returns:
            dict com branch, push_status, has_changes
        """
        wt = str(Path(worktree_path).resolve())
        branch = self._branch_at(wt)

        # Stage everything
        self._run_git_in(wt, ["add", "-A"])

        # Check if there is anything to commit
        status = self._run_git_in(wt, ["status", "--porcelain"]).strip()
        if not status:
            return {"branch": branch, "push_status": "nothing_to_commit", "has_changes": False}

        # Build commit message from task metadata if not provided
        if not commit_msg:
            meta = Path(wt) / ".worktree-task.md"
            task_desc = ""
            if meta.exists():
                for line in meta.read_text(encoding="utf-8").splitlines():
                    if line.startswith("- **task**:"):
                        task_desc = line.split(":", 1)[1].strip()
                        break
            commit_msg = f"feat: {task_desc}" if task_desc else "feat: worktree changes"

        self._run_git_in(wt, ["commit", "-m", commit_msg])

        # Push
        push_status = "pushed"
        try:
            self._run_git_in(wt, ["push", "-u", "origin", branch])
        except RuntimeError:
            push_status = "push_failed"

        return {"branch": branch, "push_status": push_status, "has_changes": True}

    def check(self, worktree_path: str = "") -> dict | list[dict]:
        """Verifica status de um worktree ou todos.

        Args:
            worktree_path: Caminho de um worktree especifico.
                           Se vazio, retorna status de todos.

        Returns:
            dict (single) ou list[dict] (all) com branch, task, modified, staged, status.
        """
        if worktree_path:
            return self._check_single(str(Path(worktree_path).resolve()))

        results: list[dict] = []
        for info in self._list_worktrees():
            if info["path"] == self.repo_dir:
                continue
            try:
                results.append(self._check_single(info["path"]))
            except RuntimeError:
                results.append({"path": info["path"], "branch": info.get("branch", "?"), "status": "error"})
        return results

    def cleanup(self, pattern: str = "clow/*", dry_run: bool = False) -> list[dict]:
        """Limpa worktrees cujas branches ja foram mergeadas.

        Args:
            pattern: Glob pattern para filtrar branches (default: clow/*)
            dry_run: Se True, apenas lista sem remover.

        Returns:
            Lista de dicts com branch, path, action (removed | skipped | dry_run).
        """
        base = self._current_branch()
        merged_branches = set(self._merged_branches(base))
        results: list[dict] = []

        for info in self._list_worktrees():
            branch = info.get("branch", "")
            if info["path"] == self.repo_dir:
                continue
            if not self._matches_pattern(branch, pattern):
                continue

            entry: dict = {"branch": branch, "path": info["path"]}

            if branch not in merged_branches:
                entry["action"] = "skipped"
                results.append(entry)
                continue

            if dry_run:
                entry["action"] = "dry_run"
                results.append(entry)
                continue

            # Remove worktree then branch
            try:
                self._run_git(["worktree", "remove", info["path"], "--force"])
            except RuntimeError:
                import shutil
                shutil.rmtree(info["path"], ignore_errors=True)
                try:
                    self._run_git(["worktree", "prune"])
                except RuntimeError:
                    pass

            try:
                self._run_git(["branch", "-D", branch])
            except RuntimeError:
                pass

            entry["action"] = "removed"
            results.append(entry)

        return results

    def list_active(self) -> list[dict]:
        """Lista todos os worktrees ativos com status resumido."""
        results: list[dict] = []
        for info in self._list_worktrees():
            entry: dict = {"path": info["path"], "branch": info.get("branch", "")}

            # Read task metadata if present
            meta = Path(info["path"]) / ".worktree-task.md"
            if meta.exists():
                for line in meta.read_text(encoding="utf-8").splitlines():
                    if line.startswith("- **task**:"):
                        entry["task"] = line.split(":", 1)[1].strip()
                        break

            # Quick dirty check
            try:
                porcelain = self._run_git_in(info["path"], ["status", "--porcelain"]).strip()
                entry["has_changes"] = bool(porcelain)
                entry["changed_files"] = len(porcelain.splitlines()) if porcelain else 0
            except RuntimeError:
                entry["has_changes"] = False
                entry["changed_files"] = 0

            results.append(entry)
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_single(self, wt_path: str) -> dict:
        """Return detailed status for a single worktree path."""
        branch = self._branch_at(wt_path)
        porcelain = self._run_git_in(wt_path, ["status", "--porcelain"]).strip()
        lines = porcelain.splitlines() if porcelain else []

        modified = [l[3:] for l in lines if l and l[0] in (" ", "M", "A", "D", "?")]
        staged = [l[3:] for l in lines if l and l[0] in ("M", "A", "D", "R")]

        task = ""
        meta = Path(wt_path) / ".worktree-task.md"
        if meta.exists():
            for line in meta.read_text(encoding="utf-8").splitlines():
                if line.startswith("- **task**:"):
                    task = line.split(":", 1)[1].strip()
                    break

        return {
            "path": wt_path,
            "branch": branch,
            "task": task,
            "modified": modified,
            "staged": staged,
            "status": "dirty" if lines else "clean",
        }

    def _current_branch(self) -> str:
        return self._run_git(["rev-parse", "--abbrev-ref", "HEAD"]).strip()

    def _branch_at(self, wt_path: str) -> str:
        return self._run_git_in(wt_path, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()

    def _merged_branches(self, base: str) -> list[str]:
        """Return list of branch names merged into *base*."""
        raw = self._run_git(["branch", "--merged", base]).strip()
        branches: list[str] = []
        for line in raw.splitlines():
            name = line.strip().lstrip("* ")
            if name and name != base:
                branches.append(name)
        return branches

    def _list_worktrees(self) -> list[dict]:
        """Parse ``git worktree list --porcelain`` output."""
        raw = self._run_git(["worktree", "list", "--porcelain"]).strip()
        entries: list[dict] = []
        current: dict = {}
        for line in raw.splitlines():
            if not line.strip():
                if current:
                    entries.append(current)
                    current = {}
                continue
            if line.startswith("worktree "):
                current["path"] = line[len("worktree "):].strip()
            elif line.startswith("branch "):
                ref = line[len("branch "):].strip()
                # refs/heads/clow/foo -> clow/foo
                current["branch"] = ref.replace("refs/heads/", "")
            elif line.strip() == "bare":
                current["bare"] = True
        if current:
            entries.append(current)
        return entries

    @staticmethod
    def _matches_pattern(branch: str, pattern: str) -> bool:
        """Simple glob-style match (only supports trailing *)."""
        if pattern.endswith("*"):
            return branch.startswith(pattern[:-1])
        return branch == pattern

    @staticmethod
    def _slugify(text: str) -> str:
        """Convert task description to kebab-case slug."""
        text = text.lower().strip()
        text = re.sub(r"[^a-z0-9\s-]", "", text)
        text = re.sub(r"[\s_]+", "-", text)
        text = re.sub(r"-+", "-", text).strip("-")
        # Truncate to reasonable length
        return text[:50] if text else "task"

    def _run_git(self, args: list[str]) -> str:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            cwd=self.repo_dir,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} falhou: {result.stderr}")
        return result.stdout

    def _run_git_in(self, cwd: str, args: list[str]) -> str:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            cwd=cwd,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} falhou em {cwd}: {result.stderr}")
        return result.stdout
