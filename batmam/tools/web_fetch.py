"""WebFetchTool — busca conteúdo de URLs com conversão HTML→markdown."""

from __future__ import annotations
import re
import html as html_module
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from typing import Any
from .base import BaseTool


class WebFetchTool(BaseTool):
    name = "web_fetch"
    description = "Busca conteúdo de uma URL e retorna como texto. Converte HTML para markdown."
    requires_confirmation = False

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL para buscar"},
                "max_length": {"type": "integer", "description": "Máximo de caracteres (padrão: 100000)"},
                "headers": {
                    "type": "object", "description": "Headers HTTP adicionais",
                    "additionalProperties": {"type": "string"},
                },
            },
            "required": ["url"],
        }

    def execute(self, **kwargs: Any) -> str:
        url: str = kwargs.get("url", "")
        if not url:
            return "Erro: url é obrigatório."
        if not url.startswith(("http://", "https://")):
            return "Erro: URL deve começar com http:// ou https://"

        max_length: int = kwargs.get("max_length", 100000)
        extra_headers: dict = kwargs.get("headers", {})

        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; Batmam/0.2)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        }
        headers.update(extra_headers)

        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=15) as resp:
                content_type = resp.headers.get("Content-Type", "")
                encoding = "utf-8"
                if "charset=" in content_type:
                    encoding = content_type.split("charset=")[-1].split(";")[0].strip()

                raw = resp.read(max_length + 1000)
                text = raw.decode(encoding, errors="replace")

                if "json" in content_type:
                    return text[:max_length]
                if "text/plain" in content_type:
                    return text[:max_length]
                if "html" in content_type or text.strip().startswith("<"):
                    text = self._html_to_markdown(text)
                if len(text) > max_length:
                    text = text[:max_length] + "\n\n[...truncado]"
                return text

        except HTTPError as e:
            return f"HTTP Error {e.code}: {e.reason}"
        except URLError as e:
            return f"Erro de conexão: {e.reason}"
        except Exception as e:
            return f"Erro: {e}"

    def _html_to_markdown(self, html: str) -> str:
        text = html
        for tag in ["script", "style", "svg", "nav", "footer", "header", "noscript", "iframe"]:
            text = re.sub(rf"<{tag}[^>]*>.*?</{tag}>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)

        for level in range(1, 7):
            text = re.sub(
                rf"<h{level}[^>]*>(.*?)</h{level}>",
                lambda m, l=level: f"\n{'#' * l} {m.group(1).strip()}\n",
                text, flags=re.DOTALL | re.IGNORECASE,
            )

        text = re.sub(r'<a[^>]+href="([^"]*)"[^>]*>(.*?)</a>',
                       lambda m: f"[{m.group(2).strip()}]({m.group(1)})",
                       text, flags=re.DOTALL | re.IGNORECASE)

        text = re.sub(r"<pre[^>]*><code[^>]*>(.*?)</code></pre>",
                       lambda m: f"\n```\n{m.group(1).strip()}\n```\n",
                       text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<pre[^>]*>(.*?)</pre>",
                       lambda m: f"\n```\n{m.group(1).strip()}\n```\n",
                       text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<code[^>]*>(.*?)</code>",
                       lambda m: f"`{m.group(1).strip()}`",
                       text, flags=re.DOTALL | re.IGNORECASE)

        text = re.sub(r"<(?:b|strong)[^>]*>(.*?)</(?:b|strong)>", r"**\1**", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<(?:i|em)[^>]*>(.*?)</(?:i|em)>", r"*\1*", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<li[^>]*>(.*?)</li>", lambda m: f"\n- {m.group(1).strip()}", text, flags=re.DOTALL | re.IGNORECASE)

        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<p[^>]*>", "\n\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</p>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"<hr[^>]*/?>", "\n---\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)

        text = html_module.unescape(text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]+", " ", text)
        lines = [line.strip() for line in text.splitlines()]
        text = "\n".join(lines)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
