"""GlobTool avançado — busca de arquivos por padrão glob.

Features: Glob patterns, sort por mtime, paginação.
"""

from __future__ import annotations
import os
from pathlib import Path
from typing import Any
from .base import BaseTool

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
    ".next", ".nuxt", "target", "vendor", ".cargo",
}


class GlobTool(BaseTool):
    name = "glob"
    description = (
        "Busca arquivos por padrão glob (ex: **/*.py, src/**/*.ts). "
        "Retorna paths ordenados por data de modificação (mais recente primeiro)."
    )
    requires_confirmation = False

    # Behavioral flags (Claude Code Ep.02)
    _is_read_only = True
    _is_concurrency_safe = True
    _is_destructive = False
    _search_hint = "file search pattern"
    _aliases = ["Glob", "find"]

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Padrão glob (ex: **/*.py)"},
                "path": {"type": "string", "description": "Diretório base (padrão: cwd)"},
                "head_limit": {"type": "integer", "description": "Limitar a N resultados (padrão: 500)"},
            },
            "required": ["pattern"],
        }

    def execute(self, **kwargs: Any) -> str:
        pattern: str = kwargs.get("pattern", "")
        if not pattern:
            return "Erro: pattern é obrigatório."

        base_path: str = kwargs.get("path", os.getcwd())
        head_limit: int = kwargs.get("head_limit", 500)

        base = Path(base_path)
        if not base.exists():
            return f"Diretório não encontrado: {base_path}"

        try:
            matches = list(base.glob(pattern))
        except Exception as e:
            return f"Erro no glob: {e}"

        filtered = []
        for p in matches:
            if p.is_dir():
                continue
            parts = p.relative_to(base).parts
            if any(part in SKIP_DIRS or part.startswith(".") for part in parts[:-1]):
                continue
            try:
                mtime = p.stat().st_mtime
                filtered.append((p, mtime))
            except OSError:
                continue

        filtered.sort(key=lambda x: x[1], reverse=True)
        total = len(filtered)
        showing = filtered[:head_limit]

        lines = [str(p.relative_to(base)) for p, _ in showing]
        output = "\n".join(lines)
        if total > head_limit:
            output += f"\n\n... {total - head_limit} arquivos omitidos (total: {total})"
        elif not lines:
            output = f"Nenhum arquivo encontrado para: {pattern}"

        return output
