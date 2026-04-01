"""Ferramenta WebSearch — busca na web."""

from __future__ import annotations
import json
import urllib.request
import urllib.parse
from typing import Any
from .base import BaseTool


class WebSearchTool(BaseTool):
    name = "web_search"
    description = (
        "Busca na web usando DuckDuckGo. Retorna títulos, URLs e trechos dos resultados. "
        "Use para pesquisar documentação, resolver dúvidas técnicas, buscar soluções."
    )
    requires_confirmation = False

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Termos de busca.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Número máximo de resultados (padrão: 8).",
                },
            },
            "required": ["query"],
        }

    def execute(self, **kwargs: Any) -> str:
        query = kwargs.get("query", "")
        max_results = kwargs.get("max_results", 8)

        if not query:
            return "[ERROR] query é obrigatório."

        try:
            return self._search_ddg(query, max_results)
        except Exception as e:
            return f"[ERROR] Falha na busca: {e}"

    def _search_ddg(self, query: str, max_results: int) -> str:
        """Busca usando DuckDuckGo HTML (sem API key necessária)."""
        encoded = urllib.parse.urlencode({"q": query, "format": "json"})
        url = f"https://api.duckduckgo.com/?{encoded}&no_html=1&skip_disambig=1"

        req = urllib.request.Request(url, headers={
            "User-Agent": "Batmam/0.1.0 (AI code agent)"
        })

        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        results = []

        # Abstract (resultado principal)
        if data.get("Abstract"):
            results.append({
                "title": data.get("Heading", ""),
                "url": data.get("AbstractURL", ""),
                "snippet": data.get("Abstract", ""),
            })

        # Related topics
        for topic in data.get("RelatedTopics", [])[:max_results]:
            if isinstance(topic, dict):
                if "Text" in topic:
                    results.append({
                        "title": topic.get("Text", "")[:100],
                        "url": topic.get("FirstURL", ""),
                        "snippet": topic.get("Text", ""),
                    })
                elif "Topics" in topic:
                    for sub in topic["Topics"][:3]:
                        if "Text" in sub:
                            results.append({
                                "title": sub.get("Text", "")[:100],
                                "url": sub.get("FirstURL", ""),
                                "snippet": sub.get("Text", ""),
                            })

        # Results diretos
        for r in data.get("Results", [])[:max_results]:
            results.append({
                "title": r.get("Text", ""),
                "url": r.get("FirstURL", ""),
                "snippet": r.get("Text", ""),
            })

        if not results:
            # Fallback: busca via DuckDuckGo Lite
            return self._search_ddg_lite(query, max_results)

        output = []
        for i, r in enumerate(results[:max_results], 1):
            output.append(f"{i}. {r['title']}")
            if r['url']:
                output.append(f"   {r['url']}")
            if r['snippet']:
                output.append(f"   {r['snippet'][:200]}")
            output.append("")

        return "\n".join(output) if output else "Nenhum resultado encontrado."

    def _search_ddg_lite(self, query: str, max_results: int) -> str:
        """Fallback com DuckDuckGo lite."""
        encoded = urllib.parse.urlencode({"q": query})
        url = f"https://lite.duckduckgo.com/lite/?{encoded}"

        req = urllib.request.Request(url, headers={
            "User-Agent": "Batmam/0.1.0 (AI code agent)"
        })

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="replace")

            # Parse básico de resultados do HTML
            import re
            results = []
            # Busca links de resultado
            links = re.findall(r'<a[^>]+rel="nofollow"[^>]+href="([^"]+)"[^>]*>(.+?)</a>', html)
            snippets = re.findall(r'<td[^>]*class="result-snippet"[^>]*>(.+?)</td>', html, re.DOTALL)

            for i, (link_url, title) in enumerate(links[:max_results]):
                title = re.sub(r"<[^>]+>", "", title).strip()
                snippet = ""
                if i < len(snippets):
                    snippet = re.sub(r"<[^>]+>", "", snippets[i]).strip()

                if title and link_url:
                    results.append(f"{i+1}. {title}\n   {link_url}")
                    if snippet:
                        results.append(f"   {snippet[:200]}")
                    results.append("")

            return "\n".join(results) if results else "Nenhum resultado encontrado."

        except Exception:
            return "Nenhum resultado encontrado."
