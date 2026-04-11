"""Multi-Agent Coordinator - Parallel Worker Orchestration (Claude Code Ep.03).

Transforms Clow from single-agent into multi-agent orchestrator.
Dispatches parallel workers, routes messages, synthesizes results.

Architecture:
- Coordinator mode: orchestrator with restricted tools (Agent, SendMessage, TaskStop)
- Workers: full tool access, zero shared context, communicate via task-notifications
- 4-phase workflow: Research -> Synthesis -> Implementation -> Verification

Key principle: "Never delegate understanding" - coordinator synthesizes, workers execute.
"""

import os
import json
import time
import uuid
import threading
import logging
import shutil
from dataclasses import dataclass, field
from typing import Any, Callable
from . import config

logger = logging.getLogger("clow.coordinator")

# == Mode Detection ==

_coordinator_mode = False


def is_coordinator_mode() -> bool:
    """Check if running in coordinator mode."""
    return _coordinator_mode or os.getenv("CLOW_COORDINATOR_MODE", "").lower() in ("1", "true", "yes")


def set_coordinator_mode(enabled: bool) -> None:
    global _coordinator_mode
    _coordinator_mode = enabled
    if enabled:
        os.environ["CLOW_COORDINATOR_MODE"] = "1"
    else:
        os.environ.pop("CLOW_COORDINATOR_MODE", None)


def match_session_mode(session_mode: str = "") -> bool:
    """Match coordinator mode to a resumed session. Returns True if switched."""
    current = is_coordinator_mode()
    session_is_coord = session_mode == "coordinator"
    if current == session_is_coord:
        return False
    set_coordinator_mode(session_is_coord)
    return True


# == Coordinator Tools (restricted set) ==

COORDINATOR_TOOLS = {"agent", "web_search", "web_fetch", "read", "glob", "grep"}
# Coordinator CANNOT use: bash, write, edit, deploy, docker, ssh, etc.
# All hands-on work is delegated to workers.

WORKER_TOOLS_FULL = {
    "read", "write", "edit", "glob", "grep", "bash", "agent",
    "web_search", "web_fetch", "git_ops",
}

WORKER_TOOLS_SIMPLE = {"bash", "read", "edit"}

# Internal tools workers cannot access
INTERNAL_TOOLS = {"team_create", "team_delete", "send_message"}


def get_coordinator_tools() -> set[str]:
    """Get tools available in coordinator mode."""
    return COORDINATOR_TOOLS


def get_worker_tools(simple: bool = False) -> set[str]:
    """Get tools available to workers."""
    if simple:
        return WORKER_TOOLS_SIMPLE
    return WORKER_TOOLS_FULL - INTERNAL_TOOLS


# == Coordinator System Prompt ==

COORDINATOR_SYSTEM_PROMPT = """Voce e um orquestrador multi-agente. Voce NAO executa codigo diretamente.
Voce despacha workers, sintetiza resultados, e coordena o trabalho.

REGRAS CRITICAS:

1. VOCE NAO TEM ACESSO A FERRAMENTAS DE ESCRITA
   - Sem bash, write, edit, deploy
   - Toda execucao e delegada a workers via Agent tool

2. CONTEXTO ISOLADO
   - Workers NAO veem sua conversa
   - Cada prompt deve ser auto-contido: caminhos, numeros de linha, erros, criterio de "pronto"
   - Nunca escreva "baseado na sua pesquisa" - isso delega entendimento ao worker

3. WORKFLOW DE 4 FASES
   Fase 1: PESQUISA (paralelo)
   - Lance multiplos workers para investigar o codebase
   - Workers de pesquisa sao read-only

   Fase 2: SINTESE (voce)
   - Leia os resultados dos workers
   - ENTENDA o problema voce mesmo
   - Crie specs de implementacao especificos

   Fase 3: IMPLEMENTACAO (sequencial)
   - Workers fazem mudancas conforme suas specs
   - Um worker por arquivo/conjunto de arquivos

   Fase 4: VERIFICACAO (workers frescos)
   - Lance workers NOVOS para verificar (nunca continue workers de implementacao)
   - Verificacao independente sem suposicoes

4. QUANDO CONTINUAR vs CRIAR NOVO WORKER
   - Pesquisa achou arquivos certos -> continue para implementar (worker tem contexto)
   - Pesquisa foi ampla, implementacao e estreita -> novo worker
   - Worker falhou -> continue (tem contexto do erro)
   - Verificando codigo de outro -> novo worker (olhos frescos)
   - Abordagem errada -> novo worker (evita ancoragem)

5. SINTESE E SUA RESPONSABILIDADE
   - Nunca delegue entendimento. Leia os resultados e ENTENDA.
   - Escreva specs que provem que voce entendeu: caminhos, linhas, o que mudar.
   - Prompts vagos produzem trabalho superficial."""


# == Worker Management ==

@dataclass
class Worker:
    """A worker agent managed by the coordinator."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    description: str = ""
    prompt: str = ""
    status: str = "pending"  # pending, running, completed, failed, killed
    result: str = ""
    error: str = ""
    started_at: float = 0
    completed_at: float = 0
    tokens_used: int = 0
    tools_used: int = 0
    thread: threading.Thread | None = field(default=None, repr=False)

    def to_notification(self) -> str:
        """Format as XML task-notification (Claude Code pattern)."""
        duration = int((self.completed_at - self.started_at) * 1000) if self.completed_at else 0
        return (
            f"<task-notification>\n"
            f"  <task-id>{self.id}</task-id>\n"
            f"  <status>{self.status}</status>\n"
            f"  <summary>{self.description}</summary>\n"
            f"  <result>{self.result[:2000]}</result>\n"
            f"  <usage>\n"
            f"    <total_tokens>{self.tokens_used}</total_tokens>\n"
            f"    <tool_uses>{self.tools_used}</tool_uses>\n"
            f"    <duration_ms>{duration}</duration_ms>\n"
            f"  </usage>\n"
            f"</task-notification>"
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id, "description": self.description,
            "status": self.status, "result": self.result[:500],
            "error": self.error,
            "started_at": self.started_at, "completed_at": self.completed_at,
            "tokens_used": self.tokens_used, "tools_used": self.tools_used,
        }


class Coordinator:
    """Multi-agent coordinator that dispatches and manages workers."""

    def __init__(self, cwd: str = "", model: str = ""):
        self.cwd = cwd or os.getcwd()
        self.model = model or config.CLOW_MODEL
        self._workers: dict[str, Worker] = {}
        self._lock = threading.Lock()
        self._notifications: list[str] = []  # Pending notifications for coordinator
        self._scratchpad_dir = ""

        # Create scratchpad directory
        self._scratchpad_dir = str(config.CLOW_HOME / "scratchpad" / uuid.uuid4().hex[:8])
        os.makedirs(self._scratchpad_dir, exist_ok=True)

    def spawn_worker(
        self,
        description: str,
        prompt: str,
        model: str = "",
        on_complete: Callable | None = None,
    ) -> str:
        """Spawn a new worker agent. Returns worker ID."""
        worker = Worker(description=description, prompt=prompt)

        with self._lock:
            self._workers[worker.id] = worker

        def _run():
            worker.status = "running"
            worker.started_at = time.time()
            try:
                from .agent import Agent

                agent = Agent(
                    cwd=self.cwd,
                    model=model or self.model,
                    auto_approve=True,
                    is_subagent=True,
                )

                # Inject scratchpad info into prompt
                full_prompt = prompt
                if self._scratchpad_dir:
                    full_prompt += (
                        f"\n\n[Scratchpad directory: {self._scratchpad_dir}"
                        f" - use for cross-worker shared data]"
                    )

                result = agent.run_turn(full_prompt)

                worker.result = result or ""
                worker.status = "completed"
                worker.tokens_used = (
                    agent.session.total_tokens_in + agent.session.total_tokens_out
                )
                worker.tools_used = sum(
                    len(t.tool_calls) for t in agent.session.turns
                )

            except Exception as e:
                worker.error = str(e)[:200]
                worker.status = "failed"
                logger.error(f"Worker {worker.id} failed: {e}")

            worker.completed_at = time.time()

            # Queue notification for coordinator
            with self._lock:
                self._notifications.append(worker.to_notification())

            if on_complete:
                on_complete(worker.id, worker.result)

        worker.thread = threading.Thread(
            target=_run, daemon=True, name=f"coord-{worker.id}"
        )
        worker.thread.start()

        logger.info(f"Worker spawned: {worker.id} - {description}")
        return worker.id

    def send_message(self, worker_id: str, message: str) -> bool:
        """Send follow-up message to a running/completed worker."""
        worker = self._workers.get(worker_id)
        if not worker:
            return False

        # For continued workers, spawn a new thread with the follow-up
        if worker.status in ("completed", "failed"):
            # Continue with context
            worker.status = "running"
            worker.started_at = time.time()

            def _continue():
                try:
                    from .agent import Agent

                    agent = Agent(
                        cwd=self.cwd, model=self.model,
                        auto_approve=True, is_subagent=True,
                    )
                    # Include previous result as context
                    context = (
                        f"Contexto anterior:\n{worker.result[:3000]}"
                        f"\n\nNova instrucao:\n{message}"
                    )
                    result = agent.run_turn(context)
                    worker.result = result or ""
                    worker.status = "completed"
                except Exception as e:
                    worker.error = str(e)[:200]
                    worker.status = "failed"

                worker.completed_at = time.time()
                with self._lock:
                    self._notifications.append(worker.to_notification())

            worker.thread = threading.Thread(target=_continue, daemon=True)
            worker.thread.start()
            return True

        return False

    def stop_worker(self, worker_id: str) -> bool:
        """Kill a running worker."""
        worker = self._workers.get(worker_id)
        if not worker or worker.status != "running":
            return False

        worker.status = "killed"
        worker.completed_at = time.time()
        # Thread is daemon - will die with process or when agent loop ends

        with self._lock:
            self._notifications.append(worker.to_notification())

        logger.info(f"Worker killed: {worker_id}")
        return True

    def get_pending_notifications(self) -> list[str]:
        """Get and clear pending worker notifications."""
        with self._lock:
            notifs = list(self._notifications)
            self._notifications.clear()
        return notifs

    def get_worker(self, worker_id: str) -> dict | None:
        worker = self._workers.get(worker_id)
        return worker.to_dict() if worker else None

    def list_workers(self) -> list[dict]:
        return [w.to_dict() for w in self._workers.values()]

    def get_status(self) -> dict:
        workers = list(self._workers.values())
        return {
            "mode": "coordinator" if is_coordinator_mode() else "normal",
            "total_workers": len(workers),
            "running": sum(1 for w in workers if w.status == "running"),
            "completed": sum(1 for w in workers if w.status == "completed"),
            "failed": sum(1 for w in workers if w.status == "failed"),
            "killed": sum(1 for w in workers if w.status == "killed"),
            "scratchpad": self._scratchpad_dir,
            "total_tokens": sum(w.tokens_used for w in workers),
        }

    def cleanup(self) -> None:
        """Cleanup coordinator resources."""
        # Stop all running workers
        for w in self._workers.values():
            if w.status == "running":
                w.status = "killed"

        # Remove scratchpad
        if self._scratchpad_dir and os.path.exists(self._scratchpad_dir):
            shutil.rmtree(self._scratchpad_dir, ignore_errors=True)


# == Global Coordinator ==

_coordinator: Coordinator | None = None


def get_coordinator(cwd: str = "", model: str = "") -> Coordinator:
    global _coordinator
    if _coordinator is None:
        _coordinator = Coordinator(cwd=cwd, model=model)
    return _coordinator


def reset_coordinator() -> None:
    global _coordinator
    if _coordinator:
        _coordinator.cleanup()
    _coordinator = None
