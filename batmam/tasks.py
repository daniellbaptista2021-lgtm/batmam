"""Sistema de Tasks (TODO tracking) do Batmam.

Permite ao agente criar, atualizar e gerenciar tarefas durante a execução.
Similar ao TaskCreate/TaskUpdate/TaskList do Claude Code.
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    DELETED = "deleted"


@dataclass
class Task:
    """Uma tarefa do agente."""
    id: str
    subject: str
    description: str = ""
    active_form: str = ""  # Texto para spinner quando in_progress
    status: TaskStatus = TaskStatus.PENDING
    owner: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    blocked_by: list[str] = field(default_factory=list)
    blocks: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class TaskManager:
    """Gerencia tarefas durante a sessao do agente."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._counter = 0

    def create(
        self,
        subject: str,
        description: str = "",
        active_form: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> Task:
        """Cria uma nova tarefa."""
        self._counter += 1
        task_id = str(self._counter)
        task = Task(
            id=task_id,
            subject=subject,
            description=description,
            active_form=active_form or subject,
            metadata=metadata or {},
        )
        self._tasks[task_id] = task
        return task

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def update(
        self,
        task_id: str,
        status: TaskStatus | None = None,
        subject: str | None = None,
        description: str | None = None,
        active_form: str | None = None,
        owner: str | None = None,
        metadata: dict[str, Any] | None = None,
        add_blocks: list[str] | None = None,
        add_blocked_by: list[str] | None = None,
    ) -> Task | None:
        """Atualiza uma tarefa existente."""
        task = self._tasks.get(task_id)
        if not task:
            return None

        if status == TaskStatus.DELETED:
            del self._tasks[task_id]
            return task

        if status is not None:
            task.status = status
        if subject is not None:
            task.subject = subject
        if description is not None:
            task.description = description
        if active_form is not None:
            task.active_form = active_form
        if owner is not None:
            task.owner = owner
        if metadata is not None:
            for k, v in metadata.items():
                if v is None:
                    task.metadata.pop(k, None)
                else:
                    task.metadata[k] = v
        if add_blocks:
            task.blocks.extend(b for b in add_blocks if b not in task.blocks)
        if add_blocked_by:
            task.blocked_by.extend(b for b in add_blocked_by if b not in task.blocked_by)

        task.updated_at = time.time()
        return task

    def list_all(self) -> list[Task]:
        """Lista todas as tarefas (exceto deletadas)."""
        return [t for t in self._tasks.values() if t.status != TaskStatus.DELETED]

    def list_pending(self) -> list[Task]:
        """Lista tarefas pendentes nao bloqueadas."""
        result = []
        for task in self._tasks.values():
            if task.status != TaskStatus.PENDING:
                continue
            # Verifica se esta bloqueada
            blocked = False
            for dep_id in task.blocked_by:
                dep = self._tasks.get(dep_id)
                if dep and dep.status != TaskStatus.COMPLETED:
                    blocked = True
                    break
            if not blocked:
                result.append(task)
        return result

    def summary(self) -> str:
        """Retorna resumo formatado das tarefas."""
        tasks = self.list_all()
        if not tasks:
            return "Nenhuma tarefa."

        lines = []
        for t in tasks:
            icon = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}.get(
                t.status.value, "[ ]"
            )
            blocked = ""
            if t.blocked_by:
                open_deps = [
                    b for b in t.blocked_by
                    if (d := self._tasks.get(b)) and d.status != TaskStatus.COMPLETED
                ]
                if open_deps:
                    blocked = f" (blocked by: {', '.join(open_deps)})"
            owner = f" @{t.owner}" if t.owner else ""
            lines.append(f"#{t.id} {icon} {t.subject}{owner}{blocked}")

        return "\n".join(lines)
