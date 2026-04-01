"""Cron Jobs do Batmam — executa prompts em intervalos regulares."""

from __future__ import annotations
import uuid
import time
import threading
import re
from dataclasses import dataclass, field
from typing import Callable, Any


@dataclass
class CronJob:
    """Um job agendado."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    prompt: str = ""
    interval_seconds: int = 600  # 10 minutos padrão
    active: bool = True
    created_at: float = field(default_factory=time.time)
    last_run: float = 0.0
    run_count: int = 0
    last_output: str = ""
    _thread: threading.Thread | None = field(default=None, repr=False)
    _stop_event: threading.Event = field(default_factory=threading.Event, repr=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "prompt": self.prompt,
            "interval": self.interval_seconds,
            "active": self.active,
            "created_at": self.created_at,
            "last_run": self.last_run,
            "run_count": self.run_count,
            "last_output": self.last_output[:200],
        }


def parse_interval(interval_str: str) -> int:
    """Converte string de intervalo para segundos. Ex: '5m', '1h', '30s'."""
    match = re.match(r"^(\d+)(s|m|h)$", interval_str.strip().lower())
    if not match:
        raise ValueError(f"Intervalo inválido: {interval_str}. Use formato: 5m, 1h, 30s")
    value = int(match.group(1))
    unit = match.group(2)
    multipliers = {"s": 1, "m": 60, "h": 3600}
    return value * multipliers[unit]


class CronManager:
    """Gerencia cron jobs em background threads."""

    def __init__(self) -> None:
        self._jobs: dict[str, CronJob] = {}
        self._agent_factory: Callable[..., Any] | None = None
        self._on_complete: Callable[[str, str], None] | None = None

    def set_agent_factory(self, factory: Callable[..., Any]) -> None:
        """Define factory para criar agentes para execução de jobs."""
        self._agent_factory = factory

    def set_on_complete(self, callback: Callable[[str, str], None]) -> None:
        """Callback chamado quando um job completa uma execução."""
        self._on_complete = callback

    def create(self, prompt: str, interval_str: str) -> CronJob:
        """Cria e inicia um novo cron job."""
        seconds = parse_interval(interval_str)
        job = CronJob(prompt=prompt, interval_seconds=seconds)
        self._jobs[job.id] = job
        self._start_job(job)
        return job

    def delete(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job:
            return False
        job._stop_event.set()
        job.active = False
        if job._thread and job._thread.is_alive():
            job._thread.join(timeout=2)
        del self._jobs[job_id]
        return True

    def pause(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job:
            return False
        job._stop_event.set()
        job.active = False
        return True

    def resume(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job or job.active:
            return False
        job._stop_event.clear()
        job.active = True
        self._start_job(job)
        return True

    def list_all(self) -> list[CronJob]:
        return sorted(self._jobs.values(), key=lambda j: j.created_at)

    def get(self, job_id: str) -> CronJob | None:
        return self._jobs.get(job_id)

    def stop_all(self) -> None:
        for job in self._jobs.values():
            job._stop_event.set()
            job.active = False

    def _start_job(self, job: CronJob) -> None:
        """Inicia thread de execução para o job."""
        def run_loop():
            while not job._stop_event.is_set():
                job._stop_event.wait(job.interval_seconds)
                if job._stop_event.is_set():
                    break
                try:
                    self._execute_job(job)
                except Exception as e:
                    job.last_output = f"[ERROR] {e}"

        job._thread = threading.Thread(target=run_loop, daemon=True, name=f"cron-{job.id}")
        job._thread.start()

    def _execute_job(self, job: CronJob) -> None:
        """Executa o prompt do job usando o agent factory."""
        if not self._agent_factory:
            job.last_output = "[ERROR] Agent factory não configurado"
            return

        try:
            agent = self._agent_factory()
            result = agent.run_turn(job.prompt)
            job.last_run = time.time()
            job.run_count += 1
            job.last_output = result[:500]

            if self._on_complete:
                self._on_complete(job.id, result)
        except Exception as e:
            job.last_output = f"[ERROR] {e}"

    def format_interval(self, seconds: int) -> str:
        if seconds >= 3600:
            return f"{seconds // 3600}h"
        if seconds >= 60:
            return f"{seconds // 60}m"
        return f"{seconds}s"


# Instância global
_cron_manager = CronManager()

def get_cron_manager() -> CronManager:
    return _cron_manager
