"""Docker Manage Tool — gerencia containers Docker via CLI."""

from __future__ import annotations
import subprocess
from typing import Any
from .base import BaseTool


class DockerManageTool(BaseTool):
    name = "docker_manage"
    description = "Gerencia containers Docker. Ações: ps, logs, restart, stop, start, stats."
    requires_confirmation = True

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["ps", "logs", "restart", "stop", "start", "stats", "inspect"],
                    "description": "Ação Docker a executar",
                },
                "container": {"type": "string", "description": "Nome ou ID do container (para logs/restart/stop/start)"},
                "tail": {"type": "integer", "description": "Número de linhas de log (padrão: 50)"},
                "follow": {"type": "boolean", "description": "Seguir logs em tempo real (padrão: false)"},
            },
            "required": ["action"],
        }

    def execute(self, **kwargs: Any) -> str:
        action = kwargs.get("action", "")
        container = kwargs.get("container", "")
        tail = kwargs.get("tail", 50)

        try:
            if action == "ps":
                cmd = "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}\t{{.Image}}'"
                return self._run(cmd)

            if action == "stats":
                cmd = "docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}'"
                return self._run(cmd)

            if not container:
                return "Erro: container é obrigatório para esta ação."

            if action == "logs":
                cmd = f"docker logs --tail {tail} {container}"
                return self._run(cmd, max_output=5000)

            elif action == "restart":
                return self._run(f"docker restart {container}")

            elif action == "stop":
                return self._run(f"docker stop {container}")

            elif action == "start":
                return self._run(f"docker start {container}")

            elif action == "inspect":
                return self._run(f"docker inspect {container}", max_output=3000)

            return f"Ação '{action}' não reconhecida."

        except Exception as e:
            return f"Erro Docker: {e}"

    @staticmethod
    def _run(cmd: str, max_output: int = 5000) -> str:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=30,
        )
        output = result.stdout or result.stderr
        if not output.strip():
            return f"Comando executado: {cmd}"
        if len(output) > max_output:
            output = output[:max_output] + "\n... (truncado)"
        return output
