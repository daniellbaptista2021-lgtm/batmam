"""Git Worktree Isolation — executa agentes em cópias isoladas do repo."""

from __future__ import annotations
import subprocess
import uuid
import shutil
from pathlib import Path
from dataclasses import dataclass


@dataclass
class WorktreeInfo:
    """Informações sobre um worktree criado."""
    path: str
    branch: str
    base_branch: str
    has_changes: bool = False


class WorktreeManager:
    """Gerencia git worktrees para isolamento de agentes."""

    def __init__(self, repo_dir: str) -> None:
        self.repo_dir = repo_dir

    def create(self) -> WorktreeInfo:
        """Cria um worktree temporário."""
        wt_id = uuid.uuid4().hex[:8]
        branch_name = f"batmam-worktree-{wt_id}"
        wt_path = Path(self.repo_dir).parent / f".batmam-wt-{wt_id}"

        # Detecta branch atual
        base_branch = self._run_git("rev-parse --abbrev-ref HEAD").strip()

        # Cria worktree com nova branch
        self._run_git(f"worktree add -b {branch_name} {wt_path}")

        return WorktreeInfo(
            path=str(wt_path),
            branch=branch_name,
            base_branch=base_branch,
        )

    def cleanup(self, info: WorktreeInfo) -> WorktreeInfo:
        """Remove worktree. Se houve mudanças, mantém a branch."""
        wt_path = Path(info.path)

        # Verifica se houve mudanças
        try:
            status = subprocess.run(
                "git status --porcelain",
                shell=True, capture_output=True, text=True,
                cwd=info.path,
            )
            has_changes = bool(status.stdout.strip())
            info.has_changes = has_changes

            if has_changes:
                # Commit automático das mudanças
                subprocess.run(
                    'git add -A && git commit -m "batmam: worktree changes"',
                    shell=True, capture_output=True, text=True,
                    cwd=info.path,
                )
        except Exception:
            has_changes = False

        # Remove worktree
        try:
            self._run_git(f"worktree remove {info.path} --force")
        except Exception:
            if wt_path.exists():
                shutil.rmtree(wt_path, ignore_errors=True)
                try:
                    self._run_git("worktree prune")
                except Exception:
                    pass

        # Se não houve mudanças, deleta a branch
        if not has_changes:
            try:
                self._run_git(f"branch -D {info.branch}")
            except Exception:
                pass

        return info

    def _run_git(self, cmd: str) -> str:
        result = subprocess.run(
            f"git {cmd}",
            shell=True, capture_output=True, text=True,
            cwd=self.repo_dir,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git {cmd} falhou: {result.stderr}")
        return result.stdout

    @staticmethod
    def is_git_repo(path: str) -> bool:
        try:
            result = subprocess.run(
                "git rev-parse --is-inside-work-tree",
                shell=True, capture_output=True, text=True,
                cwd=path,
            )
            return result.returncode == 0
        except Exception:
            return False
