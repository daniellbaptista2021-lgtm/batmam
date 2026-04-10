"""Git Operations Tool — todas as operacoes git basicas em uma unica tool."""

from __future__ import annotations
import subprocess
from typing import Any
from .base import BaseTool


class GitOpsTool(BaseTool):
    name = "git_ops"
    description = (
        "Operacoes git completas: init, clone, add, commit, push, pull, "
        "branch, checkout, merge, status, log, diff, tag, remote."
    )
    requires_confirmation = True

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "init", "clone", "add", "commit", "push", "pull",
                        "branch", "checkout", "merge", "status", "log", "diff",
                        "tag", "remote_add", "remote_list", "fetch",
                    ],
                    "description": "Operacao git",
                },
                "args": {"type": "string", "description": "Argumentos da operacao (ex: branch name, commit msg, url)"},
                "cwd": {"type": "string", "description": "Diretorio de trabalho"},
                "flags": {"type": "string", "description": "Flags adicionais (ex: --all, -b, --force)"},
            },
            "required": ["action"],
        }

    def execute(self, **kwargs: Any) -> str:
        action = kwargs["action"]
        args = kwargs.get("args", "")
        cwd = kwargs.get("cwd", None)
        flags = kwargs.get("flags", "")

        cmd_map = {
            "init": "git init",
            "clone": f"git clone {args}" if args else None,
            "add": f"git add {args or '.'}",
            "commit": f'git commit -m "{args}"' if args else None,
            "push": f"git push {flags} {args}".strip(),
            "pull": f"git pull {flags} {args}".strip(),
            "branch": f"git branch {flags} {args}".strip() if args or flags else "git branch -a",
            "checkout": f"git checkout {flags} {args}".strip() if args else None,
            "merge": f"git merge {flags} {args}".strip() if args else None,
            "status": "git status --short",
            "log": f"git log --oneline -20 {flags}".strip(),
            "diff": f"git diff {args}".strip(),
            "tag": f"git tag {flags} {args}".strip() if args else "git tag -l",
            "remote_add": f"git remote add origin {args}" if args else None,
            "remote_list": "git remote -v",
            "fetch": f"git fetch {args or '--all'}",
        }

        cmd = cmd_map.get(action)
        if cmd is None:
            need_args = {"clone", "commit", "checkout", "merge"}
            if action in need_args:
                return f"Erro: args obrigatorio para '{action}'."
            return f"Acao '{action}' nao reconhecida."

        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60, cwd=cwd)
            output = (r.stdout or "") + (r.stderr or "")
            return output[:5000] or f"git {action}: OK"
        except subprocess.TimeoutExpired:
            return f"Timeout ao executar: git {action}"
        except Exception as e:
            return f"Erro: {e}"
