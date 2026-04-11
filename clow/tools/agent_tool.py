"""Ferramenta Agent v0.2.0 — sub-agentes tipados com background e worktree isolation."""

from __future__ import annotations
from typing import Any
from .base import BaseTool
from ..agent_types import get_agent_type, list_agent_types


class AgentTool(BaseTool):
    name = "agent"
    description = (
        "Lança um sub-agente tipado para realizar tarefas. "
        "Tipos: explore (busca rápida), plan (arquitetura), general (tudo), guide (ajuda). "
        "Suporta run_in_background e isolation='worktree'."
    )
    requires_confirmation = False

    # Behavioral flags (Claude Code Ep.02)
    _is_read_only = False
    _is_concurrency_safe = False
    _is_destructive = False
    _search_hint = "agent subagent delegate task"
    _aliases = ["Agent", "subagent"]

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
                "subagent_type": {
                    "type": "string",
                    "enum": ["explore", "plan", "general", "guide"],
                    "description": "Tipo de agente: explore (busca rápida), plan (arquitetura), general (propósito geral), guide (ajuda Clow).",
                },
                "run_in_background": {
                    "type": "boolean",
                    "description": "Se true, executa em background e notifica ao completar. Padrão: false.",
                },
                "isolation": {
                    "type": "string",
                    "enum": ["worktree"],
                    "description": "Se 'worktree', executa em git worktree isolado.",
                },
            },
            "required": ["task"],
        }

    def execute(self, **kwargs: Any) -> str:
        task = kwargs.get("task", "")
        description = kwargs.get("description", "")
        run_in_background = kwargs.get("run_in_background", False)
        isolation = kwargs.get("isolation", "")

        if not task:
            return "[ERROR] task é obrigatório."

        if self._parent_agent is None:
            return "[ERROR] Sub-agent não configurado (sem agente pai)."

        # Worktree isolation
        if isolation == "worktree":
            return self._run_in_worktree(task, description, run_in_background)

        # Background execution
        if run_in_background:
            return self._run_background(task, description)

        # Execução normal (síncrona)
        return self._run_sync(task)

    def _run_sync(self, task: str) -> str:
        """Executa sub-agente de forma síncrona."""
        try:
            from ..agent import SubAgent
            sub = SubAgent(parent=self._parent_agent, task=task)
            result = sub.run()
            return result if result else "(sub-agente não retornou resposta)"
        except Exception as e:
            return f"[ERROR] Falha no sub-agente: {e}"

    def _run_background(self, task: str, description: str) -> str:
        """Executa sub-agente em background thread."""
        try:
            job_id = self._parent_agent.run_background(task, description)
            return (
                f"Sub-agente iniciado em background.\n"
                f"ID: {job_id}\n"
                f"Descrição: {description or task[:50]}\n"
                f"Você será notificado quando completar."
            )
        except Exception as e:
            return f"[ERROR] Falha ao iniciar background agent: {e}"

    def _run_in_worktree(self, task: str, description: str, background: bool) -> str:
        """Executa sub-agente em git worktree isolado."""
        try:
            from ..worktree import WorktreeManager

            cwd = self._parent_agent.cwd
            if not WorktreeManager.is_git_repo(cwd):
                return "[ERROR] Não é um repositório git. Worktree isolation requer git."

            wt_mgr = WorktreeManager(cwd)
            wt_info = wt_mgr.create()

            # Modifica a task para incluir contexto do worktree
            wt_task = (
                f"[Executando em worktree isolado: {wt_info.path}]\n"
                f"[Branch: {wt_info.branch}, baseado em: {wt_info.base_branch}]\n\n"
                f"{task}"
            )

            if background:
                # Background + worktree
                import threading

                def _run():
                    try:
                        from ..agent import Agent
                        agent = Agent(
                            cwd=wt_info.path,
                            model=self._parent_agent.model,
                            on_text_delta=lambda t: None,
                            on_text_done=lambda t: None,
                            on_tool_call=self._parent_agent.on_tool_call,
                            on_tool_result=self._parent_agent.on_tool_result,
                            ask_confirmation=self._parent_agent.ask_confirmation,
                            auto_approve=self._parent_agent.auto_approve,
                            is_subagent=True,
                        )
                        agent.run_turn(wt_task)
                    finally:
                        wt_mgr.cleanup(wt_info)

                thread = threading.Thread(target=_run, daemon=True, name=f"wt-{wt_info.branch}")
                thread.start()

                return (
                    f"Sub-agente iniciado em worktree isolado (background).\n"
                    f"Branch: {wt_info.branch}\n"
                    f"Path: {wt_info.path}"
                )

            # Síncrono + worktree
            try:
                from ..agent import Agent
                agent = Agent(
                    cwd=wt_info.path,
                    model=self._parent_agent.model,
                    on_text_delta=lambda t: None,
                    on_text_done=lambda t: None,
                    on_tool_call=self._parent_agent.on_tool_call,
                    on_tool_result=self._parent_agent.on_tool_result,
                    ask_confirmation=self._parent_agent.ask_confirmation,
                    auto_approve=self._parent_agent.auto_approve,
                    is_subagent=True,
                )
                result = agent.run_turn(wt_task)
            finally:
                cleanup_info = wt_mgr.cleanup(wt_info)

            if cleanup_info.has_changes:
                return (
                    f"{result}\n\n"
                    f"[Worktree] Mudanças detectadas.\n"
                    f"Branch: {cleanup_info.branch}\n"
                    f"Use `git merge {cleanup_info.branch}` para incorporar."
                )
            else:
                return f"{result}\n\n[Worktree] Sem mudanças — branch removida."

        except Exception as e:
            return f"[ERROR] Falha no worktree: {e}"
