"""Ferramenta Bash - executa comandos no shell."""

from __future__ import annotations
import subprocess
import os
from typing import Any
from .base import BaseTool


class BashTool(BaseTool):
    name = "bash"
    description = (
        "Executa um comando bash e retorna stdout+stderr. "
        "Use para operações de sistema, git, instalação de pacotes, "
        "compilação e qualquer comando de terminal."
    )
    requires_confirmation = True

    # Limite de saída para não estourar contexto
    MAX_OUTPUT = 50_000

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "O comando bash a ser executado.",
                },
                "cwd": {
                    "type": "string",
                    "description": "Diretório de trabalho (opcional). Se não informado, usa o diretório atual.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout em segundos (padrão: 120).",
                },
            },
            "required": ["command"],
        }

    def execute(self, **kwargs: Any) -> str:
        command = kwargs.get("command", "")
        cwd = kwargs.get("cwd") or os.getcwd()
        timeout = kwargs.get("timeout", 120)

        if not command.strip():
            return "[ERROR] Comando vazio."

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=cwd,
                timeout=timeout,
                env={**os.environ},
            )

            output_parts = []
            if result.stdout:
                output_parts.append(result.stdout)
            if result.stderr:
                output_parts.append(f"[STDERR]\n{result.stderr}")

            output = "\n".join(output_parts) if output_parts else "(sem saída)"

            if result.returncode != 0:
                output = f"[EXIT CODE: {result.returncode}]\n{output}"

            # Truncar se muito grande
            if len(output) > self.MAX_OUTPUT:
                half = self.MAX_OUTPUT // 2
                output = (
                    output[:half]
                    + f"\n\n... [TRUNCADO: {len(output)} chars total] ...\n\n"
                    + output[-half:]
                )

            return output

        except subprocess.TimeoutExpired:
            return f"[ERROR] Comando expirou após {timeout}s: {command}"
        except Exception as e:
            return f"[ERROR] Falha ao executar: {e}"
