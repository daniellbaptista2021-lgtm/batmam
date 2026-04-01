"""Sistema de memória persistente do Batmam.

Armazena informações entre sessões em ~/.batmam/memory/
Equivalente ao sistema de memória do Claude Code.
"""

from __future__ import annotations
import json
import time
from pathlib import Path
from . import config


def load_memory_context() -> str:
    """Carrega todas as memórias para injetar no system prompt."""
    memory_dir = config.MEMORY_DIR
    if not memory_dir.exists():
        return ""

    memories = []
    index_file = memory_dir / "MEMORY.md"

    # Carrega índice se existir
    if index_file.exists():
        memories.append(index_file.read_text(encoding="utf-8").strip())

    # Carrega arquivos de memória individuais
    for f in sorted(memory_dir.glob("*.md")):
        if f.name == "MEMORY.md":
            continue
        try:
            content = f.read_text(encoding="utf-8").strip()
            if content:
                memories.append(f"## {f.stem}\n{content}")
        except Exception:
            continue

    return "\n\n".join(memories) if memories else ""


def save_memory(name: str, content: str, memory_type: str = "general") -> Path:
    """Salva uma memória."""
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    filepath = config.MEMORY_DIR / f"{safe_name}.md"

    text = f"""---
name: {name}
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
    """Lista todas as memórias."""
    memories = []
    for f in sorted(config.MEMORY_DIR.glob("*.md")):
        if f.name == "MEMORY.md":
            continue
        try:
            content = f.read_text(encoding="utf-8")
            # Extrai frontmatter básico
            name = f.stem
            mtype = "general"
            for line in content.splitlines():
                if line.startswith("name:"):
                    name = line.split(":", 1)[1].strip()
                elif line.startswith("type:"):
                    mtype = line.split(":", 1)[1].strip()
            memories.append({"name": name, "type": mtype, "file": f.name})
        except Exception:
            continue
    return memories


def _update_index() -> None:
    """Atualiza MEMORY.md com lista de memórias."""
    entries = []
    for f in sorted(config.MEMORY_DIR.glob("*.md")):
        if f.name == "MEMORY.md":
            continue
        try:
            content = f.read_text(encoding="utf-8")
            name = f.stem
            desc = ""
            for line in content.splitlines():
                if line.startswith("name:"):
                    name = line.split(":", 1)[1].strip()
                elif line.startswith("description:") or line.startswith("type:"):
                    desc = line.split(":", 1)[1].strip()
            entries.append(f"- [{name}]({f.name}) — {desc}")
        except Exception:
            continue

    index_path = config.MEMORY_DIR / "MEMORY.md"
    index_path.write_text("\n".join(entries) + "\n" if entries else "", encoding="utf-8")
