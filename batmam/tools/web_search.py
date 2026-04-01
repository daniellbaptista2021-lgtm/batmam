"""WebSearchTool — busca web com resultados estruturados via DuckDuckGo."""

from __future__ import annotations
import json
import re
from urllib.request import urlopen, Request
from urllib.parse import quote_plus
from typing import Any
from .base import BaseTool


class WebSearchTool(BaseTool):
    name = "web_search"
    description = "Busca na web usando DuckDuckGo. Retorna resultados com título, URL e snippet."
    requires_confirmation = False

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Termo de busca"},
                "max_results": {"type": "integer", "description": "Máximo de resultados (padrão: 10)"},
            },
            "required": ["query"],
        }

    def execute(self, **kwargs: Any) -> str:
        query: str = kwargs.get("query", "")
        if not query:
            return "Erro: query é obrigatório."

        max_results: int = kwargs.get("max_results", 10)

        results = self._search_ddg_api(query, max_results)
        if not results:
            results = self._search_ddg_lite(query, max_results)

        if not results:
            return f"Nenhum resultado encontrado para: {query}"

        lines = []
        for i, r in enumerate(results[:max_results], 1):
            lines.append(f"{i}. {r['title']}")
            lines.append(f"   {r['url']}")
            if r.get("snippet"):
                lines.append(f"   {r['snippet'][:200]}")
            lines.append("")

        return "\n".join(lines).strip()

    def _search_ddg_api(self, query: str, max_results: int) -> list[dict]:
        try:
            url = f"https://api.duckduckgo.com/?q={quote_plus(query)}&format=json&no_html=1&skip_disambig=1"
            req = Request(url, headers={"User-Agent": "Batmam/0.2"})
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            results = []
            if data.get("Abstract"):
                results.append({
                    "title": data.get("Heading", query),
                    "url": data.get("AbstractURL", ""),
                    "snippet": data.get("Abstract", ""),
                })

            for topic in data.get("RelatedTopics", []):
                if len(results) >= max_results:
                    break
                if "Topics" in topic:
                    for sub in topic["Topics"]:
                        if len(results) >= max_results:
                            break
                        text = sub.get("Text", "")
                        href = sub.get("FirstURL", "")
                        if text and href:
                            title = text.split(" - ")[0] if " - " in text else text[:60]
                            results.append({"title": title, "url": href, "snippet": text})
                else:
                    text = topic.get("Text", "")
                    href = topic.get("FirstURL", "")
                    if text and href:
                        title = text.split(" - ")[0] if " - " in text else text[:60]
                        results.append({"title": title, "url": href, "snippet": text})

            for r in data.get("Results", []):
                if len(results) >= max_results:
                    break
                results.append({"title": r.get("Text", "")[:80], "url": r.get("FirstURL", ""), "snippet": r.get("Text", "")})

            return results
        except Exception:
            return []

    def _search_ddg_lite(self, query: str, max_results: int) -> list[dict]:
        try:
            url = f"https://lite.duckduckgo.com/lite/?q={quote_plus(query)}"
            req = Request(url, headers={"User-Agent": "Batmam/0.2"})
            with urlopen(req, timeout=10) as resp:
                html = resp.read().decode("utf-8", errors="ignore")

            results = []
            link_pattern = r'<a[^>]+href="(https?://[^"]+)"[^>]*>([^<]{5,})</a>'
            for match in re.finditer(link_pattern, html):
                if len(results) >= max_results:
                    break
                href = match.group(1)
                title = match.group(2).strip()
                if "duckduckgo" not in href:
                    results.append({"title": title, "url": href, "snippet": ""})

            snippet_pattern = r'<td[^>]*class="result-snippet"[^>]*>(.*?)</td>'
            snippets = re.findall(snippet_pattern, html, re.DOTALL)
            for i, snippet in enumerate(snippets):
                if i < len(results):
                    clean = re.sub(r"<[^>]+>", "", snippet).strip()
                    results[i]["snippet"] = clean[:200]

            return results
        except Exception:
            return []
