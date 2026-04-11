"""Skill Tool - execute skills by name, loading from clow.skills."""

from __future__ import annotations
from typing import Any
from .base import BaseTool


class SkillTool(BaseTool):
    """Execute a skill by name. Loads skill and returns content for the LLM."""

    name = "skill"
    description = (
        "Execute a skill by name. Loads the skill definition and returns "
        "its content/instructions for the LLM to follow. Skills provide "
        "specialized capabilities and domain knowledge."
    )
    requires_confirmation = False
    _is_read_only = True
    _is_concurrency_safe = True
    _is_destructive = False
    _search_hint = "skill execute capability domain"
    _aliases = ["run_skill", "invoke_skill"]

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "Name of the skill to execute (e.g. 'pdf', 'commit', 'review-pr').",
                },
                "args": {
                    "type": "string",
                    "description": "Optional arguments to pass to the skill.",
                },
            },
            "required": ["skill_name"],
        }

    def execute(self, **kwargs: Any) -> str:
        skill_name = kwargs.get("skill_name", "")
        args = kwargs.get("args", "")

        if not skill_name:
            return "[ERROR] skill_name is required."

        # Try loading from skills engine
        try:
            from ..skills_engine import SKILL_MAP
            if skill_name in SKILL_MAP:
                skill_info = SKILL_MAP[skill_name]
                return (
                    f"[SKILL: {skill_name}]\n"
                    f"Type: {skill_info.get('label', skill_name)}\n"
                    f"Library: {skill_info.get('lib', 'N/A')}\n"
                    f"Extension: {skill_info.get('ext', 'N/A')}\n"
                    f"Args: {args if args else '(none)'}\n\n"
                    f"Skill loaded. Follow the skill instructions to generate output."
                )
        except ImportError:
            pass

        # Try loading from .clow/skills/ directory
        try:
            from pathlib import Path
            skills_dir = Path.cwd() / ".clow" / "skills"
            skill_file = skills_dir / f"{skill_name}.md"
            if skill_file.exists():
                content = skill_file.read_text(encoding="utf-8")
                return f"[SKILL: {skill_name}]\n\n{content}"

            # Try .txt
            skill_file = skills_dir / f"{skill_name}.txt"
            if skill_file.exists():
                content = skill_file.read_text(encoding="utf-8")
                return f"[SKILL: {skill_name}]\n\n{content}"

            # Try .py
            skill_file = skills_dir / f"{skill_name}.py"
            if skill_file.exists():
                content = skill_file.read_text(encoding="utf-8")
                return f"[SKILL: {skill_name}] (Python script)\n\n{content}"
        except Exception:
            pass

        # Try loading from ~/.clow/skills/
        try:
            from pathlib import Path
            from .. import config
            global_skills = config.CLOW_HOME / "skills"
            for ext in (".md", ".txt", ".py"):
                skill_file = global_skills / f"{skill_name}{ext}"
                if skill_file.exists():
                    content = skill_file.read_text(encoding="utf-8")
                    return f"[SKILL: {skill_name}]\n\n{content}"
        except Exception:
            pass

        # List available skills if not found
        available = []
        try:
            from ..skills_engine import SKILL_MAP
            available.extend(SKILL_MAP.keys())
        except ImportError:
            pass

        try:
            from pathlib import Path
            for skills_dir in [Path.cwd() / ".clow" / "skills", config.CLOW_HOME / "skills"]:
                if skills_dir.exists():
                    for f in skills_dir.iterdir():
                        if f.suffix in (".md", ".txt", ".py"):
                            available.append(f.stem)
        except Exception:
            pass

        if available:
            return f"[ERROR] Skill '{skill_name}' not found. Available: {', '.join(sorted(set(available)))}"
        return f"[ERROR] Skill '{skill_name}' not found. No skills directory found."
