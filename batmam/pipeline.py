"""Feature #25: Multi-agent Pipeline.

Encadeia agentes em pipeline: cada etapa passa output pro próximo.
Uso: /pipeline "analisa código" -> "gera testes" -> "faz review"
"""

from __future__ import annotations
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from .logging import log_action


@dataclass
class PipelineStep:
    """Uma etapa do pipeline."""
    prompt: str
    output: str = ""
    status: str = "pending"  # pending, running, completed, error
    duration: float = 0.0


@dataclass
class PipelineResult:
    """Resultado de um pipeline completo."""
    steps: list[PipelineStep] = field(default_factory=list)
    total_duration: float = 0.0
    status: str = "pending"  # pending, running, completed, error

    def summary(self) -> str:
        lines = [f"Pipeline ({len(self.steps)} etapas) — {self.status}"]
        for i, step in enumerate(self.steps, 1):
            icon = {"completed": "✓", "error": "✗", "running": "◑", "pending": "○"}.get(step.status, "?")
            lines.append(f"  {icon} Etapa {i}: {step.prompt[:50]}... [{step.status}] ({step.duration:.1f}s)")
        lines.append(f"  Tempo total: {self.total_duration:.1f}s")
        return "\n".join(lines)


def parse_pipeline(text: str) -> list[str]:
    """Parseia string de pipeline separada por '->'.

    Aceita:
      "analisa código" -> "gera testes" -> "faz review"
      analisa código -> gera testes -> faz review
    """
    # Split por ->
    parts = re.split(r'\s*->\s*', text.strip())
    prompts = []
    for part in parts:
        # Remove aspas externas
        cleaned = part.strip().strip('"').strip("'").strip()
        if cleaned:
            prompts.append(cleaned)
    return prompts


def run_pipeline(
    prompts: list[str],
    agent_factory: Callable[..., Any],
    on_step_start: Callable[[int, str], None] | None = None,
    on_step_done: Callable[[int, str, str], None] | None = None,
) -> PipelineResult:
    """Executa pipeline de agentes sequencialmente.

    Cada etapa recebe o output da anterior como contexto.
    """
    result = PipelineResult(status="running")
    steps = [PipelineStep(prompt=p) for p in prompts]
    result.steps = steps

    pipeline_start = time.time()
    previous_output = ""

    log_action("pipeline_start", f"{len(prompts)} etapas", tool_name="pipeline")

    for i, step in enumerate(steps):
        step.status = "running"
        if on_step_start:
            on_step_start(i, step.prompt)

        # Monta prompt com contexto da etapa anterior
        full_prompt = step.prompt
        if previous_output:
            full_prompt = (
                f"Contexto da etapa anterior:\n```\n{previous_output[:3000]}\n```\n\n"
                f"Agora execute: {step.prompt}"
            )

        step_start = time.time()
        try:
            agent = agent_factory()
            output = agent.run_turn(full_prompt)
            step.output = output
            step.status = "completed"
            previous_output = output
        except Exception as e:
            step.output = f"[ERROR] {e}"
            step.status = "error"
            step.duration = time.time() - step_start
            result.status = "error"
            log_action("pipeline_step_error", str(e), level="error", tool_name="pipeline")
            if on_step_done:
                on_step_done(i, step.status, step.output)
            break

        step.duration = time.time() - step_start

        log_action(
            "pipeline_step_done",
            f"Etapa {i+1}: {step.prompt[:50]}",
            tool_name="pipeline",
            duration=step.duration,
        )

        if on_step_done:
            on_step_done(i, step.status, step.output)

    result.total_duration = time.time() - pipeline_start
    if result.status != "error":
        result.status = "completed"

    log_action("pipeline_done", result.summary(), tool_name="pipeline", duration=result.total_duration)

    return result
