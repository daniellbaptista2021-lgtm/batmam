"""Wrapper que tenta Skills API primeiro, fallback para generators manuais."""
from __future__ import annotations
import logging

log = logging.getLogger("clow.skills")


def generate_with_fallback(prompt: str, skill_type: str, model: str = "deepseek-chat", user_id: str = "") -> dict:
    """Tenta Skills API, se falhar usa generator manual.

    skill_type: xlsx, docx, pptx, pdf
    """
    # Tenta Skills API
    try:
        from ..skills_engine import generate_with_skills
        result = generate_with_skills(prompt, skill_type, model=model, user_id=user_id)
        if result.get("type") != "text" or result.get("method") == "skills_api":
            log.info(f"Skills API gerou {skill_type} com sucesso")
            return result
    except Exception as e:
        log.warning(f"Skills API falhou para {skill_type}: {e}")

    # Fallback para generator manual
    log.info(f"Usando generator manual para {skill_type}")
    try:
        if skill_type == "xlsx":
            from . import xlsx_generator
            result = xlsx_generator.generate(prompt)
            result["method"] = "manual"
            return result
        elif skill_type == "docx":
            from . import docx_generator
            result = docx_generator.generate(prompt)
            result["method"] = "manual"
            return result
        elif skill_type == "pptx":
            from . import pptx_generator
            result = pptx_generator.generate(prompt)
            result["method"] = "manual"
            return result
        elif skill_type == "pdf":
            # PDF nao tem generator manual, retorna texto
            from .base import ask_ai
            text = ask_ai(prompt, model=model, user_id=user_id)
            return {"type": "text", "content": text, "method": "manual"}
    except Exception as e:
        log.error(f"Generator manual tambem falhou para {skill_type}: {e}")
        raise

    raise ValueError(f"Skill type '{skill_type}' nao suportado")
