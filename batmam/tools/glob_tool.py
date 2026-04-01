"""Ferramenta Glob - busca arquivos por padrão."""

from __future__ import annotations
import fnmatch
import os
from pathlib import Path
from typing import Any
from .base import BaseTool


class GlobTool(BaseTool):
    name = "glob"
    description = (
        "Busca arquivos por padrão glob (ex: '**/*.py', 'src/**/*.ts'). "
        "Retorna caminhos dos arquivos encontrados ordenados por modificação."
    )
    requires_confirmation = False

    MAX_RESULTS = 500

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Padrão glob para buscar arquivos (ex: '**/*.py').",
                },
                "path": {
                    "type": "string",
                    "description": "Diretório base para busca. Padrão: diretório atual.",
                },
            },
            "required": ["pattern"],
        }

    def execute(self, **kwargs: Any) -> str:
        pattern = kwargs.get("pattern", "")
        base_path = kwargs.get("path") or os.getcwd()

        if not pattern:
            return "[ERROR] pattern é obrigatório."

        base = Path(base_path).expanduser().resolve()

        if not base.exists():
            return f"[ERROR] Diretório não encontrado: {base}"

        try:
            matches = sorted(base.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        except Exception as e:
            return f"[ERROR] Erro na busca: {e}"

        # Filtra apenas arquivos
        files = [m for m in matches if m.is_file()]

        if not files:
            return f"Nenhum arquivo encontrado para padrão '{pattern}' em {base}"

        total = len(files)
        shown = files[: self.MAX_RESULTS]

        result = "\n".join(str(f) for f in shown)

        if total > self.MAX_RESULTS:
            result += f"\n\n... [{total - self.MAX_RESULTS} arquivos omitidos]"

        return f"{len(shown)} arquivo(s) encontrado(s):\n{result}"
