"""Git Worktree isolation para sub-agentes do Batmam.

Permite rodar agentes em copias isoladas do repositorio
sem interferir no working directory principal.
"""

from __future__ import annotations
import subprocess
import tempfile
import uuid
from pathlib import Path


def is_git_repo(cwd: str) -> bool:
    """Verifica se o diretorio eh um repositorio git."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=cwd, capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def create_worktree(cwd: str) -> tuple[str, str]:
    """Cria um worktree git temporario.

    Retorna (worktree_path, branch_name).
    Raises RuntimeError se nao for um repo git.
    """
    if not is_git_repo(cwd):
        raise RuntimeError(f"Nao eh um repositorio git: {cwd}")

    branch_name = f"batmam-wt-{uuid.uuid4().hex[:8]}"
    worktree_path = str(Path(tempfile.gettempdir()) / f"batmam-worktree-{branch_name}")

    # Cria branch e worktree
    result = subprocess.run(
        ["git", "worktree", "add", "-b", branch_name, worktree_path],
        cwd=cwd, capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Falha ao criar worktree: {result.stderr}")

    return worktree_path, branch_name


def cleanup_worktree(cwd: str, worktree_path: str, branch_name: str, force: bool = False) -> bool:
    """Remove worktree e branch temporaria.

    Se force=False, verifica se houve mudancas antes de limpar.
    Retorna True se limpou, False se manteve (por ter mudancas).
    """
    wt = Path(worktree_path)
    if not wt.exists():
        return True

    # Verifica se houve mudancas no worktree
    if not force:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=worktree_path, capture_output=True, text=True, timeout=10,
        )
        if result.stdout.strip():
            return False  # Tem mudancas, nao limpa

        # Verifica commits novos
        result = subprocess.run(
            ["git", "log", "--oneline", f"HEAD...{branch_name}~1"],
            cwd=worktree_path, capture_output=True, text=True, timeout=10,
        )
        # Se tem commits alem do inicial, nao limpa
        if result.stdout.strip().count("\n") > 0:
            return False

    # Remove worktree
    subprocess.run(
        ["git", "worktree", "remove", "--force", worktree_path],
        cwd=cwd, capture_output=True, text=True, timeout=10,
    )

    # Remove branch
    subprocess.run(
        ["git", "branch", "-D", branch_name],
        cwd=cwd, capture_output=True, text=True, timeout=10,
    )

    return True


def has_changes(worktree_path: str) -> bool:
    """Verifica se o worktree tem mudancas."""
    try:
        result = subprocess.run(
            ["git", "diff", "--stat", "HEAD"],
            cwd=worktree_path, capture_output=True, text=True, timeout=10,
        )
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=worktree_path, capture_output=True, text=True, timeout=10,
        )
        return bool(result.stdout.strip() or status.stdout.strip())
    except Exception:
        return False
