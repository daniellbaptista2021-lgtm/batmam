"""Sistema de Tasks do Batmam — rastreia progresso de tarefas."""

from __future__ import annotations
import uuid
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Task:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    title: str = ""
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    dependencies: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    output: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id, "title": self.title, "description": self.description,
            "status": self.status.value, "dependencies": self.dependencies,
            "created_at": self.created_at, "updated_at": self.updated_at,
            "output": self.output,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Task:
        return cls(
            id=d.get("id", uuid.uuid4().hex[:8]),
            title=d.get("title", ""),
            description=d.get("description", ""),
            status=TaskStatus(d.get("status", "pending")),
            dependencies=d.get("dependencies", []),
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
            output=d.get("output", ""),
        )

    def can_start(self, tasks: dict[str, Task]) -> bool:
        """Verifica se todas as dependências foram completadas."""
        for dep_id in self.dependencies:
            dep = tasks.get(dep_id)
            if not dep or dep.status != TaskStatus.COMPLETED:
                return False
        return True


class TaskManager:
    """Gerencia tasks em memória."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}

    def create(self, title: str, description: str = "", dependencies: list[str] | None = None) -> Task:
        task = Task(title=title, description=description, dependencies=dependencies or [])
        self._tasks[task.id] = task
        return task

    def update(self, task_id: str, status: str | None = None, output: str | None = None, title: str | None = None) -> Task | None:
        task = self._tasks.get(task_id)
        if not task:
            return None
        if status:
            task.status = TaskStatus(status)
        if output is not None:
            task.output = output
        if title is not None:
            task.title = title
        task.updated_at = time.time()
        return task

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def list_all(self, status_filter: str | None = None) -> list[Task]:
        tasks = list(self._tasks.values())
        if status_filter:
            tasks = [t for t in tasks if t.status.value == status_filter]
        return sorted(tasks, key=lambda t: t.created_at)

    def get_ready(self) -> list[Task]:
        """Retorna tasks pendentes cujas dependências foram completadas."""
        return [
            t for t in self._tasks.values()
            if t.status == TaskStatus.PENDING and t.can_start(self._tasks)
        ]

    def summary(self) -> str:
        total = len(self._tasks)
        if total == 0:
            return "Nenhuma task."
        counts = {}
        for t in self._tasks.values():
            counts[t.status.value] = counts.get(t.status.value, 0) + 1
        parts = [f"{v} {k}" for k, v in counts.items()]
        return f"{total} tasks: {', '.join(parts)}"


# Instância global
_manager = TaskManager()

def get_task_manager() -> TaskManager:
    return _manager
