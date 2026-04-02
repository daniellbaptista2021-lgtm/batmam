"""Clow Memory System — lembra fatos do usuario entre conversas."""
from __future__ import annotations
import json
import hashlib
from pathlib import Path

USERS_DIR = Path(__file__).parent.parent / "data" / "users"


def _user_mem_path(user_id: str) -> Path:
    safe = hashlib.sha256(user_id.encode()).hexdigest()[:16]
    d = USERS_DIR / safe
    d.mkdir(parents=True, exist_ok=True)
    return d / "memories.json"


def load_memories(user_id: str) -> list[str]:
    p = _user_mem_path(user_id)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text())
    except Exception:
        return []


def save_memories(user_id: str, memories: list[str]):
    p = _user_mem_path(user_id)
    p.write_text(json.dumps(memories, ensure_ascii=False))


def add_memory(user_id: str, fact: str) -> str:
    mems = load_memories(user_id)
    if fact in mems:
        return "Ja lembro disso."
    mems.append(fact)
    if len(mems) > 50:
        mems = mems[-50:]
    save_memories(user_id, mems)
    return f"Memorizado: {fact}"


def forget_memory(user_id: str, keyword: str) -> str:
    mems = load_memories(user_id)
    before = len(mems)
    mems = [m for m in mems if keyword.lower() not in m.lower()]
    if len(mems) == before:
        return f"Nao encontrei nada com '{keyword}' nas memorias."
    save_memories(user_id, mems)
    removed = before - len(mems)
    return f"Esqueci {removed} memoria(s) com '{keyword}'."


def format_memories_for_prompt(user_id: str) -> str:
    mems = load_memories(user_id)
    if not mems:
        return ""
    return "Memorias do usuario (fatos importantes de conversas anteriores):\n" + "\n".join(f"- {m}" for m in mems)


def format_memories_list(user_id: str) -> str:
    mems = load_memories(user_id)
    if not mems:
        return "Nenhuma memoria salva ainda. Conforme conversamos, vou lembrar fatos importantes."
    lines = ["## Memorias do Clow\n"]
    for i, m in enumerate(mems, 1):
        lines.append(f"{i}. {m}")
    lines.append(f"\nUse `/forget palavra` para remover uma memoria.")
    return "\n".join(lines)
