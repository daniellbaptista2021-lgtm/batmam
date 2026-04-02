"""Skill Loader — carrega skills relevantes para o system prompt."""
from __future__ import annotations
from pathlib import Path

SKILLS_DIR = Path(__file__).parent

# Keywords que ativam o design system
DESIGN_KEYWORDS = [
    "landing", "site", "page", "pagina", "app", "frontend", "interface",
    "design", "layout", "dashboard", "html", "css", "hotsite", "lp",
    "calculadora", "ferramenta", "sistema", "aplicativo",
]


def should_load_design_skill(prompt: str) -> bool:
    """Verifica se o prompt precisa do design system."""
    lower = prompt.lower()
    return any(kw in lower for kw in DESIGN_KEYWORDS)


def get_design_system_prompt() -> str:
    """Retorna o conteudo da skill de design para injecao no system prompt."""
    skill_path = SKILLS_DIR / "design_system" / "SKILL.md"
    ref_path = SKILLS_DIR / "design_system" / "REFERENCE.md"

    parts = []
    if skill_path.exists():
        parts.append(skill_path.read_text(encoding="utf-8"))
    if ref_path.exists():
        parts.append(ref_path.read_text(encoding="utf-8"))

    return "\n\n---\n\n".join(parts)


def get_design_prompt_for(prompt: str) -> str:
    """Retorna o system prompt de design SE o prompt for visual, senao vazio."""
    if should_load_design_skill(prompt):
        return get_design_system_prompt()
    return ""
