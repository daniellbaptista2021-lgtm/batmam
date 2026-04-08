"""Ferramentas de Task para o agente — TaskCreate, TaskUpdate, TaskList, TaskGet."""

from __future__ import annotations
from typing import Any
from .base import BaseTool


class TaskCreateTool(BaseTool):
    name = "task_create"
    description = (
        "Cria uma nova tarefa para rastrear progresso. "
        "Use para planejar trabalho complexo em etapas."
    )
    requires_confirmation = False

    _task_manager: Any = None

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                    "description": "Titulo breve da tarefa.",
                },
                "description": {
                    "type": "string",
                    "description": "O que precisa ser feito.",
                },
                "active_form": {
                    "type": "string",
                    "description": "Forma continua para exibir quando em progresso (ex: 'Rodando testes').",
                },
            },
            "required": ["subject"],
        }

    def execute(self, **kwargs: Any) -> str:
        if not self._task_manager:
            return "[ERROR] TaskManager nao configurado."
        task = self._task_manager.create(
            subject=kwargs.get("subject", ""),
            description=kwargs.get("description", ""),
            active_form=kwargs.get("active_form", ""),
        )
        return f"Task #{task.id} criada: {task.subject}"


class TaskUpdateTool(BaseTool):
    name = "task_update"
    description = (
        "Atualiza status de uma tarefa. "
        "Marque como in_progress ao iniciar e completed ao terminar."
    )
    requires_confirmation = False

    _task_manager: Any = None

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "ID da tarefa.",
                },
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "completed", "deleted"],
                    "description": "Novo status.",
                },
                "subject": {
                    "type": "string",
                    "description": "Novo titulo (opcional).",
                },
                "description": {
                    "type": "string",
                    "description": "Nova descricao (opcional).",
                },
            },
            "required": ["task_id"],
        }

    def execute(self, **kwargs: Any) -> str:
        if not self._task_manager:
            return "[ERROR] TaskManager nao configurado."

        from ..tasks import TaskStatus
        task_id = kwargs.get("task_id", "")
        status_str = kwargs.get("status")
        status = TaskStatus(status_str) if status_str else None

        task = self._task_manager.update(
            task_id=task_id,
            status=status,
            subject=kwargs.get("subject"),
            description=kwargs.get("description"),
        )
        if not task:
            return f"[ERROR] Task #{task_id} nao encontrada."
        return f"Task #{task.id} atualizada: {task.status.value} — {task.subject}"


class TaskListTool(BaseTool):
    name = "task_list"
    description = "Lista todas as tarefas e seu status."
    requires_confirmation = False

    _task_manager: Any = None

    def get_schema(self) -> dict:
        return {"type": "object", "properties": {}}

    def execute(self, **kwargs: Any) -> str:
        if not self._task_manager:
            return "[ERROR] TaskManager nao configurado."
        return self._task_manager.summary()


class TaskGetTool(BaseTool):
    name = "task_get"
    description = "Obtem detalhes de uma tarefa especifica."
    requires_confirmation = False

    _task_manager: Any = None

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "ID da tarefa.",
                },
            },
            "required": ["task_id"],
        }

    def execute(self, **kwargs: Any) -> str:
        if not self._task_manager:
            return "[ERROR] TaskManager nao configurado."
        task = self._task_manager.get(kwargs.get("task_id", ""))
        if not task:
            return "[ERROR] Task nao encontrada."
        lines = [
            f"#{task.id} [{task.status.value}] {task.subject}",
            f"  Descricao: {task.description}" if task.description else "",
            f"  Owner: {task.owner}" if task.owner else "",
            f"  Blocked by: {', '.join(task.blocked_by)}" if task.blocked_by else "",
            f"  Blocks: {', '.join(task.blocks)}" if task.blocks else "",
        ]
        return "\n".join(l for l in lines if l)
