"""Agent Swarm — coordena multiplos agentes paralelos para tasks complexas.

Decompoe uma task em subtasks, spawna agentes em worktrees git isolados,
executa em paralelo, coleta resultados e faz merge automatizado.
"""

from __future__ import annotations
import json
import os
import subprocess
import time
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from pathlib import Path
from typing import Any, Callable

from . import config
from .logging import log_action


class SwarmAgent:
    """Representa um agente individual dentro do swarm."""

    def __init__(
        self,
        agent_id: str,
        subtask: str,
        worktree_path: str | None = None,
    ):
        self.agent_id = agent_id
        self.subtask = subtask
        self.worktree_path = worktree_path
        self.status = "pending"  # pending -> running -> completed | error
        self.result = ""
        self.error = ""
        self.started_at: float = 0
        self.completed_at: float = 0
        self.files_changed: list[str] = []

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "agent_id": self.agent_id,
            "subtask": self.subtask[:100],
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration": round(self.completed_at - self.started_at, 2) if self.completed_at else 0,
            "files_changed": self.files_changed,
        }
        if self.error:
            d["error"] = self.error[:200]
        return d


class SwarmCoordinator:
    """Coordena a execucao de multiplos agentes em paralelo.

    Fluxo:
    1. Recebe task complexa
    2. Decompoe em subtasks via LLM
    3. Cria worktrees git isolados
    4. Spawna agentes paralelos
    5. Coleta resultados
    6. Merge worktrees de volta
    7. Roda validacao
    """

    def __init__(
        self,
        cwd: str,
        model: str | None = None,
        on_progress: Callable[[str], None] | None = None,
        on_tool_call: Callable[[str, dict], None] | None = None,
        on_tool_result: Callable[[str, str, str], None] | None = None,
        ask_confirmation: Callable[[str], bool] | None = None,
        auto_approve: bool = False,
    ):
        self.cwd = cwd
        self.model = model or config.CLOW_MODEL
        self.on_progress = on_progress or (lambda msg: None)
        self.on_tool_call = on_tool_call
        self.on_tool_result = on_tool_result
        self.ask_confirmation = ask_confirmation
        self.auto_approve = auto_approve
        self.max_agents = config.CLOW_SWARM_MAX_AGENTS
        self.agents: list[SwarmAgent] = []
        self._lock = threading.Lock()
        self.swarm_id = uuid.uuid4().hex[:8]

    def run(self, task: str) -> dict[str, Any]:
        """Executa o swarm completo. Retorna resultado consolidado."""
        log_action("swarm_start", f"task={task[:80]}", session_id=self.swarm_id)
        self.on_progress(f"[Swarm {self.swarm_id}] Decompondo task em subtasks...")

        # 1. Decompoe task
        subtasks = self._decompose_task(task)
        if not subtasks:
            return {"success": False, "error": "Nao conseguiu decompor a task em subtasks"}

        self.on_progress(f"[Swarm] {len(subtasks)} subtasks identificadas")

        # 2. Cria agentes (limite de max_agents)
        subtasks = subtasks[:self.max_agents]
        for i, st in enumerate(subtasks):
            agent = SwarmAgent(
                agent_id=f"swarm-{self.swarm_id}-{i}",
                subtask=st,
            )
            self.agents.append(agent)

        # 3. Cria worktrees e executa
        self.on_progress(f"[Swarm] Criando {len(self.agents)} worktrees git...")
        worktrees_created = self._create_worktrees()

        if not worktrees_created:
            # Fallback: executa sem worktrees (sequencial no mesmo dir)
            self.on_progress("[Swarm] Git worktrees nao disponivel, executando sequencial...")
            return self._run_sequential(task, subtasks)

        # 4. Executa agentes em paralelo
        self.on_progress("[Swarm] Executando agentes em paralelo...")
        self._run_parallel()

        # 5. Coleta resultados
        results = self._collect_results()

        # 6. Merge worktrees
        self.on_progress("[Swarm] Fazendo merge dos resultados...")
        merge_result = self._merge_worktrees()

        # 7. Cleanup worktrees
        self._cleanup_worktrees()

        log_action("swarm_done", f"agents={len(self.agents)}", session_id=self.swarm_id)

        return {
            "success": True,
            "swarm_id": self.swarm_id,
            "agents": [a.to_dict() for a in self.agents],
            "merge": merge_result,
            "summary": results,
        }

    def _decompose_task(self, task: str) -> list[str]:
        """Usa LLM para decompor task em subtasks paralelas."""
        try:
            from openai import OpenAI
            client = OpenAI(**config.get_deepseek_client_kwargs())
            response = client.chat.completions.create(
                model=config.CLOW_MODEL,
                messages=[
                    {"role": "system", "content": (
                        "Decompoe tasks em subtasks paralelas. "
                        "Retorne APENAS JSON array de strings. Max 5 subtasks."
                    )},
                    {"role": "user", "content": task},
                ],
                max_tokens=1000,
            )
            raw = response.choices[0].message.content.strip()

            # Parse JSON
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            subtasks = json.loads(raw)
            if isinstance(subtasks, list) and all(isinstance(s, str) for s in subtasks):
                return subtasks[:self.max_agents]
            return []

        except Exception as e:
            log_action("swarm_decompose_error", str(e), level="warning")
            return []

    def _create_worktrees(self) -> bool:
        """Cria git worktrees isolados para cada agente."""
        try:
            # Verifica se estamos num repo git
            result = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=self.cwd, capture_output=True, text=True,
            )
            if result.returncode != 0:
                return False

            base_branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.cwd, capture_output=True, text=True,
            ).stdout.strip()

            for agent in self.agents:
                wt_path = str(Path(self.cwd) / f".clow-worktree-{agent.agent_id}")
                branch_name = f"clow-swarm-{agent.agent_id}"

                # Cria worktree
                subprocess.run(
                    ["git", "worktree", "add", "-b", branch_name, wt_path, base_branch],
                    cwd=self.cwd, capture_output=True, text=True,
                )
                if Path(wt_path).exists():
                    agent.worktree_path = wt_path
                else:
                    return False

            return True
        except Exception:
            return False

    def _run_parallel(self) -> None:
        """Executa agentes em paralelo via ThreadPoolExecutor."""
        from .agent import Agent

        def run_agent(swarm_agent: SwarmAgent) -> None:
            swarm_agent.status = "running"
            swarm_agent.started_at = time.time()
            self.on_progress(f"  [{swarm_agent.agent_id}] Iniciando: {swarm_agent.subtask[:60]}...")

            try:
                agent = Agent(
                    cwd=swarm_agent.worktree_path or self.cwd,
                    model=self.model,
                    on_text_delta=lambda t: None,
                    on_text_done=lambda t: None,
                    on_tool_call=self.on_tool_call or (lambda n, a: None),
                    on_tool_result=self.on_tool_result or (lambda n, s, o: None),
                    ask_confirmation=self.ask_confirmation or (lambda m: True),
                    auto_approve=self.auto_approve,
                    is_subagent=True,
                )
                result = agent.run_turn(swarm_agent.subtask)
                swarm_agent.result = result
                swarm_agent.status = "completed"

                # Coleta arquivos modificados
                if swarm_agent.worktree_path:
                    diff_out = subprocess.run(
                        ["git", "diff", "--name-only"],
                        cwd=swarm_agent.worktree_path,
                        capture_output=True, text=True,
                    )
                    swarm_agent.files_changed = [
                        f for f in diff_out.stdout.strip().split("\n") if f
                    ]

            except Exception as e:
                swarm_agent.status = "error"
                swarm_agent.error = str(e)
            finally:
                swarm_agent.completed_at = time.time()
                self.on_progress(
                    f"  [{swarm_agent.agent_id}] {swarm_agent.status} "
                    f"({swarm_agent.completed_at - swarm_agent.started_at:.1f}s)"
                )

        with ThreadPoolExecutor(max_workers=self.max_agents) as executor:
            futures = [executor.submit(run_agent, a) for a in self.agents]
            for f in as_completed(futures):
                pass  # Resultados ja atualizados nos objetos SwarmAgent

    def _run_sequential(self, task: str, subtasks: list[str]) -> dict[str, Any]:
        """Fallback: executa subtasks sequencialmente sem worktrees."""
        from .agent import Agent

        results = []
        for i, st in enumerate(subtasks):
            self.on_progress(f"  [seq-{i}] {st[:60]}...")
            try:
                agent = Agent(
                    cwd=self.cwd,
                    model=self.model,
                    on_text_delta=lambda t: None,
                    on_text_done=lambda t: None,
                    auto_approve=self.auto_approve,
                    is_subagent=True,
                )
                result = agent.run_turn(st)
                results.append({"subtask": st, "status": "completed", "result": result[:500]})
            except Exception as e:
                results.append({"subtask": st, "status": "error", "error": str(e)})

        return {
            "success": True,
            "swarm_id": self.swarm_id,
            "mode": "sequential",
            "agents": results,
            "merge": {"status": "not_needed"},
        }

    def _merge_worktrees(self) -> dict[str, Any]:
        """Merge worktrees de volta na branch principal."""
        merged = []
        conflicts = []

        for agent in self.agents:
            if agent.status != "completed" or not agent.worktree_path:
                continue
            if not agent.files_changed:
                continue

            branch_name = f"clow-swarm-{agent.agent_id}"
            try:
                # Commit changes no worktree
                subprocess.run(
                    ["git", "add", "-A"], cwd=agent.worktree_path,
                    capture_output=True, text=True,
                )
                subprocess.run(
                    ["git", "commit", "-m", f"swarm: {agent.subtask[:60]}"],
                    cwd=agent.worktree_path, capture_output=True, text=True,
                )

                # Merge na branch principal
                result = subprocess.run(
                    ["git", "merge", "--no-edit", branch_name],
                    cwd=self.cwd, capture_output=True, text=True,
                )
                if result.returncode == 0:
                    merged.append(agent.agent_id)
                else:
                    # Conflito — abort e reporta
                    subprocess.run(
                        ["git", "merge", "--abort"],
                        cwd=self.cwd, capture_output=True, text=True,
                    )
                    conflicts.append({
                        "agent": agent.agent_id,
                        "error": result.stderr[:200],
                    })

            except Exception as e:
                conflicts.append({"agent": agent.agent_id, "error": str(e)})

        return {
            "status": "completed",
            "merged": merged,
            "conflicts": conflicts,
        }

    def _collect_results(self) -> str:
        """Consolida resultados de todos os agentes."""
        parts = []
        for agent in self.agents:
            status_emoji = {"completed": "[OK]", "error": "[ERRO]", "running": "[...]"}.get(
                agent.status, "[?]"
            )
            parts.append(f"{status_emoji} {agent.agent_id}: {agent.subtask[:60]}")
            if agent.files_changed:
                parts.append(f"    Arquivos: {', '.join(agent.files_changed[:5])}")
            if agent.error:
                parts.append(f"    Erro: {agent.error[:100]}")
        return "\n".join(parts)

    def _cleanup_worktrees(self) -> None:
        """Remove worktrees e branches temporarias."""
        for agent in self.agents:
            if not agent.worktree_path:
                continue
            try:
                subprocess.run(
                    ["git", "worktree", "remove", "--force", agent.worktree_path],
                    cwd=self.cwd, capture_output=True, text=True,
                )
                branch_name = f"clow-swarm-{agent.agent_id}"
                subprocess.run(
                    ["git", "branch", "-D", branch_name],
                    cwd=self.cwd, capture_output=True, text=True,
                )
            except Exception:
                pass

    def get_status(self) -> list[dict]:
        """Retorna status de todos os agentes."""
        return [a.to_dict() for a in self.agents]
