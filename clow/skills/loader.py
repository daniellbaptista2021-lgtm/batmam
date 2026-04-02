"""Skill Loader — carrega skills relevantes para o system prompt."""
from __future__ import annotations
import json
import logging
from pathlib import Path

log = logging.getLogger("clow.skills")
SKILLS_DIR = Path(__file__).parent

# Registry cache
_registry: list[dict] | None = None
_skill_cache: dict[str, str] = {}

# Keywords que ativam o design system (skill interna)
DESIGN_KEYWORDS = [
    "landing", "site", "page", "pagina", "app", "frontend", "interface",
    "design", "layout", "dashboard", "html", "css", "hotsite", "lp",
    "calculadora", "ferramenta", "sistema", "aplicativo",
]


def _load_registry() -> list[dict]:
    global _registry
    if _registry is not None:
        return _registry
    reg_path = SKILLS_DIR / "imported" / "registry.json"
    if reg_path.exists():
        data = json.loads(reg_path.read_text(encoding="utf-8"))
        _registry = data.get("skills", [])
    else:
        _registry = []
    return _registry


def _read_skill(path: str) -> str:
    """Le conteudo de uma skill, com cache."""
    if path in _skill_cache:
        return _skill_cache[path]
    full = SKILLS_DIR / path
    if full.exists():
        content = full.read_text(encoding="utf-8")
        # Truncar skills muito grandes (max 3000 chars pra nao estourar tokens)
        if len(content) > 3000:
            content = content[:3000] + "\n\n[... truncado para economia de tokens ...]"
        _skill_cache[path] = content
        return content
    return ""


def detect_skills(prompt: str, max_skills: int = 2) -> list[dict]:
    """Detecta skills relevantes para o prompt. Retorna top N."""
    registry = _load_registry()
    lower = prompt.lower()
    scored = []

    for skill in registry:
        triggers = skill.get("trigger_words", [])
        if "__always__" in triggers:
            continue  # Tratado separadamente
        matches = sum(1 for tw in triggers if tw in lower)
        if matches > 0:
            scored.append((matches, skill))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [s[1] for s in scored[:max_skills]]


def get_always_skills() -> list[dict]:
    """Retorna skills marcadas como __always__."""
    registry = _load_registry()
    return [s for s in registry if "__always__" in s.get("trigger_words", [])]


def build_skill_prompt(prompt: str) -> str:
    """Constroi o bloco de skill para injecao no system prompt."""
    parts = []

    # Skills always-on (content-humanizer)
    for skill in get_always_skills():
        content = _read_skill(skill["path"])
        if content:
            parts.append(f"[Skill: {skill['name']}]\n{content}")

    # Skills detectadas por keyword
    detected = detect_skills(prompt)
    for skill in detected:
        content = _read_skill(skill["path"])
        if content:
            parts.append(f"[Skill: {skill['name']} ativada]\n{content}")
            log.info(f"Skill ativada: {skill['id']}")

    if not parts:
        return ""

    return "\n\n---\n\n".join(parts)


def list_all_skills() -> dict[str, list[dict]]:
    """Lista todas skills por categoria."""
    registry = _load_registry()
    by_cat: dict[str, list] = {}
    for s in registry:
        cat = s.get("category", "other")
        by_cat.setdefault(cat, []).append({"id": s["id"], "name": s["name"]})
    return by_cat


def format_skills_list(category: str = "") -> str:
    """Formata lista de skills para exibicao no chat."""
    by_cat = list_all_skills()

    if category:
        skills = by_cat.get(category.lower(), [])
        if not skills:
            return f"Nenhuma skill encontrada na categoria '{category}'.\nCategorias: {', '.join(by_cat.keys())}"
        lines = [f"## Skills — {category.title()}\n"]
        for s in skills:
            lines.append(f"- **{s['name']}** (`{s['id']}`)")
        return "\n".join(lines)

    lines = ["## Skills Disponiveis\n"]
    for cat, skills in sorted(by_cat.items()):
        lines.append(f"### {cat.title()}")
        for s in skills:
            lines.append(f"- **{s['name']}** (`{s['id']}`)")
        lines.append("")

    # Design system (skill interna)
    lines.append("### Design")
    lines.append("- **Clow Design System** (`design-system`) — automatico em geracao visual")
    lines.append("")
    lines.append(f"**Total: {sum(len(v) for v in by_cat.values()) + 1} skills**")
    return "\n".join(lines)


# ── Design system (skill interna) ──

def should_load_design_skill(prompt: str) -> bool:
    lower = prompt.lower()
    return any(kw in lower for kw in DESIGN_KEYWORDS)


def get_design_system_prompt() -> str:
    skill_path = SKILLS_DIR / "design_system" / "SKILL.md"
    ref_path = SKILLS_DIR / "design_system" / "REFERENCE.md"
    parts = []
    if skill_path.exists():
        parts.append(skill_path.read_text(encoding="utf-8"))
    if ref_path.exists():
        parts.append(ref_path.read_text(encoding="utf-8"))
    return "\n\n---\n\n".join(parts)


def get_design_prompt_for(prompt: str) -> str:
    if should_load_design_skill(prompt):
        return get_design_system_prompt()
    return ""
