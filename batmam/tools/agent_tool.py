"""Ferramenta Agent — lança sub-agentes para tarefas complexas."""

from __future__ import annotations
from typing import Any
from .base import BaseTool


class AgentTool(BaseTool):
    name = "agent"
    description = (
        "Lança um sub-agente para realizar tarefas complexas em paralelo. "
        "O sub-agente tem acesso a todas as mesmas ferramentas. "
        "Use para pesquisas, análises ou tarefas independentes."
    )
    requires_confirmation = False

    # Referência ao agente pai (setado externamente)
    _parent_agent: Any = None

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "Descrição detalhada da tarefa para o sub-agente executar.",
                },
                "description": {
                    "type": "string",
                    "description": "Resumo curto (3-5 palavras) do que o sub-agente fará.",
                },
            },
            "required": ["task"],
        }

    def execute(self, **kwargs: Any) -> str:
        task = kwargs.get("task", "")
        if not task:
            return "[ERROR] task é obrigatório."

        if self._parent_agent is None:
            return "[ERROR] Sub-agent não configurado (sem agente pai)."

        try:
            from ..agent import SubAgent
            sub = SubAgent(parent=self._parent_agent, task=task)
            result = sub.run()
            return result if result else "(sub-agente não retornou resposta)"
        except Exception as e:
            return f"[ERROR] Falha no sub-agente: {e}"
