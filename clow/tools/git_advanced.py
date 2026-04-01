"""Git Advanced Tool — operações git avançadas."""

from __future__ import annotations
import subprocess
from typing import Any
from .base import BaseTool


class GitAdvancedTool(BaseTool):
    name = "git_advanced"
    description = "Operações git avançadas: cherry-pick, rebase, stash, bisect, log_graph, blame."
    requires_confirmation = True

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["cherry_pick", "rebase", "stash", "stash_pop", "stash_list",
                             "bisect_start", "bisect_good", "bisect_bad", "bisect_reset",
                             "log_graph", "blame", "reflog", "shortlog"],
                    "description": "Operação git a executar",
                },
                "target": {"type": "string", "description": "Commit hash, branch, ou arquivo alvo"},
                "cwd": {"type": "string", "description": "Diretório de trabalho"},
            },
            "required": ["action"],
        }

    def execute(self, **kwargs: Any) -> str:
        action = kwargs.get("action", "")
        target = kwargs.get("target", "")
        cwd = kwargs.get("cwd", None)

        commands = {
            "cherry_pick": f"git cherry-pick {target}" if target else None,
            "rebase": f"git rebase {target}" if target else None,
            "stash": "git stash",
            "stash_pop": "git stash pop",
            "stash_list": "git stash list",
            "bisect_start": "git bisect start",
            "bisect_good": f"git bisect good {target}".strip(),
            "bisect_bad": f"git bisect bad {target}".strip(),
            "bisect_reset": "git bisect reset",
            "log_graph": "git log --oneline --graph --all -20",
            "blame": f"git blame {target}" if target else None,
            "reflog": "git reflog -20",
            "shortlog": "git shortlog -sn --all",
        }

        cmd = commands.get(action)
        if cmd is None:
            return f"Erro: ação '{action}' requer um target." if action in ("cherry_pick", "rebase", "blame") else f"Ação '{action}' não reconhecida."

        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=30, cwd=cwd,
            )
            output = result.stdout or result.stderr
            if not output.strip():
                return f"git {action}: executado com sucesso."
            if len(output) > 5000:
                output = output[:5000] + "\n... (truncado)"
            return output
        except subprocess.TimeoutExpired:
            return f"Erro: git {action} timeout."
        except Exception as e:
            return f"Erro git: {e}"
