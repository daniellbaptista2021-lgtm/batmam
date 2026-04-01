"""Ferramenta WebFetch — busca conteúdo de URLs."""

from __future__ import annotations
import urllib.request
import urllib.error
import re
import html as html_module
from typing import Any
from .base import BaseTool


class WebFetchTool(BaseTool):
    name = "web_fetch"
    description = (
        "Faz fetch do conteúdo de uma URL e retorna o texto. "
        "Remove HTML e retorna texto limpo. "
        "Use para ler documentação, APIs, páginas web."
    )
    requires_confirmation = False

    MAX_SIZE = 100_000  # 100KB de texto

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL completa para buscar (deve começar com http:// ou https://).",
                },
                "raw": {
                    "type": "boolean",
                    "description": "Se true, retorna HTML bruto ao invés de texto limpo. Padrão: false.",
                },
                "headers": {
                    "type": "object",
                    "description": "Headers HTTP adicionais (opcional).",
                },
            },
            "required": ["url"],
        }

    def execute(self, **kwargs: Any) -> str:
        url = kwargs.get("url", "")
        raw = kwargs.get("raw", False)
        extra_headers = kwargs.get("headers", {})

        if not url:
            return "[ERROR] url é obrigatório."

        if not url.startswith(("http://", "https://")):
            return "[ERROR] URL deve começar com http:// ou https://"

        headers = {
            "User-Agent": "Batmam/0.1.0 (AI code agent)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.7",
        }
        headers.update(extra_headers)

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                content_type = resp.headers.get("Content-Type", "")
                data = resp.read(self.MAX_SIZE * 2)  # Lê um pouco mais para o HTML

                # Determina encoding
                encoding = "utf-8"
                if "charset=" in content_type:
                    encoding = content_type.split("charset=")[-1].split(";")[0].strip()

                text = data.decode(encoding, errors="replace")

            if raw or "text/plain" in content_type or "application/json" in content_type:
                return self._truncate(text)

            # HTML → texto limpo
            clean = self._html_to_text(text)
            return self._truncate(clean)

        except urllib.error.HTTPError as e:
            return f"[ERROR] HTTP {e.code}: {e.reason}"
        except urllib.error.URLError as e:
            return f"[ERROR] URL error: {e.reason}"
        except Exception as e:
            return f"[ERROR] Falha no fetch: {e}"

    def _html_to_text(self, html: str) -> str:
        """Converte HTML para texto limpo."""
        # Remove script e style
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<nav[^>]*>.*?</nav>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<footer[^>]*>.*?</footer>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<header[^>]*>.*?</header>", "", text, flags=re.DOTALL | re.IGNORECASE)

        # Headers para markdown
        for i in range(1, 7):
            text = re.sub(rf"<h{i}[^>]*>(.*?)</h{i}>", rf"\n{'#' * i} \1\n", text, flags=re.DOTALL | re.IGNORECASE)

        # Parágrafos e breaks
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</?p[^>]*>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</?div[^>]*>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<li[^>]*>", "\n- ", text, flags=re.IGNORECASE)

        # Links
        text = re.sub(r'<a[^>]+href="([^"]*)"[^>]*>(.*?)</a>', r"\2 (\1)", text, flags=re.DOTALL | re.IGNORECASE)

        # Code blocks
        text = re.sub(r"<pre[^>]*>(.*?)</pre>", r"\n```\n\1\n```\n", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<code[^>]*>(.*?)</code>", r"`\1`", text, flags=re.DOTALL | re.IGNORECASE)

        # Remove todas as tags restantes
        text = re.sub(r"<[^>]+>", "", text)

        # Decode HTML entities
        text = html_module.unescape(text)

        # Limpa espaçamento
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r" +", " ", text)

        lines = [line.strip() for line in text.splitlines()]
        return "\n".join(line for line in lines if line)

    def _truncate(self, text: str) -> str:
        if len(text) > self.MAX_SIZE:
            return text[:self.MAX_SIZE] + f"\n\n... [TRUNCADO: {len(text)} chars total]"
        return text
