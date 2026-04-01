"""Scraper Tool — web scraping de páginas."""

from __future__ import annotations
import json
import re
from urllib.request import urlopen, Request
from urllib.error import URLError
from typing import Any
from .base import BaseTool


class ScraperTool(BaseTool):
    name = "scraper"
    description = "Faz web scraping de páginas. Extrai dados via seletores CSS ou regex."
    requires_confirmation = False

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL da página para scraping"},
                "selector": {"type": "string", "description": "Seletor CSS, tag HTML, ou regex para extrair dados"},
                "output_format": {
                    "type": "string",
                    "enum": ["text", "json", "csv"],
                    "description": "Formato de saída (padrão: text)",
                },
                "extract": {
                    "type": "string",
                    "enum": ["text", "links", "images", "tables", "meta", "all"],
                    "description": "O que extrair (padrão: text)",
                },
            },
            "required": ["url"],
        }

    def execute(self, **kwargs: Any) -> str:
        url = kwargs.get("url", "")
        if not url:
            return "Erro: url é obrigatório."

        selector = kwargs.get("selector", "")
        output_format = kwargs.get("output_format", "text")
        extract = kwargs.get("extract", "text")

        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; Clow/0.2)"})
            resp = urlopen(req, timeout=30)
            html = resp.read().decode("utf-8", errors="replace")

            # Tenta usar BeautifulSoup se disponível
            try:
                from bs4 import BeautifulSoup
                return self._scrape_bs4(html, selector, extract, output_format)
            except ImportError:
                return self._scrape_regex(html, selector, extract, output_format)

        except URLError as e:
            return f"Erro ao acessar {url}: {e}"
        except Exception as e:
            return f"Erro: {e}"

    def _scrape_bs4(self, html: str, selector: str, extract: str, fmt: str) -> str:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        results = []

        if selector:
            elements = soup.select(selector)
            results = [el.get_text(strip=True) for el in elements]
        elif extract == "links":
            results = [{"text": a.get_text(strip=True), "href": a.get("href", "")}
                       for a in soup.find_all("a", href=True)]
        elif extract == "images":
            results = [{"alt": img.get("alt", ""), "src": img.get("src", "")}
                       for img in soup.find_all("img")]
        elif extract == "tables":
            for table in soup.find_all("table"):
                rows = []
                for tr in table.find_all("tr"):
                    cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                    rows.append(cells)
                results.append(rows)
        elif extract == "meta":
            results = [{"name": m.get("name", m.get("property", "")), "content": m.get("content", "")}
                       for m in soup.find_all("meta") if m.get("content")]
        else:
            text = soup.get_text(separator="\n", strip=True)
            if len(text) > 8000:
                text = text[:8000] + "\n... (truncado)"
            return text

        return self._format_output(results, fmt)

    def _scrape_regex(self, html: str, selector: str, extract: str, fmt: str) -> str:
        """Fallback sem BeautifulSoup — usa regex."""
        results = []

        if selector:
            pattern = re.compile(selector)
            results = pattern.findall(html)
        elif extract == "links":
            results = re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.I)
            results = [{"href": h, "text": re.sub(r'<[^>]+>', '', t)} for h, t in results]
        elif extract == "images":
            results = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.I)
            results = [{"src": s} for s in results]
        else:
            text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.S | re.I)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.S | re.I)
            text = re.sub(r'<[^>]+>', '\n', text)
            text = re.sub(r'\n{3,}', '\n\n', text).strip()
            if len(text) > 8000:
                text = text[:8000] + "\n... (truncado)"
            return text

        return self._format_output(results, fmt)

    @staticmethod
    def _format_output(results: list, fmt: str) -> str:
        if not results:
            return "(nenhum resultado)"

        if fmt == "json":
            return json.dumps(results[:100], indent=2, ensure_ascii=False)
        elif fmt == "csv":
            if isinstance(results[0], dict):
                keys = list(results[0].keys())
                lines = [",".join(keys)]
                for r in results[:100]:
                    lines.append(",".join(str(r.get(k, "")).replace(",", ";") for k in keys))
                return "\n".join(lines)
            return "\n".join(str(r) for r in results[:100])
        else:
            if isinstance(results[0], dict):
                return "\n".join(json.dumps(r, ensure_ascii=False) for r in results[:100])
            return "\n".join(str(r) for r in results[:100])
