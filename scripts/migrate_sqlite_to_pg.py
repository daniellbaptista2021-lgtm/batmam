#!/usr/bin/env python3
"""Migra dados do SQLite para PostgreSQL.

Uso: CLOW_DB_BACKEND=postgres python3 scripts/migrate_sqlite_to_pg.py

Pré-requisitos:
  - PostgreSQL rodando e acessível via DATABASE_URL
  - Schema já criado (roda migrations automaticamente)
  - SQLite com dados em data/clow.db
"""
import os
import sys
import sqlite3
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Force postgres backend
os.environ["CLOW_DB_BACKEND"] = "postgres"

from clow.db_postgres import get_db as pg_get_db
from clow.migrations_pg import run_pg_migrations

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "clow.db"

TABLES = [
    "users",
    "usage_log",
    "conversations",
    "messages",
    "missions",
    "mission_steps",
    "leads",
    "lead_activities",
    "email_campaigns",
    "email_sends",
    "appointments",
    "scheduling_links",
    "whatsapp_connections",
    "bot_configs",
    "wa_message_logs",
    "web_sessions",
]


def migrate():
    if not DB_PATH.exists():
        print(f"SQLite database not found: {DB_PATH}")
        sys.exit(1)

    # 1. Run PG migrations first
    print("Aplicando schema PostgreSQL...")
    run_pg_migrations()

    # 2. Connect to SQLite
    sqlite_conn = sqlite3.connect(str(DB_PATH))
    sqlite_conn.row_factory = sqlite3.Row

    total_rows = 0

    for table in TABLES:
        try:
            rows = sqlite_conn.execute(f"SELECT * FROM {table}").fetchall()
        except sqlite3.OperationalError:
            print(f"  SKIP {table} (tabela nao existe no SQLite)")
            continue

        if not rows:
            print(f"  SKIP {table} (vazia)")
            continue

        cols = rows[0].keys()
        placeholders = ", ".join(["%s"] * len(cols))
        col_names = ", ".join(cols)
        insert_sql = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"

        inserted = 0
        with pg_get_db() as pg:
            for row in rows:
                try:
                    pg.execute(insert_sql, tuple(row))
                    inserted += 1
                except Exception as e:
                    if "duplicate" not in str(e).lower() and "conflict" not in str(e).lower():
                        print(f"    WARN: {table} row error: {str(e)[:100]}")

        total_rows += inserted
        print(f"  OK {table}: {inserted}/{len(rows)} linhas migradas")

    sqlite_conn.close()
    print(f"\nMigracao concluida: {total_rows} linhas no total")
    print("Para ativar PostgreSQL, adicione ao .env:")
    print("  CLOW_DB_BACKEND=postgres")
    print("  DATABASE_URL=postgresql://chatwoot:ChAtW00t_PV_2026@localhost:5432/clow_app")


if __name__ == "__main__":
    migrate()
