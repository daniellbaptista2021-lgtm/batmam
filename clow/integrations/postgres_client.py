"""Modulo PostgreSQL — queries e gestao de banco."""
from __future__ import annotations
import json

TIMEOUT = 30


def _connect(creds: dict):
    import psycopg2
    return psycopg2.connect(
        host=creds.get("host", "localhost"),
        port=int(creds.get("port", 5432)),
        user=creds.get("user", "postgres"),
        password=creds.get("password", ""),
        dbname=creds.get("database", "postgres"),
        connect_timeout=TIMEOUT,
    )


def execute_sql(creds: dict, sql: str) -> str:
    conn = _connect(creds)
    try:
        cur = conn.cursor()
        cur.execute(sql)

        if cur.description:
            cols = [d[0] for d in cur.description]
            rows = cur.fetchmany(100)
            return _format_table(cols, rows, cur.rowcount)
        else:
            conn.commit()
            return f"✅ Query executada. {cur.rowcount} linha(s) afetada(s)."
    finally:
        conn.close()


def list_tables(creds: dict) -> str:
    sql = "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name"
    return execute_sql(creds, sql)


def list_databases(creds: dict) -> str:
    sql = "SELECT datname FROM pg_database WHERE datistemplate=false ORDER BY datname"
    return execute_sql(creds, sql)


def table_info(creds: dict, table: str) -> str:
    sql = f"SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_name='{table}' ORDER BY ordinal_position"
    return execute_sql(creds, sql)


def row_count(creds: dict, table: str) -> str:
    sql = f"SELECT count(*) as total FROM {table}"
    return execute_sql(creds, sql)


def _format_table(cols: list, rows: list, total: int) -> str:
    if not rows:
        return "Nenhum resultado."

    show_cols = cols[:10]
    lines = [
        "| " + " | ".join(show_cols) + " |",
        "| " + " | ".join(["---"] * len(show_cols)) + " |",
    ]
    for row in rows[:50]:
        vals = [str(v)[:50] if v is not None else "NULL" for v in row[:10]]
        lines.append("| " + " | ".join(vals) + " |")

    if total > 50:
        lines.append(f"\n*Total: {total} linhas (mostrando 50)*")

    return "\n".join(lines)
