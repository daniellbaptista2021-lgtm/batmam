"""Sistema de Cron / Scheduled Agents do Batmam.

Permite agendar execucao recorrente de agentes com prompts predefinidos.
Armazena config em ~/.batmam/settings.json -> "cron_jobs".
"""

from __future__ import annotations
import json
import time
import threading
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from . import config


@dataclass
class CronJob:
    """Um job agendado."""
    id: str
    name: str
    schedule: str  # Formato cron ou intervalo simples (ex: "5m", "1h", "0 */6 * * *")
    prompt: str
    cwd: str = ""
    model: str = ""
    enabled: bool = True
    last_run: float = 0
    last_result: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "schedule": self.schedule,
            "prompt": self.prompt,
            "cwd": self.cwd,
            "model": self.model,
            "enabled": self.enabled,
            "last_run": self.last_run,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CronJob:
        return cls(
            id=data.get("id", uuid.uuid4().hex[:8]),
            name=data.get("name", ""),
            schedule=data.get("schedule", ""),
            prompt=data.get("prompt", ""),
            cwd=data.get("cwd", ""),
            model=data.get("model", ""),
            enabled=data.get("enabled", True),
            last_run=data.get("last_run", 0),
            created_at=data.get("created_at", time.time()),
        )


def _parse_interval(schedule: str) -> int | None:
    """Converte intervalo simples para segundos. Ex: 5m -> 300, 1h -> 3600."""
    schedule = schedule.strip().lower()
    try:
        if schedule.endswith("s"):
            return int(schedule[:-1])
        elif schedule.endswith("m"):
            return int(schedule[:-1]) * 60
        elif schedule.endswith("h"):
            return int(schedule[:-1]) * 3600
        elif schedule.endswith("d"):
            return int(schedule[:-1]) * 86400
    except ValueError:
        pass
    return None


class CronManager:
    """Gerencia jobs agendados."""

    def __init__(self) -> None:
        self._jobs: dict[str, CronJob] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._running = False
        self._load_jobs()

    def _load_jobs(self) -> None:
        """Carrega jobs do settings.json."""
        settings = config.load_settings()
        for job_data in settings.get("cron_jobs", []):
            job = CronJob.from_dict(job_data)
            self._jobs[job.id] = job

    def _save_jobs(self) -> None:
        """Salva jobs no settings.json."""
        settings = config.load_settings()
        settings["cron_jobs"] = [j.to_dict() for j in self._jobs.values()]
        config.save_settings(settings)

    def create(
        self,
        name: str,
        schedule: str,
        prompt: str,
        cwd: str = "",
        model: str = "",
    ) -> CronJob:
        """Cria um novo job agendado."""
        job = CronJob(
            id=uuid.uuid4().hex[:8],
            name=name,
            schedule=schedule,
            prompt=prompt,
            cwd=cwd or str(Path.cwd()),
            model=model or config.BATMAM_MODEL,
        )
        self._jobs[job.id] = job
        self._save_jobs()
        return job

    def delete(self, job_id: str) -> bool:
        """Remove um job."""
        if job_id in self._jobs:
            del self._jobs[job_id]
            self._save_jobs()
            return True
        return False

    def list_jobs(self) -> list[CronJob]:
        return list(self._jobs.values())

    def get(self, job_id: str) -> CronJob | None:
        return self._jobs.get(job_id)

    def start(self) -> None:
        """Inicia execucao dos jobs em background."""
        self._running = True
        for job in self._jobs.values():
            if job.enabled:
                self._start_job_thread(job)

    def stop(self) -> None:
        """Para todos os jobs."""
        self._running = False

    def _start_job_thread(self, job: CronJob) -> None:
        """Inicia thread para um job."""
        interval = _parse_interval(job.schedule)
        if interval is None:
            return  # Formato cron completo nao suportado ainda

        def _run_loop():
            while self._running and job.enabled:
                time.sleep(interval)
                if not self._running:
                    break
                self._execute_job(job)

        thread = threading.Thread(target=_run_loop, daemon=True, name=f"cron-{job.id}")
        self._threads[job.id] = thread
        thread.start()

    def _execute_job(self, job: CronJob) -> None:
        """Executa um job (roda batmam com o prompt)."""
        try:
            result = subprocess.run(
                ["batmam", "-y", "-m", job.model, job.prompt],
                cwd=job.cwd or None,
                capture_output=True,
                text=True,
                timeout=600,
            )
            job.last_run = time.time()
            job.last_result = result.stdout[-500:] if result.stdout else "(sem saida)"
            self._save_jobs()
        except Exception as e:
            job.last_run = time.time()
            job.last_result = f"[ERROR] {e}"

    def run_once(self, job_id: str) -> str:
        """Executa um job uma vez manualmente."""
        job = self._jobs.get(job_id)
        if not job:
            return "Job nao encontrado."
        self._execute_job(job)
        return job.last_result
