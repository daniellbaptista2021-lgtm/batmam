"""Carregamento de contexto de projeto (CLOW.md).

Percorre toda a cadeia de diretorios ancestrais buscando arquivos de instrucao:
  - CLOW.md, CLOW.local.md
  - .clow/CLOW.md, .clow/instructions.md
  - CLAUDE.md (compatibilidade)

Usa deduplicacao por hash de conteudo para evitar repeticao,
e orcamento de caracteres (4K por arquivo, 12K total) para
nao sobrecarregar o contexto do modelo.
"""

from __future__ import annotations
import hashlib
from pathlib import Path

# Orcamento de conteudo
MAX_CHARS_PER_FILE = 4000
MAX_CHARS_TOTAL = 12000

# Nomes de arquivo buscados em cada diretorio (ordem de prioridade)
INSTRUCTION_FILES = [
    "CLOW.md",
    "CLOW.local.md",
    Path(".clow") / "CLOW.md",
    Path(".clow") / "instructions.md",
    "CLAUDE.md",
]

# Maximo de niveis para subir na arvore de diretorios
MAX_ANCESTOR_DEPTH = 10


def load_project_context(cwd: str) -> str:
    """Carrega contexto do projeto percorrendo a cadeia de ancestrais.

    Busca CLOW.md, CLOW.local.md, .clow/CLOW.md, .clow/instructions.md
    e CLAUDE.md em cada diretorio, de cwd ate a raiz.

    Usa deduplicacao por hash de conteudo e orcamento de caracteres.
    """
    collected: list[tuple[str, str]] = []  # (path_label, content)
    seen_hashes: set[str] = set()
    total_chars = 0

    current = Path(cwd).resolve()

    for depth in range(MAX_ANCESTOR_DEPTH):
        for name in INSTRUCTION_FILES:
            candidate = current / name
            if not candidate.exists() or not candidate.is_file():
                continue

            try:
                raw = candidate.read_text(encoding="utf-8").strip()
            except Exception:
                continue

            if not raw:
                continue

            # Deduplicacao por hash
            content_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            if content_hash in seen_hashes:
                continue
            seen_hashes.add(content_hash)

            # Orcamento por arquivo
            if len(raw) > MAX_CHARS_PER_FILE:
                raw = raw[:MAX_CHARS_PER_FILE] + "\n... (truncado)"

            # Orcamento total
            if total_chars + len(raw) > MAX_CHARS_TOTAL:
                remaining = MAX_CHARS_TOTAL - total_chars
                if remaining > 200:
                    raw = raw[:remaining] + "\n... (orcamento de contexto atingido)"
                    label = _safe_label(candidate, cwd)
                    collected.append((label, raw))
                break

            label = _safe_label(candidate, cwd)
            collected.append((label, raw))
            total_chars += len(raw)

        # Orcamento total atingido
        if total_chars >= MAX_CHARS_TOTAL:
            break

        # Sobe para o diretorio pai
        parent = current.parent
        if parent == current:
            break
        current = parent

    if not collected:
        return ""

    # Formata saida com labels
    if len(collected) == 1:
        return collected[0][1]

    parts = []
    for label, content in collected:
        parts.append(f"## {label}\n{content}")
    return "\n\n".join(parts)


def _safe_label(candidate: Path, cwd: str) -> str:
    """Gera label relativo seguro, sem ValueError."""
    try:
        return str(candidate.relative_to(Path(cwd).resolve()))
    except ValueError:
        return str(candidate)
