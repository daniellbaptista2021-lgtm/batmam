"""Website Cloner — pipeline 5-fases inspirado em ai-website-cloner-template.

Pipeline:
  1. recon       — screenshots desktop+mobile, design tokens, behaviors, DOM topology
  2. foundation  — copia scaffold Next.js, popula globals.css, baixa assets
  3. specs       — divide em secoes, gera spec markdown por componente (deepseek-reasoner)
  4. builder     — gera componente React/TSX por secao, valida tsc (deepseek-reasoner)
  5. qa          — screenshot do clone, diff visual, retry de discrepancias

Uso:
    from clow.skills.website_cloner import clone_site, format_result
    result = clone_site("https://example.com")
    print(format_result(result))
"""
from __future__ import annotations

from .pipeline import clone_site, format_result

__all__ = ["clone_site", "format_result"]
