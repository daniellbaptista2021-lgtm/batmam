"""Ferramenta Grep - busca conteúdo em arquivos com regex."""

from __future__ import annotations
import re
import os
from pathlib import Path
from typing import Any
from .base import BaseTool


class GrepTool(BaseTool):
    name = "grep"
    description = (
        "Busca conteúdo em arquivos usando regex. "
        "Pode filtrar por tipo de arquivo e limitar resultados. "
        "Modos: 'content' (linhas), 'files' (só caminhos), 'count'."
    )
    requires_confirmation = False

    MAX_RESULTS = 250

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Padrão regex para buscar no conteúdo dos arquivos.",
                },
                "path": {
                    "type": "string",
                    "description": "Arquivo ou diretório para buscar. Padrão: diretório atual.",
                },
                "glob": {
                    "type": "string",
                    "description": "Filtro glob para arquivos (ex: '*.py', '*.js').",
                },
                "mode": {
                    "type": "string",
                    "enum": ["content", "files", "count"],
                    "description": "Modo de saída. Padrão: 'files'.",
                },
                "case_insensitive": {
                    "type": "boolean",
                    "description": "Busca case-insensitive. Padrão: false.",
                },
                "context_lines": {
                    "type": "integer",
                    "description": "Linhas de contexto antes/depois do match.",
                },
            },
            "required": ["pattern"],
        }

    def execute(self, **kwargs: Any) -> str:
        pattern_str = kwargs.get("pattern", "")
        base_path = kwargs.get("path") or os.getcwd()
        glob_filter = kwargs.get("glob")
        mode = kwargs.get("mode", "files")
        case_insensitive = kwargs.get("case_insensitive", False)
        context_lines = kwargs.get("context_lines", 0)

        if not pattern_str:
            return "[ERROR] pattern é obrigatório."

        flags = re.IGNORECASE if case_insensitive else 0
        try:
            regex = re.compile(pattern_str, flags)
        except re.error as e:
            return f"[ERROR] Regex inválida: {e}"

        base = Path(base_path).expanduser().resolve()

        if base.is_file():
            files = [base]
        elif base.is_dir():
            if glob_filter:
                files = [f for f in base.rglob(glob_filter) if f.is_file()]
            else:
                files = [f for f in base.rglob("*") if f.is_file()]
        else:
            return f"[ERROR] Caminho não encontrado: {base}"

        # Ignora diretórios comuns
        skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", ".tox"}
        files = [
            f for f in files
            if not any(part in skip_dirs for part in f.parts)
        ]

        results = []
        match_count = 0

        for file_path in sorted(files):
            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            lines = text.splitlines()
            file_matches = []

            for i, line in enumerate(lines):
                if regex.search(line):
                    file_matches.append((i + 1, line))
                    match_count += 1

            if not file_matches:
                continue

            if mode == "files":
                results.append(str(file_path))
            elif mode == "count":
                results.append(f"{file_path}: {len(file_matches)}")
            elif mode == "content":
                results.append(f"\n── {file_path} ──")
                for lineno, line_text in file_matches:
                    # Contexto
                    if context_lines > 0:
                        start = max(0, lineno - 1 - context_lines)
                        end = min(len(lines), lineno + context_lines)
                        for ci in range(start, end):
                            prefix = ">" if ci == lineno - 1 else " "
                            results.append(f"  {prefix} {ci + 1:>6}\t{lines[ci]}")
                        results.append("")
                    else:
                        results.append(f"  {lineno:>6}\t{line_text}")

            if len(results) >= self.MAX_RESULTS:
                break

        if not results:
            return f"Nenhum resultado para '{pattern_str}'"

        header = f"{match_count} match(es)"
        return f"{header}\n" + "\n".join(results[:self.MAX_RESULTS])
