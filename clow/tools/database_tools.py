"""Database Tools — Postgres, MySQL, Redis direto via CLI/lib."""

from __future__ import annotations
import subprocess
import json
from typing import Any
from .base import BaseTool


class QueryPostgresTool(BaseTool):
    name = "query_postgres"
    description = "Executa SQL no PostgreSQL local ou remoto via psql. SELECT, INSERT, UPDATE, DDL."
    requires_confirmation = True

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "Query SQL a executar"},
                "database": {"type": "string", "description": "Nome do banco (padrao: postgres)"},
                "host": {"type": "string", "description": "Host do Postgres (padrao: localhost)"},
                "port": {"type": "integer", "description": "Porta (padrao: 5432)"},
                "user": {"type": "string", "description": "Usuario (padrao: postgres)"},
                "password": {"type": "string", "description": "Senha"},
            },
            "required": ["sql"],
        }

    def execute(self, **kwargs: Any) -> str:
        sql = kwargs["sql"]
        db = kwargs.get("database", "postgres")
        host = kwargs.get("host", "localhost")
        port = kwargs.get("port", 5432)
        user = kwargs.get("user", "postgres")
        password = kwargs.get("password", "")

        env = {}
        if password:
            env["PGPASSWORD"] = password

        cmd = f'psql -h {host} -p {port} -U {user} -d {db} -c "{sql}" --no-psqlrc'
        try:
            import os
            full_env = {**os.environ, **env}
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30, env=full_env)
            return (r.stdout + r.stderr)[:5000] or "Query executada."
        except Exception as e:
            return f"Erro Postgres: {e}"


class QueryMysqlTool(BaseTool):
    name = "query_mysql"
    description = "Executa SQL no MySQL/MariaDB via mysql CLI."
    requires_confirmation = True

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "Query SQL a executar"},
                "database": {"type": "string", "description": "Nome do banco"},
                "host": {"type": "string", "description": "Host (padrao: localhost)"},
                "port": {"type": "integer", "description": "Porta (padrao: 3306)"},
                "user": {"type": "string", "description": "Usuario (padrao: root)"},
                "password": {"type": "string", "description": "Senha"},
            },
            "required": ["sql"],
        }

    def execute(self, **kwargs: Any) -> str:
        sql = kwargs["sql"]
        db = kwargs.get("database", "")
        host = kwargs.get("host", "localhost")
        port = kwargs.get("port", 3306)
        user = kwargs.get("user", "root")
        password = kwargs.get("password", "")

        parts = [f"mysql -h {host} -P {port} -u {user}"]
        if password:
            parts.append(f"-p'{password}'")
        if db:
            parts.append(db)
        parts.append(f'-e "{sql}"')
        cmd = " ".join(parts)

        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            return (r.stdout + r.stderr)[:5000] or "Query executada."
        except Exception as e:
            return f"Erro MySQL: {e}"


class QueryRedisTool(BaseTool):
    name = "query_redis"
    description = "Executa comandos Redis via redis-cli. GET, SET, DEL, KEYS, INFO, etc."

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Comando Redis (ex: 'GET mykey', 'KEYS *', 'INFO memory')"},
                "host": {"type": "string", "description": "Host (padrao: localhost)"},
                "port": {"type": "integer", "description": "Porta (padrao: 6379)"},
                "password": {"type": "string", "description": "Senha Redis"},
                "db": {"type": "integer", "description": "Numero do database (padrao: 0)"},
            },
            "required": ["command"],
        }

    def execute(self, **kwargs: Any) -> str:
        command = kwargs["command"]
        host = kwargs.get("host", "localhost")
        port = kwargs.get("port", 6379)
        password = kwargs.get("password", "")
        db = kwargs.get("db", 0)

        parts = [f"redis-cli -h {host} -p {port} -n {db}"]
        if password:
            parts.append(f"-a '{password}'")
        parts.append(command)
        cmd = " ".join(parts)

        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            return (r.stdout + r.stderr)[:3000] or "OK"
        except Exception as e:
            return f"Erro Redis: {e}"


class ManageMigrationsTool(BaseTool):
    name = "manage_migrations"
    description = "Cria e executa migrations de banco. Suporta SQL puro, Alembic, Django, Prisma."
    requires_confirmation = True

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "run", "rollback", "status", "list"],
                    "description": "Acao de migration",
                },
                "name": {"type": "string", "description": "Nome da migration (para create)"},
                "framework": {
                    "type": "string",
                    "enum": ["sql", "alembic", "django", "prisma"],
                    "description": "Framework de migration (padrao: sql)",
                },
                "sql": {"type": "string", "description": "SQL da migration (para framework=sql)"},
                "cwd": {"type": "string", "description": "Diretorio do projeto"},
            },
            "required": ["action"],
        }

    def execute(self, **kwargs: Any) -> str:
        action = kwargs["action"]
        name = kwargs.get("name", "")
        framework = kwargs.get("framework", "sql")
        sql = kwargs.get("sql", "")
        cwd = kwargs.get("cwd", None)

        commands = {
            ("alembic", "create"): f"alembic revision --autogenerate -m '{name}'",
            ("alembic", "run"): "alembic upgrade head",
            ("alembic", "rollback"): "alembic downgrade -1",
            ("alembic", "status"): "alembic current",
            ("alembic", "list"): "alembic history --verbose",
            ("django", "create"): f"python manage.py makemigrations {name}".strip(),
            ("django", "run"): "python manage.py migrate",
            ("django", "rollback"): f"python manage.py migrate {name} zero" if name else "echo 'name obrigatorio'",
            ("django", "status"): "python manage.py showmigrations",
            ("django", "list"): "python manage.py showmigrations",
            ("prisma", "create"): f"npx prisma migrate dev --name {name}" if name else "echo 'name obrigatorio'",
            ("prisma", "run"): "npx prisma migrate deploy",
            ("prisma", "status"): "npx prisma migrate status",
            ("prisma", "list"): "ls -la prisma/migrations/ 2>/dev/null || echo 'Sem migrations'",
        }

        if framework == "sql" and action == "create":
            if not sql:
                return "Erro: sql obrigatorio para migration SQL pura."
            import time, os
            ts = time.strftime("%Y%m%d%H%M%S")
            mdir = os.path.join(cwd or ".", "migrations")
            os.makedirs(mdir, exist_ok=True)
            fname = f"{ts}_{name or 'migration'}.sql"
            path = os.path.join(mdir, fname)
            with open(path, "w") as f:
                f.write(sql)
            return f"Migration criada: {path}"

        cmd = commands.get((framework, action))
        if not cmd:
            return f"Combinacao '{framework}/{action}' nao suportada."

        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60, cwd=cwd)
            return (r.stdout + r.stderr)[:5000] or "OK"
        except Exception as e:
            return f"Erro: {e}"
