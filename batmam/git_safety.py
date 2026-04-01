"""Git Safety Protocol — regras rígidas de segurança Git.

Mesmo nível de proteção do Claude Code:
- Nunca force push sem permissão
- Nunca amend commits publicados
- Nunca skip hooks
- Sempre novo commit em vez de amend após falha
- Validação de estado antes de operações
"""

from __future__ import annotations
import subprocess
import re
from dataclasses import dataclass
from .logging import log_action


@dataclass
class GitStatus:
    """Estado atual do repositório Git."""
    is_repo: bool = False
    branch: str = ""
    has_staged: bool = False
    has_unstaged: bool = False
    has_untracked: bool = False
    ahead: int = 0
    behind: int = 0
    clean: bool = True
    merge_conflict: bool = False


class GitSafety:
    """Protocolo de segurança Git."""

    ALWAYS_BLOCKED = [
        r"git\s+push\s+.*--force\s+.*(?:main|master)",
        r"git\s+config\s+",
        r"git\s+rebase\s+.*-i\b",
        r"git\s+add\s+.*-i\b",
    ]

    NEEDS_CONFIRMATION = [
        r"git\s+push\s+.*--force",
        r"git\s+push\s+-f\b",
        r"git\s+reset\s+--hard",
        r"git\s+checkout\s+--\s+\.",
        r"git\s+restore\s+\.",
        r"git\s+clean\s+-f",
        r"git\s+branch\s+-D\b",
        r"git\s+stash\s+drop",
        r"git\s+rebase",
        r"git\s+push\b",
    ]

    FORBIDDEN_FLAGS = [
        r"--no-verify",
        r"--no-gpg-sign",
        r"-c\s+commit\.gpgsign=false",
    ]

    def __init__(self, cwd: str) -> None:
        self.cwd = cwd

    def get_status(self) -> GitStatus:
        status = GitStatus()
        try:
            r = subprocess.run(
                "git rev-parse --is-inside-work-tree",
                shell=True, capture_output=True, text=True, cwd=self.cwd,
            )
            status.is_repo = r.returncode == 0
            if not status.is_repo:
                return status

            r = subprocess.run(
                "git branch --show-current",
                shell=True, capture_output=True, text=True, cwd=self.cwd,
            )
            status.branch = r.stdout.strip()

            r = subprocess.run(
                "git status --porcelain",
                shell=True, capture_output=True, text=True, cwd=self.cwd,
            )
            for line in r.stdout.splitlines():
                if not line.strip():
                    continue
                idx = line[0]
                wt = line[1] if len(line) > 1 else " "
                if idx != " " and idx != "?":
                    status.has_staged = True
                if wt != " " and wt != "?":
                    status.has_unstaged = True
                if line.startswith("??"):
                    status.has_untracked = True
                if line.startswith("UU") or line.startswith("AA"):
                    status.merge_conflict = True

            status.clean = not (status.has_staged or status.has_unstaged or status.has_untracked)

            r = subprocess.run(
                "git rev-list --left-right --count HEAD...@{upstream}",
                shell=True, capture_output=True, text=True, cwd=self.cwd,
            )
            if r.returncode == 0:
                parts = r.stdout.strip().split()
                if len(parts) == 2:
                    status.ahead = int(parts[0])
                    status.behind = int(parts[1])
        except Exception:
            pass
        return status

    def validate_command(self, command: str) -> tuple[bool, str]:
        cmd = command.strip()

        for pattern in self.ALWAYS_BLOCKED:
            if re.search(pattern, cmd, re.IGNORECASE):
                reason = f"Comando bloqueado pelo Git Safety Protocol: {cmd[:80]}"
                log_action("git_safety_blocked", reason, level="warning")
                return False, reason

        for pattern in self.FORBIDDEN_FLAGS:
            if re.search(pattern, cmd, re.IGNORECASE):
                reason = f"Flag proibida detectada: {cmd[:80]}. Não use --no-verify ou equivalentes."
                log_action("git_safety_forbidden_flag", reason, level="warning")
                return False, reason

        return True, ""

    def needs_confirmation(self, command: str) -> tuple[bool, str]:
        cmd = command.strip()
        for pattern in self.NEEDS_CONFIRMATION:
            if re.search(pattern, cmd, re.IGNORECASE):
                return True, f"Operação Git sensível: {cmd[:80]}"
        return False, ""

    def pre_commit_check(self) -> tuple[bool, str]:
        status = self.get_status()
        if not status.is_repo:
            return False, "Não é um repositório Git."
        if status.merge_conflict:
            return False, "Existem conflitos de merge não resolvidos."
        if not status.has_staged and not status.has_unstaged and not status.has_untracked:
            return False, "Nada para commitar — working tree limpa."
        return True, ""

    def pre_push_check(self) -> tuple[bool, str]:
        status = self.get_status()
        if not status.is_repo:
            return False, "Não é um repositório Git."
        if status.behind > 0:
            return False, f"Branch está {status.behind} commits atrás do remote. Faça pull primeiro."
        if status.merge_conflict:
            return False, "Existem conflitos de merge não resolvidos."
        return True, ""

    def get_commit_context(self) -> dict:
        context = {"status": "", "diff": "", "log": "", "staged_diff": ""}
        try:
            r = subprocess.run("git status", shell=True, capture_output=True, text=True, cwd=self.cwd)
            context["status"] = r.stdout[:3000]
            r = subprocess.run("git diff", shell=True, capture_output=True, text=True, cwd=self.cwd)
            context["diff"] = r.stdout[:5000]
            r = subprocess.run("git diff --staged", shell=True, capture_output=True, text=True, cwd=self.cwd)
            context["staged_diff"] = r.stdout[:5000]
            r = subprocess.run("git log --oneline -10", shell=True, capture_output=True, text=True, cwd=self.cwd)
            context["log"] = r.stdout[:2000]
        except Exception:
            pass
        return context

    def format_commit_message(self, message: str, co_author: str = "") -> str:
        msg = message.strip()
        if co_author and co_author not in msg:
            msg += f"\n\nCo-Authored-By: {co_author}"
        return msg
