"""Modulo Supabase — queries, CRUD e gestao de banco."""
from __future__ import annotations
import requests
import json

TIMEOUT = 30


def _headers(creds: dict) -> dict:
    return {
        "apikey": creds["service_key"],
        "Authorization": f"Bearer {creds['service_key']}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _rest_url(creds: dict) -> str:
    return f"{creds['url'].rstrip('/')}/rest/v1"


def execute_sql(creds: dict, sql: str) -> str:
    """Executa SQL via RPC."""
    url = f"{creds['url'].rstrip('/')}/rest/v1/rpc/exec_sql"
    headers = _headers(creds)

    # Tenta via rpc primeiro, senao usa pg direto
    try:
        r = requests.post(url, headers=headers, json={"query": sql}, timeout=TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            return _format_result(data)
    except Exception:
        pass

    # Fallback: query via PostgREST nao suporta SQL arbitrario
    return "⚠️ SQL arbitrario requer a funcao `exec_sql` no Supabase. Use queries via tabela (ex: 'mostra dados da tabela users')."


def list_tables(creds: dict) -> str:
    """Lista tabelas publicas."""
    url = f"{creds['url'].rstrip('/')}/rest/v1/"
    headers = _headers(creds)
    r = requests.get(url, headers=headers, timeout=TIMEOUT)

    if r.status_code == 200:
        # OpenAPI spec
        try:
            spec = r.json()
            if "paths" in spec:
                tables = [p.strip("/") for p in spec["paths"] if p != "/"]
                if tables:
                    lines = ["## Tabelas no Supabase\n"]
                    for t in sorted(tables):
                        lines.append(f"- `{t}`")
                    return "\n".join(lines)
        except Exception:
            pass

    # Tenta via information_schema
    return "Use `select table_name from information_schema.tables where table_schema='public'` para listar tabelas."


def query_table(creds: dict, table: str, limit: int = 50, filters: str = "") -> str:
    """Query em uma tabela via REST."""
    url = f"{_rest_url(creds)}/{table}?limit={limit}&order=created_at.desc"
    if filters:
        url += f"&{filters}"
    headers = _headers(creds)
    headers["Prefer"] = "count=exact"
    r = requests.get(url, headers=headers, timeout=TIMEOUT)
    r.raise_for_status()

    data = r.json()
    total = r.headers.get("content-range", "")

    return _format_table(table, data, total)


def insert_row(creds: dict, table: str, data: dict) -> str:
    url = f"{_rest_url(creds)}/{table}"
    r = requests.post(url, headers=_headers(creds), json=data, timeout=TIMEOUT)
    r.raise_for_status()
    return f"✅ Registro inserido em `{table}`."


def update_rows(creds: dict, table: str, filters: str, data: dict) -> str:
    url = f"{_rest_url(creds)}/{table}?{filters}"
    r = requests.patch(url, headers=_headers(creds), json=data, timeout=TIMEOUT)
    r.raise_for_status()
    updated = r.json()
    return f"✅ {len(updated)} registro(s) atualizado(s) em `{table}`."


def delete_rows(creds: dict, table: str, filters: str) -> str:
    url = f"{_rest_url(creds)}/{table}?{filters}"
    r = requests.delete(url, headers=_headers(creds), timeout=TIMEOUT)
    r.raise_for_status()
    return f"✅ Registros removidos de `{table}`."


def _format_table(table: str, data: list, total: str = "") -> str:
    if not data:
        return f"Nenhum registro encontrado em `{table}`."

    lines = [f"## {table}"]
    if total:
        lines.append(f"*{total}*\n")

    keys = list(data[0].keys())
    # Limita colunas pra nao estourar
    show_keys = keys[:8]

    lines.append("| " + " | ".join(show_keys) + " |")
    lines.append("| " + " | ".join(["---"] * len(show_keys)) + " |")

    for row in data[:30]:
        vals = [str(row.get(k, ""))[:40] for k in show_keys]
        lines.append("| " + " | ".join(vals) + " |")

    if len(data) > 30:
        lines.append(f"\n*...e mais {len(data)-30} registros*")

    return "\n".join(lines)


def _format_result(data) -> str:
    if isinstance(data, list) and data:
        return _format_table("Resultado", data)
    return f"```json\n{json.dumps(data, indent=2, default=str)[:2000]}\n```"
