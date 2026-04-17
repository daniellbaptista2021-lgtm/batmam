"""Skill /clone — shim que delega pro modulo `website_cloner` (pipeline 5-fases).

Compatibilidade: mantem `clone_site(url, output_dir)` e `format_result(result)`
exportados como antes — qualquer importador antigo continua funcionando.

Pra detalhes: ver `clow.skills.website_cloner`.
"""
from __future__ import annotations

from .website_cloner import clone_site, format_result

__all__ = ["clone_site", "format_result"]
