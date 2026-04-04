"""Agent Teams — agentes persistentes com task board e message bus.

Diferente do Swarm (paralelo bruto), Teams sao agentes com roles definidos
que compartilham um task board e se comunicam via message bus.
"""

from __future__ import annotations
import json
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import config
from .logging import log_action

TEAMS_DB = config.CLOW_HOME / "teams.db"
ROLES_DIR = Path(".clow") / "team"

# Roles default
DEFAULT_ROLES = {
    "architect": {
        "name": "Architect",
        "description": "Planeja a arquitetura e decompoe tasks em subtasks tecnicas.",
        "tools": ["read", "glob", "grep", "web_search", "task_create", "task_update"],
        "model": "default",
        "trigger": "new_task",
    },
    "developer": {
        "name": "Developer",
        "description": "Implementa codigo, cria arquivos, executa comandos.",
        "tools": ["read", "write", "edit", "bash", "glob", "grep"],
        "model": "default",
        "trigger": "new_task",
    },
    "tester": {
        "name": "Tester",
        "description": "Escreve e executa testes, valida implementacoes.",
        "tools": ["read", "bash", "glob", "grep", "write"],
        "model": "default",
        "trigger": "task_completed",
    },
    "reviewer": {
        "name": "Reviewer",
        "description": "Revisa codigo, identifica bugs, sugere melhorias.",
        "tools": ["read", "glob", "grep"],
        "model": "default",
        "trigger": "task_review_requested",
    },
}


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(TEAMS_DB), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS team_tasks (
            id TEXT PRIMARY KEY,
            team_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            assigned_role TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'todo',
            result TEXT DEFAULT '',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            completed_at REAL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS team_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_id TEXT NOT NULL,
            from_role TEXT NOT NULL,
            to_role TEXT DEFAULT '',
            message TEXT NOT NULL,
            timestamp REAL NOT NULL
        )
    """)
    conn.commit()
    return conn


@dataclass
class TeamAgent:
    """Um agente membro do time."""
    role: str
    name: str
    description: str
    tools: list[str] = field(default_factory=list)
    model: str = "default"
    trigger: str = "new_task"
    status: str = "idle"  # idle, working, done
    current_task_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "name": self.name,
            "description": self.description,
            "tools": self.tools,
            "trigger": self.trigger,
            "status": self.status,
            "current_task_id": self.current_task_id,
        }


class TeamCoordinator:
    """Coordena um time de agentes com task board compartilhado."""

    def __init__(self, cwd: str | None = None, on_progress: Callable[[str], None] | None = None):
        self.cwd = cwd or os.getcwd()
        self.team_id = uuid.uuid4().hex[:8]
        self.agents: dict[str, TeamAgent] = {}
        self.on_progress = on_progress or (lambda msg: None)
        self._lock = threading.Lock()
        self._stop = threading.Event()

        # Carrega roles
        self._load_roles()

    def _load_roles(self) -> None:
        """Carrega roles de .clow/team/*.md ou usa defaults."""
        roles_path = Path(self.cwd) / ROLES_DIR
        loaded = {}

        if roles_path.exists():
            for md_file in roles_path.glob("*.md"):
                role_data = self._parse_role_md(md_file)
                if role_data:
                    loaded[md_file.stem] = role_data

        # Merge com defaults
        all_roles = {**DEFAULT_ROLES, **loaded}

        for role_key, role_config in all_roles.items():
            if len(self.agents) >= config.CLOW_TEAM_MAX_AGENTS:
                break
            self.agents[role_key] = TeamAgent(
                role=role_key,
                name=role_config.get("name", role_key.title()),
                description=role_config.get("description", ""),
                tools=role_config.get("tools", []),
                model=role_config.get("model", "default"),
                trigger=role_config.get("trigger", "new_task"),
            )

    @staticmethod
    def _parse_role_md(filepath: Path) -> dict | None:
        """Parse um arquivo .md de role."""
        try:
            content = filepath.read_text(encoding="utf-8")
            role: dict[str, Any] = {"name": filepath.stem.title()}

            for line in content.splitlines():
                line = line.strip()
                if line.startswith("# "):
                    role["name"] = line[2:].strip()
                elif line.lower().startswith("description:"):
                    role["description"] = line.split(":", 1)[1].strip()
                elif line.lower().startswith("tools:"):
                    role["tools"] = [t.strip() for t in line.split(":", 1)[1].split(",")]
                elif line.lower().startswith("model:"):
                    role["model"] = line.split(":", 1)[1].strip()
                elif line.lower().startswith("trigger:"):
                    role["trigger"] = line.split(":", 1)[1].strip()

            return role if "description" in role else None
        except Exception:
            return None

    def run(self, task: str) -> dict[str, Any]:
        """Executa o time com uma task principal."""
        log_action("team_start", f"task={task[:80]}", session_id=self.team_id)
        self.on_progress(f"[Team {self.team_id}] Decompondo task...")

        # 1. Architect decompoe task
        subtasks = self._decompose_task(task)
        self.on_progress(f"[Team] {len(subtasks)} subtasks criadas")

        # 2. Adiciona subtasks ao board
        for st in subtasks:
            self._add_task(st["title"], st.get("description", ""), st.get("role", "developer"))

        # 3. Executa agentes (sequencial por simplicidade)
        self.on_progress("[Team] Agentes trabalhando...")
        self._run_agents()

        # 4. Coleta resultados
        board = self.get_board()
        messages = self.get_messages()

        log_action("team_done", f"tasks={len(board)}", session_id=self.team_id)

        return {
            "success": True,
            "team_id": self.team_id,
            "agents": {k: v.to_dict() for k, v in self.agents.items()},
            "board": board,
            "messages": messages[-20:],
        }

    def _decompose_task(self, task: str) -> list[dict]:
        """Usa LLM pra decompor task em subtasks com roles."""
        try:
            if config.CLOW_PROVIDER == "anthropic":
                from anthropic import Anthropic
                client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
                roles_desc = ", ".join(f"{k}: {v.description}" for k, v in self.agents.items())
                response = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    system=(
                        f"Decompoe tasks em subtasks para um time com roles: {roles_desc}. "
                        "Retorne JSON array com objetos: {{\"title\": str, \"description\": str, \"role\": str}}. "
                        "Max 6 subtasks. Somente o JSON."
                    ),
                    messages=[{"role": "user", "content": task}],
                    max_tokens=1000,
                )
                raw = response.content[0].text.strip()
                if raw.startswith("```"):
                    raw = raw.split("```")[1].lstrip("json\n")
                return json.loads(raw)[:6]
            return [{"title": task, "description": "", "role": "developer"}]
        except Exception:
            return [{"title": task, "description": "", "role": "developer"}]

    def _add_task(self, title: str, description: str, role: str) -> str:
        task_id = uuid.uuid4().hex[:8]
        db = _get_db()
        db.execute(
            "INSERT INTO team_tasks (id, team_id, title, description, assigned_role, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (task_id, self.team_id, title, description, role, "todo", time.time(), time.time()),
        )
        db.commit()
        db.close()
        return task_id

    def _update_task(self, task_id: str, status: str, result: str = "") -> None:
        db = _get_db()
        db.execute(
            "UPDATE team_tasks SET status=?, result=?, updated_at=?, completed_at=? WHERE id=?",
            (status, result, time.time(), time.time() if status == "done" else 0, task_id),
        )
        db.commit()
        db.close()

    def send_message(self, from_role: str, to_role: str, message: str) -> None:
        db = _get_db()
        db.execute(
            "INSERT INTO team_messages (team_id, from_role, to_role, message, timestamp) VALUES (?,?,?,?,?)",
            (self.team_id, from_role, to_role, message, time.time()),
        )
        db.commit()
        db.close()

    def get_board(self) -> list[dict]:
        db = _get_db()
        rows = db.execute(
            "SELECT * FROM team_tasks WHERE team_id=? ORDER BY created_at", (self.team_id,)
        ).fetchall()
        db.close()
        return [dict(r) for r in rows]

    def get_messages(self, limit: int = 50) -> list[dict]:
        db = _get_db()
        rows = db.execute(
            "SELECT * FROM team_messages WHERE team_id=? ORDER BY timestamp DESC LIMIT ?",
            (self.team_id, limit),
        ).fetchall()
        db.close()
        return [dict(r) for r in rows]

    def _run_agents(self) -> None:
        """Executa agentes sequencialmente baseado em triggers."""
        from .agent import Agent

        db = _get_db()
        tasks = db.execute(
            "SELECT * FROM team_tasks WHERE team_id=? AND status='todo' ORDER BY created_at",
            (self.team_id,),
        ).fetchall()
        db.close()

        for task_row in tasks:
            task_dict = dict(task_row)
            role = task_dict["assigned_role"]
            agent_def = self.agents.get(role)

            if not agent_def:
                agent_def = self.agents.get("developer", list(self.agents.values())[0])

            agent_def.status = "working"
            agent_def.current_task_id = task_dict["id"]
            self._update_task(task_dict["id"], "in_progress")

            self.on_progress(f"  [{agent_def.name}] {task_dict['title'][:60]}...")
            self.send_message(role, "coordinator", f"Iniciando: {task_dict['title']}")

            try:
                agent = Agent(
                    cwd=self.cwd,
                    auto_approve=True,
                    is_subagent=True,
                )
                result = agent.run_turn(
                    f"Voce e o {agent_def.name} ({agent_def.description}). "
                    f"Execute esta task: {task_dict['title']}\n{task_dict['description']}"
                )

                self._update_task(task_dict["id"], "done", result[:1000])
                self.send_message(role, "coordinator", f"Concluido: {task_dict['title']}")
                agent_def.status = "idle"

            except Exception as e:
                self._update_task(task_dict["id"], "todo", f"Erro: {e}")
                self.send_message(role, "coordinator", f"Erro em {task_dict['title']}: {e}")
                agent_def.status = "idle"

    def status_summary(self) -> str:
        """Gera resumo do status do time para display."""
        board = self.get_board()
        by_status: dict[str, int] = {}
        for t in board:
            by_status[t["status"]] = by_status.get(t["status"], 0) + 1

        agents_info = []
        for a in self.agents.values():
            agents_info.append(f"  {a.name} ({a.role}): {a.status}")

        lines = [
            f"=== Team {self.team_id} ===",
            f"Tasks: {len(board)} total",
        ]
        for s, c in by_status.items():
            lines.append(f"  {s}: {c}")
        lines.append("Agentes:")
        lines.extend(agents_info)

        return "\n".join(lines)
