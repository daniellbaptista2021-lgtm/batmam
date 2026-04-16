"""Sistema de memória persistente do Clow v0.2.0.

Memória tipada com 4 tipos (user/feedback/project/reference),
frontmatter YAML, agrupamento por tipo, e índice MEMORY.md.
"""

from __future__ import annotations
import hashlib
import os
import re
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

    # Limite de 200 linhas no índice
    if len(lines) > 200:
        lines = lines[:200]
        lines.append("... (índice truncado em 200 linhas)")

    index_path = config.MEMORY_DIR / "MEMORY.md"
    index_path.write_text("\n".join(lines) + "\n" if lines else "", encoding="utf-8")


def validate_memory_content(content: str, memory_type: str = "general") -> tuple[bool, str]:
    """Valida se o conteúdo deve ser salvo na memória.

    Regras de exclusão (matching Claude Code):
    - Code patterns → derivável do código
    - Git history → derivável de git log/blame
    - Debugging solutions → o fix está no código
    - Ephemeral tasks → usar tasks
    """
    exclusion_patterns = [
        (r"(?:class|def|function)\s+\w+\s*[\(\{:]", "Code patterns são deriváveis do código — leia o arquivo diretamente"),
        (r"git\s+(?:log|blame|diff)\s+", "Git history é derivável de git log/blame"),
        (r"(?:fix|fixed|bug|debug).*(?:by changing|by adding|by removing)\s+", "Debugging solutions estão no commit/código"),
        (r"^TODO\s*:|^FIXME\s*:|^HACK\s*:", "TODOs efêmeros devem ser tasks, não memórias"),
    ]

    for pattern, reason in exclusion_patterns:
        if re.search(pattern, content, re.IGNORECASE | re.MULTILINE):
            return False, reason

    return True, ""


def check_memory_stale(memory_file: Path, cwd: str = "") -> tuple[bool, str]:
    """Verifica se uma memória referencia recursos que não existem mais."""
    try:
        content = memory_file.read_text(encoding="utf-8")
    except Exception:
        return False, "Não foi possível ler o arquivo"

    work_dir = cwd or os.getcwd()
    issues = []

    # Procura referências a arquivos
    file_refs = re.findall(
        r'(?:^|\s)([\w/.-]+\.(?:py|js|ts|go|rs|java|rb|php|sh|yaml|yml|json|toml|md))\b',
        content,
    )
    for fpath in file_refs[:5]:
        full_path = os.path.join(work_dir, fpath)
        if not os.path.exists(full_path):
            issues.append(f"Arquivo não encontrado: {fpath}")

    if issues:
        return True, "; ".join(issues)
    return False, ""


def cleanup_stale_memories(cwd: str = "") -> list[str]:
    """Verifica e lista memórias stale (não remove automaticamente)."""
    cleaned = []
    for f in config.MEMORY_DIR.glob("*.md"):
        if f.name == "MEMORY.md":
            continue
        is_stale, reason = check_memory_stale(f, cwd)
        if is_stale:
            cleaned.append(f"{f.stem}: {reason}")
    return cleaned


# ══════════════════════════════════════════════════════════════════
# Memória isolada por usuário (User-scoped memory)
# ══════════════════════════════════════════════════════════════════

def _user_memory_dir(user_id: str) -> Path:
    """Retorna diretório de memória exclusivo do usuário.

    Usa hash SHA-256 truncado para nomes seguros de diretório.
    """
    safe = hashlib.sha256(user_id.encode()).hexdigest()[:16]
    d = config.USER_MEMORIES_DIR / safe
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_user_memory_context(user_id: str) -> str:
    """Carrega memórias do usuário para injetar no system prompt."""
    if not user_id:
        return load_memory_context()  # fallback global

    memory_dir = _user_memory_dir(user_id)

    memories_by_type: dict[str, list[str]] = {}
    index_file = memory_dir / "MEMORY.md"

    index_content = ""
    if index_file.exists():
        index_content = index_file.read_text(encoding="utf-8").strip()

    for f in sorted(memory_dir.glob("*.md")):
        if f.name == "MEMORY.md":
            continue
        try:
            content = f.read_text(encoding="utf-8").strip()
            if not content:
                continue

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


def save_user_memory(
    user_id: str,
    name: str,
    content: str,
    memory_type: str = "general",
    description: str = "",
) -> Path:
    """Salva uma memória no diretório exclusivo do usuário."""
    if not user_id:
        return save_memory(name, content, memory_type, description)  # fallback global

    if memory_type not in MEMORY_TYPES:
        memory_type = "general"

    memory_dir = _user_memory_dir(user_id)
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    filepath = memory_dir / f"{safe_name}.md"

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
    _update_user_index(user_id)
    return filepath


def delete_user_memory(user_id: str, name: str) -> bool:
    """Deleta uma memória do usuário."""
    if not user_id:
        return delete_memory(name)

    memory_dir = _user_memory_dir(user_id)
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    filepath = memory_dir / f"{safe_name}.md"
    if filepath.exists():
        filepath.unlink()
        _update_user_index(user_id)
        return True
    return False


def list_user_memories(user_id: str) -> list[dict]:
    """Lista memórias do usuário com metadados."""
    if not user_id:
        return list_memories()

    memory_dir = _user_memory_dir(user_id)
    memories = []
    for f in sorted(memory_dir.glob("*.md")):
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


def _update_user_index(user_id: str) -> None:
    """Atualiza MEMORY.md do usuário."""
    memory_dir = _user_memory_dir(user_id)
    entries_by_type: dict[str, list[str]] = {}

    for f in sorted(memory_dir.glob("*.md")):
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

    if len(lines) > 200:
        lines = lines[:200]
        lines.append("... (índice truncado em 200 linhas)")

    index_path = memory_dir / "MEMORY.md"
    index_path.write_text("\n".join(lines) + "\n" if lines else "", encoding="utf-8")


def get_user_local_instructions(user_id: str) -> str:
    """Carrega CLOW.local.md personalizado do usuário."""
    if not user_id:
        return ""
    memory_dir = _user_memory_dir(user_id)
    local_file = memory_dir / "CLOW.local.md"
    if local_file.exists():
        try:
            return local_file.read_text(encoding="utf-8").strip()
        except Exception:
            return ""
    return ""


def save_user_local_instructions(user_id: str, content: str) -> Path:
    """Salva CLOW.local.md personalizado do usuário."""
    memory_dir = _user_memory_dir(user_id)
    filepath = memory_dir / "CLOW.local.md"
    filepath.write_text(content, encoding="utf-8")
    return filepath
