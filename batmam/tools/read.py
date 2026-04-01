"""Ferramenta Read - lê arquivos do sistema."""

from __future__ import annotations
from pathlib import Path
from typing import Any
from .base import BaseTool


class ReadTool(BaseTool):
    name = "read"
    description = (
        "Lê o conteúdo de um arquivo. Retorna com números de linha. "
        "Suporta offset e limit para arquivos grandes."
    )
    requires_confirmation = False

    MAX_LINES = 2000

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Caminho absoluto ou relativo do arquivo.",
                },
                "offset": {
                    "type": "integer",
                    "description": "Linha inicial (0-indexed). Padrão: 0.",
                },
                "limit": {
                    "type": "integer",
                    "description": f"Número máximo de linhas. Padrão: {self.MAX_LINES}.",
                },
            },
            "required": ["file_path"],
        }

    def execute(self, **kwargs: Any) -> str:
        file_path = kwargs.get("file_path", "")
        offset = kwargs.get("offset", 0)
        limit = kwargs.get("limit", self.MAX_LINES)

        if not file_path:
            return "[ERROR] file_path é obrigatório."

        path = Path(file_path).expanduser().resolve()

        if not path.exists():
            return f"[ERROR] Arquivo não encontrado: {path}"

        if not path.is_file():
            return f"[ERROR] Não é um arquivo: {path}"

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"[ERROR] Não foi possível ler: {e}"

        lines = text.splitlines()
        total = len(lines)
        selected = lines[offset : offset + limit]

        numbered = []
        for i, line in enumerate(selected, start=offset + 1):
            numbered.append(f"{i:>6}\t{line}")

        result = "\n".join(numbered)

        if offset + limit < total:
            result += f"\n\n... [{total - offset - limit} linhas restantes]"

        return result
