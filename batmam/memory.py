"""Sistema de memória persistente do Batmam v0.2.0.

Memória tipada com 4 tipos (user/feedback/project/reference),
frontmatter YAML, agrupamento por tipo, e índice MEMORY.md.
"""

from __future__ import annotations
import time
from pathlib import Path
from . import config

MEMORY_TYPES = {"user", "feedback", "project", "reference", "general"}


def load_memory_context() -> str:
    """Carrega todas as memórias para injetar no system prompt, agrupadas por tipo."""
    memory_dir = config.MEMORY_DIR
    if not memory_dir.exists():
        return ""

    memories_by_type: dict[str, list[str]] = {}
    index_file = memory_dir / "MEMORY.md"

    # Carrega índice se existir
    index_content = ""
    if index_file.exists():
        index_content = index_file.read_text(encoding="utf-8").strip()

    # Carrega arquivos de memória individuais, agrupados por tipo
    for f in sorted(memory_dir.glob("*.md")):
        if f.name == "MEMORY.md":
            continue
        try:
            content = f.read_text(encoding="utf-8").strip()
            if not content:
                continue

            # Extrai tipo do frontmatter
            mtype = "general"
            body_lines = []
            in_frontmatter = False
            frontmatter_done = False

            for line in content.splitlines():
                if line.strip() == "---" and not frontmatter_done:
                    if not in_frontmatter:
                        in_frontmatter = True
                        continue
                    else:
                        in_frontmatter = False
                        frontmatter_done = True
                        continue

                if in_frontmatter:
                    if line.startswith("type:"):
                        mtype = line.split(":", 1)[1].strip()
                elif frontmatter_done:
                    body_lines.append(line)
                else:
                    body_lines.append(line)

            body = "\n".join(body_lines).strip()
            if body:
                if mtype not in memories_by_type:
                    memories_by_type[mtype] = []
                memories_by_type[mtype].append(f"### {f.stem}\n{body}")

        except Exception:
            continue

    # Monta contexto agrupado
    sections = []
    if index_content:
        sections.append(f"## Índice\n{index_content}")

    type_labels = {
        "user": "Sobre o Usuário",
        "feedback": "Feedback e Correções",
        "project": "Contexto do Projeto",
        "reference": "Referências Externas",
        "general": "Geral",
    }

    for mtype in ["user", "feedback", "project", "reference", "general"]:
        if mtype in memories_by_type:
            label = type_labels.get(mtype, mtype.title())
            entries = "\n\n".join(memories_by_type[mtype])
            sections.append(f"## {label}\n{entries}")

    return "\n\n".join(sections) if sections else ""


def save_memory(
    name: str,
    content: str,
    memory_type: str = "general",
    description: str = "",
) -> Path:
    """Salva uma memória com frontmatter tipado."""
    if memory_type not in MEMORY_TYPES:
        memory_type = "general"

    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    filepath = config.MEMORY_DIR / f"{safe_name}.md"

    if not description:
        description = content[:80].replace("\n", " ")

    text = f"""---
name: {name}
description: {description}
type: {memory_type}
saved_at: {time.strftime('%Y-%m-%d %H:%M')}
---

{content}
"""
    filepath.write_text(text, encoding="utf-8")

    # Atualiza índice
    _update_index()

    return filepath


def delete_memory(name: str) -> bool:
    """Deleta uma memória."""
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    filepath = config.MEMORY_DIR / f"{safe_name}.md"
    if filepath.exists():
        filepath.unlink()
        _update_index()
        return True
    return False


def list_memories() -> list[dict]:
    """Lista todas as memórias com metadados."""
    memories = []
    for f in sorted(config.MEMORY_DIR.glob("*.md")):
        if f.name == "MEMORY.md":
            continue
        try:
            content = f.read_text(encoding="utf-8")
            name = f.stem
            mtype = "general"
            description = ""
            for line in content.splitlines():
                if line.startswith("name:"):
                    name = line.split(":", 1)[1].strip()
                elif line.startswith("type:"):
                    mtype = line.split(":", 1)[1].strip()
                elif line.startswith("description:"):
                    description = line.split(":", 1)[1].strip()
            memories.append({
                "name": name,
                "type": mtype,
                "description": description,
                "file": f.name,
            })
        except Exception:
            continue
    return memories


def _update_index() -> None:
    """Atualiza MEMORY.md com lista de memórias agrupadas por tipo."""
    entries_by_type: dict[str, list[str]] = {}

    for f in sorted(config.MEMORY_DIR.glob("*.md")):
        if f.name == "MEMORY.md":
            continue
        try:
            content = f.read_text(encoding="utf-8")
            name = f.stem
            mtype = "general"
            desc = ""
            for line in content.splitlines():
                if line.startswith("name:"):
                    name = line.split(":", 1)[1].strip()
                elif line.startswith("type:"):
                    mtype = line.split(":", 1)[1].strip()
                elif line.startswith("description:"):
                    desc = line.split(":", 1)[1].strip()

            entry = f"- [{name}]({f.name}) — {desc or mtype}"
            if mtype not in entries_by_type:
                entries_by_type[mtype] = []
            entries_by_type[mtype].append(entry)
        except Exception:
            continue

    lines = []
    for mtype in ["user", "feedback", "project", "reference", "general"]:
        if mtype in entries_by_type:
            lines.append(f"## {mtype}")
            lines.extend(entries_by_type[mtype])
            lines.append("")

    index_path = config.MEMORY_DIR / "MEMORY.md"
    index_path.write_text("\n".join(lines) + "\n" if lines else "", encoding="utf-8")
