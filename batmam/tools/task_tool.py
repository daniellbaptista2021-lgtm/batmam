"""Ferramentas de Task — create, update, list, get."""

from __future__ import annotations
from typing import Any
from .base import BaseTool
from ..tasks import get_task_manager, TaskStatus


class TaskCreateTool(BaseTool):
    name = "task_create"
    description = (
        "Cria uma nova task para rastrear progresso. "
        "Use para quebrar trabalho complexo em etapas."
    )
    requires_confirmation = False

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Título curto da task.",
                },
                "description": {
                    "type": "string",
                    "description": "Descrição detalhada (opcional).",
                },
                "dependencies": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lista de IDs de tasks que devem ser completadas primeiro.",
                },
            },
            "required": ["title"],
        }

    def execute(self, **kwargs: Any) -> str:
        title = kwargs.get("title", "")
        description = kwargs.get("description", "")
        dependencies = kwargs.get("dependencies", [])

        if not title:
            return "[ERROR] title é obrigatório."

        manager = get_task_manager()
        task = manager.create(title=title, description=description, dependencies=dependencies)
        return f"Task criada: [{task.id}] {task.title} (status: {task.status.value})"


class TaskUpdateTool(BaseTool):
    name = "task_update"
    description = (
        "Atualiza o status ou output de uma task existente. "
        "Use para marcar tasks como in_progress, completed ou failed."
    )
    requires_confirmation = False

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "ID da task a atualizar.",
                },
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "completed", "failed"],
                    "description": "Novo status da task.",
                },
                "output": {
                    "type": "string",
                    "description": "Output/resultado da task (opcional).",
                },
            },
            "required": ["task_id"],
        }

    def execute(self, **kwargs: Any) -> str:
        task_id = kwargs.get("task_id", "")
        status = kwargs.get("status")
        output = kwargs.get("output")

        if not task_id:
            return "[ERROR] task_id é obrigatório."

        manager = get_task_manager()
        task = manager.update(task_id, status=status, output=output)
        if not task:
            return f"[ERROR] Task '{task_id}' não encontrada."
        return f"Task atualizada: [{task.id}] {task.title} → {task.status.value}"


class TaskListTool(BaseTool):
    name = "task_list"
    description = (
        "Lista todas as tasks. Opcionalmente filtra por status."
    )
    requires_confirmation = False

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "completed", "failed"],
                    "description": "Filtrar por status (opcional).",
                },
            },
        }

    def execute(self, **kwargs: Any) -> str:
        status_filter = kwargs.get("status")
        manager = get_task_manager()
        tasks = manager.list_all(status_filter=status_filter)

        if not tasks:
            return "Nenhuma task encontrada."

        lines = [f"Tasks ({len(tasks)}):"]
        status_icons = {"pending": "○", "in_progress": "◑", "completed": "●", "failed": "✗"}
        for t in tasks:
            icon = status_icons.get(t.status.value, "?")
            deps = f" [deps: {','.join(t.dependencies)}]" if t.dependencies else ""
            lines.append(f"  {icon} [{t.id}] {t.title} ({t.status.value}){deps}")

        lines.append(f"\n{manager.summary()}")
        return "\n".join(lines)


class TaskGetTool(BaseTool):
    name = "task_get"
    description = "Obtém detalhes de uma task específica por ID."
    requires_confirmation = False

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "ID da task.",
                },
            },
            "required": ["task_id"],
        }

    def execute(self, **kwargs: Any) -> str:
        task_id = kwargs.get("task_id", "")
        if not task_id:
            return "[ERROR] task_id é obrigatório."

        manager = get_task_manager()
        task = manager.get(task_id)
        if not task:
            return f"[ERROR] Task '{task_id}' não encontrada."

        import time as _time
        created = _time.strftime("%d/%m %H:%M", _time.localtime(task.created_at))
        updated = _time.strftime("%d/%m %H:%M", _time.localtime(task.updated_at))

        lines = [
            f"Task: {task.title}",
            f"  ID: {task.id}",
            f"  Status: {task.status.value}",
            f"  Criada: {created}",
            f"  Atualizada: {updated}",
        ]
        if task.description:
            lines.append(f"  Descrição: {task.description}")
        if task.dependencies:
            lines.append(f"  Dependências: {', '.join(task.dependencies)}")
        if task.output:
            lines.append(f"  Output: {task.output[:300]}")
        return "\n".join(lines)
