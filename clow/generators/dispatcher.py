"""Dispatcher — detecta tipo de pedido e roteia para o generator correto."""
from __future__ import annotations
import re


RULES = [
    {
        "type": "landing_page",
        "keywords": ["landing", "page", "site", "pagina", "página", "lp", "hotsite"],
        "module": "landing_page",
    },
    {
        "type": "app",
        "keywords": ["sistema", "app", "aplicativo", "calculadora", "ferramenta", "tool", "gerador", "simulador"],
        "module": "app_generator",
    },
    {
        "type": "pptx",
        "keywords": ["apresentação", "apresentacao", "powerpoint", "pptx", "slides", "deck", "slide"],
        "module": "pptx_generator",
    },
    {
        "type": "xlsx",
        "keywords": ["planilha", "excel", "xlsx", "tabela", "spreadsheet"],
        "module": "xlsx_generator",
    },
    {
        "type": "docx",
        "keywords": ["documento", "doc", "docx", "word", "relatório", "relatorio", "contrato", "proposta"],
        "module": "docx_generator",
    },
    {
        "type": "copy",
        "keywords": ["copy", "anúncio", "anuncio", "criativo", "ads", "tráfego", "trafego"],
        "module": "copy_generator",
    },
    {
        "type": "content",
        "keywords": ["conteúdo", "conteudo", "ideia", "ideias", "reels", "stories", "tiktok", "carrossel"],
        "module": "content_ideas",
    },
]

# Palavras que indicam que o usuario quer CRIAR/GERAR algo
ACTION_WORDS = [
    "cri", "gera", "gere", "faz", "faça", "faca", "monta", "monte",
    "produz", "elabor", "desenvolv", "constro", "prepara",
    "quero", "preciso", "me faz", "me gera", "me cria", "me da",
    "me dá", "sugir", "suger", "traz", "traga", "lista",
]


def detect(message: str) -> tuple[str | None, str | None]:
    """Detecta se a mensagem pede geracao de arquivo.

    Returns:
        (module_name, type) ou (None, None) se nao detectar.
    """
    text = message.lower().strip()

    # Checa se tem intencao de criar/gerar
    has_action = any(w in text for w in ACTION_WORDS)

    # Busca keywords por tipo
    for rule in RULES:
        for kw in rule["keywords"]:
            if kw in text:
                # Se tem keyword E acao, ou se a keyword e muito especifica
                if has_action or kw in ("landing", "lp", "hotsite", "pptx", "xlsx", "docx", "copy", "ads", "ideias", "ideia"):
                    return rule["module"], rule["type"]

    return None, None


SKILLS_MODULES = {"xlsx_generator": "xlsx", "docx_generator": "docx", "pptx_generator": "pptx"}


def run_generator(module_name: str, prompt: str, model: str = "", user_id: str = "") -> dict:
    """Executa o generator. Para xlsx/docx/pptx tenta Skills API primeiro."""
    skill_type = SKILLS_MODULES.get(module_name)
    if skill_type:
        from .skills_wrapper import generate_with_fallback
        return generate_with_fallback(prompt, skill_type, model=model or "claude-haiku-4-5-20251001", user_id=user_id)

    import importlib
    mod = importlib.import_module(f".{module_name}", package="clow.generators")
    return mod.generate(prompt)
