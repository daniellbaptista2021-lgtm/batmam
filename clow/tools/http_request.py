"""HTTP Request Tool — requisições HTTP genéricas."""

from __future__ import annotations
import json
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from typing import Any
from .base import BaseTool


class HttpRequestTool(BaseTool):
    name = "http_request"
    description = "Faz requisições HTTP genéricas (GET, POST, PUT, DELETE). Útil para integrar com qualquer API externa."
    requires_confirmation = True

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL da requisição"},
                "method": {
                    "type": "string",
                    "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"],
                    "description": "Método HTTP (padrão: GET)",
                },
                "headers": {
                    "type": "object",
                    "description": "Headers HTTP",
                    "additionalProperties": {"type": "string"},
                },
                "body": {"type": "string", "description": "Body da requisição (JSON string)"},
                "auth_token": {"type": "string", "description": "Bearer token para Authorization header"},
                "timeout": {"type": "integer", "description": "Timeout em segundos (padrão: 30)"},
            },
            "required": ["url"],
        }

    def execute(self, **kwargs: Any) -> str:
        url = kwargs.get("url", "")
        if not url:
            return "Erro: url é obrigatório."
        if not url.startswith(("http://", "https://")):
            return "Erro: URL deve começar com http:// ou https://"

        method = kwargs.get("method", "GET").upper()
        headers = dict(kwargs.get("headers", {}))
        body = kwargs.get("body", "")
        auth_token = kwargs.get("auth_token", "")
        timeout = kwargs.get("timeout", 30)

        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        if body and "Content-Type" not in headers:
            headers["Content-Type"] = "application/json"

        try:
            data = body.encode() if body else None
            req = Request(url, data=data, headers=headers, method=method)
            resp = urlopen(req, timeout=timeout)

            status = resp.status
            resp_headers = dict(resp.headers)
            content = resp.read().decode("utf-8", errors="replace")

            # Tenta formatar JSON
            try:
                parsed = json.loads(content)
                content = json.dumps(parsed, indent=2, ensure_ascii=False)
            except (json.JSONDecodeError, ValueError):
                pass

            # Trunca respostas muito grandes
            if len(content) > 10000:
                content = content[:10000] + "\n... (truncado)"

            return f"HTTP {status} {method} {url}\n\n{content}"

        except HTTPError as e:
            body_text = ""
            try:
                body_text = e.read().decode("utf-8", errors="replace")[:2000]
            except Exception:
                pass
            return f"HTTP {e.code} {method} {url}\n{e.reason}\n{body_text}"

        except URLError as e:
            return f"Erro de conexão: {e.reason}"
        except Exception as e:
            return f"Erro: {e}"
