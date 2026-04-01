"""Carregamento de contexto de projeto (BATMAM.md)."""

from __future__ import annotations
from pathlib import Path


def load_project_context(cwd: str) -> str:
    """Carrega BATMAM.md do diretório de trabalho (equivalente ao CLAUDE.md)."""
    search_paths = [
        Path(cwd) / "BATMAM.md",
        Path(cwd) / ".batmam" / "BATMAM.md",
        Path(cwd) / "CLAUDE.md",  # Compatibilidade
    ]

    for path in search_paths:
        if path.exists():
            try:
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    return content
            except Exception:
                continue

    # Busca recursiva para cima (até 5 níveis)
    current = Path(cwd).resolve()
    for _ in range(5):
        parent = current.parent
        if parent == current:
            break
        for name in ("BATMAM.md", ".batmam/BATMAM.md"):
            candidate = parent / name
            if candidate.exists():
                try:
                    return candidate.read_text(encoding="utf-8").strip()
                except Exception:
                    pass
        current = parent

    return ""
