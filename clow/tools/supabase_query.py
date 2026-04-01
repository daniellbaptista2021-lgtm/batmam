"""Supabase Query Tool — executa queries SQL via API REST do Supabase/Postgres."""

from __future__ import annotations
import json
import os
from urllib.request import urlopen, Request
from urllib.error import URLError
from typing import Any
from .base import BaseTool


class SupabaseQueryTool(BaseTool):
    name = "supabase_query"
    description = "Executa queries SQL no Supabase/Postgres via API REST. Retorna resultados formatados."
    requires_confirmation = True

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Query SQL para executar"},
                "supabase_url": {"type": "string", "description": "URL do projeto Supabase (ou usa env SUPABASE_URL)"},
                "supabase_key": {"type": "string", "description": "Service role key (ou usa env SUPABASE_SERVICE_KEY)"},
            },
            "required": ["query"],
        }

    def execute(self, **kwargs: Any) -> str:
        query = kwargs.get("query", "").strip()
        if not query:
            return "Erro: query SQL é obrigatória."

        supabase_url = kwargs.get("supabase_url") or os.getenv("SUPABASE_URL", "")
        supabase_key = kwargs.get("supabase_key") or os.getenv("SUPABASE_SERVICE_KEY", "")

        if not supabase_url or not supabase_key:
            return "Erro: SUPABASE_URL e SUPABASE_SERVICE_KEY são obrigatórios. Configure no .env"

        url = f"{supabase_url.rstrip('/')}/rest/v1/rpc/execute_sql"

        # Tenta via RPC primeiro, fallback para postgrest
        try:
            payload = json.dumps({"query": query}).encode()
            req = Request(
                url,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "apikey": supabase_key,
                    "Authorization": f"Bearer {supabase_key}",
                    "Prefer": "return=representation",
                },
                method="POST",
            )
            resp = urlopen(req, timeout=30)
            result = json.loads(resp.read().decode())

            if isinstance(result, list) and result:
                return self._format_table(result)
            elif isinstance(result, dict):
                return json.dumps(result, indent=2, ensure_ascii=False)
            return f"Query executada. Resultado: {result}"

        except URLError as e:
            return f"Erro na query Supabase: {e}"
        except Exception as e:
            return f"Erro: {e}"

    @staticmethod
    def _format_table(rows: list[dict]) -> str:
        """Formata resultado como tabela markdown."""
        if not rows:
            return "(vazio)"

        headers = list(rows[0].keys())
        lines = ["| " + " | ".join(headers) + " |"]
        lines.append("| " + " | ".join("---" for _ in headers) + " |")

        for row in rows[:100]:
            cells = [str(row.get(h, ""))[:50] for h in headers]
            lines.append("| " + " | ".join(cells) + " |")

        if len(rows) > 100:
            lines.append(f"\n... +{len(rows) - 100} linhas")

        return "\n".join(lines)
