"""CloneWebsiteTool — wrapper BaseTool pro pipeline `website_cloner`."""
from __future__ import annotations

from typing import Any

from .base import BaseTool


class CloneWebsiteTool(BaseTool):
    """Clona um site (landing page, hotsite, marketing) gerando projeto Next.js completo."""

    name = "clone_website"
    description = (
        "Clona um site/landing page gerando projeto Next.js modular com pipeline 5-fases "
        "(recon -> foundation -> specs -> builder -> QA) usando deepseek-reasoner. "
        "Retorna paths dos arquivos gerados em ~/.clow/clones/<dominio>."
    )
    requires_confirmation = False

    _is_read_only = False
    _is_concurrency_safe = False
    _is_destructive = False
    _is_enabled = True
    _search_hint = "clone website landing page nextjs scrape visual reverse engineer"
    _aliases = ["WebsiteCloner", "CloneWebsite", "clone-website"]

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL do site/landing page a clonar (deve comecar com http:// ou https://)",
                },
                "output_dir": {
                    "type": "string",
                    "description": "Diretorio de output. Vazio => ~/.clow/clones/<dominio>",
                },
                "skip_qa": {
                    "type": "boolean",
                    "description": "Pula a fase 5 (QA visual). Default: false",
                },
                "skip_build": {
                    "type": "boolean",
                    "description": "Pula `npm install` e `npm run build`. Default: false",
                },
            },
            "required": ["url"],
        }

    def execute(self, **kwargs: Any) -> str:
        url: str = (kwargs.get("url") or "").strip()
        if not url:
            return "Erro: 'url' eh obrigatorio."
        if not url.startswith(("http://", "https://")):
            return "Erro: URL deve comecar com http:// ou https://"

        output_dir: str = kwargs.get("output_dir", "") or ""
        skip_qa: bool = bool(kwargs.get("skip_qa", False))
        skip_build: bool = bool(kwargs.get("skip_build", False))

        try:
            from ..skills.website_cloner import clone_site, format_result
        except ImportError as e:
            return f"Erro ao importar pipeline: {e}"

        result = clone_site(
            url=url,
            output_dir=output_dir,
            skip_qa=skip_qa,
            skip_build=skip_build,
        )
        return format_result(result)
