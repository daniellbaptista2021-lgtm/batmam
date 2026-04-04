"""Automations Engine — triggers automaticos para Agents.

Le configuracao de .clow/automations.yaml e executa agentes
quando triggers sao ativados (cron, webhook, github_event, file_change).
"""

from __future__ import annotations
import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import config
from .logging import log_action

AUTOMATIONS_DIR = config.CLOW_HOME / "automations"
AUTOMATIONS_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = AUTOMATIONS_DIR / "executions.jsonl"


@dataclass
class Automation:
    """Definicao de uma automacao."""
    name: str
    trigger_type: str  # cron, webhook, github_event, file_change
    trigger_config: dict = field(default_factory=dict)  # schedule, event, path
    prompt_template: str = ""
    agent_type: str = "default"
    max_runs_per_day: int = 100
    enabled: bool = True
    # Runtime state
    run_count_today: int = 0
    last_run: float = 0
    last_result: str = ""
    _thread: threading.Thread | None = field(default=None, repr=False)
    _stop_event: threading.Event = field(default_factory=threading.Event, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "trigger_type": self.trigger_type,
            "trigger_config": self.trigger_config,
            "prompt_template": self.prompt_template[:200],
            "agent_type": self.agent_type,
            "max_runs_per_day": self.max_runs_per_day,
            "enabled": self.enabled,
            "run_count_today": self.run_count_today,
            "last_run": self.last_run,
            "last_result": self.last_result[:200],
        }


class AutomationsEngine:
    """Engine que gerencia e executa automacoes."""

    def __init__(self) -> None:
        self._automations: dict[str, Automation] = {}
        self._lock = threading.Lock()
        self._agent_factory: Callable | None = None

    def set_agent_factory(self, factory: Callable) -> None:
        self._agent_factory = factory

    def load_from_yaml(self, yaml_path: str | Path | None = None) -> int:
        """Carrega automacoes de arquivo YAML."""
        if yaml_path is None:
            yaml_path = Path.cwd() / ".clow" / "automations.yaml"
        else:
            yaml_path = Path(yaml_path)

        if not yaml_path.exists():
            return 0

        try:
            import yaml
        except ImportError:
            # Fallback: parse YAML simples manualmente
            return self._load_simple_yaml(yaml_path)

        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        return self._process_config(data or {})

    def _load_simple_yaml(self, path: Path) -> int:
        """Parse YAML simplificado sem dependencia."""
        try:
            text = path.read_text(encoding="utf-8")
            data = json.loads(text)  # Tenta JSON primeiro
            return self._process_config(data)
        except (json.JSONDecodeError, Exception):
            return 0

    def _process_config(self, data: dict) -> int:
        """Processa dict de config e registra automacoes."""
        automations_list = data.get("automations", [])
        count = 0

        for item in automations_list:
            name = item.get("name", "")
            if not name:
                continue

            trigger = item.get("trigger", {})
            automation = Automation(
                name=name,
                trigger_type=trigger.get("type", "webhook"),
                trigger_config={
                    k: v for k, v in trigger.items() if k != "type"
                },
                prompt_template=item.get("prompt_template", ""),
                agent_type=item.get("agent_type", "default"),
                max_runs_per_day=item.get("max_runs_per_day", 100),
                enabled=item.get("enabled", True),
            )

            with self._lock:
                self._automations[name] = automation

            if automation.enabled and automation.trigger_type == "cron":
                self._start_cron(automation)

            count += 1

        log_action("automations_loaded", f"{count} automacoes carregadas")
        return count

    def create(self, name: str, trigger_type: str, trigger_config: dict,
               prompt_template: str, max_runs_per_day: int = 100) -> Automation:
        """Cria nova automacao programaticamente."""
        automation = Automation(
            name=name,
            trigger_type=trigger_type,
            trigger_config=trigger_config,
            prompt_template=prompt_template,
            max_runs_per_day=max_runs_per_day,
        )
        with self._lock:
            self._automations[name] = automation

        if trigger_type == "cron":
            self._start_cron(automation)

        log_action("automation_created", f"{name} ({trigger_type})")
        return automation

    def trigger(self, name: str, context: dict | None = None) -> dict[str, Any]:
        """Aciona uma automacao manualmente ou via webhook."""
        with self._lock:
            automation = self._automations.get(name)

        if not automation:
            return {"error": f"Automacao '{name}' nao encontrada"}
        if not automation.enabled:
            return {"error": f"Automacao '{name}' desabilitada"}
        if automation.run_count_today >= automation.max_runs_per_day:
            return {"error": f"Limite diario atingido ({automation.max_runs_per_day})"}

        return self._execute(automation, context or {})

    def enable(self, name: str) -> bool:
        with self._lock:
            a = self._automations.get(name)
            if a:
                a.enabled = True
                if a.trigger_type == "cron":
                    self._start_cron(a)
                return True
        return False

    def disable(self, name: str) -> bool:
        with self._lock:
            a = self._automations.get(name)
            if a:
                a.enabled = False
                a._stop_event.set()
                return True
        return False

    def list_all(self) -> list[dict]:
        with self._lock:
            return [a.to_dict() for a in self._automations.values()]

    def get_logs(self, name: str | None = None, limit: int = 50) -> list[dict]:
        """Retorna logs de execucao."""
        if not LOG_FILE.exists():
            return []
        logs = []
        try:
            with open(LOG_FILE, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if name is None or entry.get("automation") == name:
                            logs.append(entry)
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass
        return logs[-limit:]

    def dashboard(self) -> dict[str, Any]:
        """Retorna status de todas as automacoes para o dashboard."""
        return {
            "total": len(self._automations),
            "enabled": sum(1 for a in self._automations.values() if a.enabled),
            "automations": self.list_all(),
        }

    def stop_all(self) -> None:
        with self._lock:
            for a in self._automations.values():
                a._stop_event.set()

    def _start_cron(self, automation: Automation) -> None:
        """Inicia thread de cron para a automacao."""
        automation._stop_event.clear()

        interval_str = automation.trigger_config.get("schedule", "10m")
        interval = self._parse_interval(interval_str)

        def _cron_loop():
            while not automation._stop_event.is_set():
                automation._stop_event.wait(interval)
                if automation._stop_event.is_set():
                    break
                if automation.enabled and automation.run_count_today < automation.max_runs_per_day:
                    self._execute(automation, {"trigger": "cron"})

        thread = threading.Thread(target=_cron_loop, daemon=True, name=f"auto-{automation.name}")
        automation._thread = thread
        thread.start()

    def _execute(self, automation: Automation, context: dict) -> dict[str, Any]:
        """Executa a automacao com um agente."""
        start = time.time()
        prompt = automation.prompt_template
        for key, value in context.items():
            prompt = prompt.replace(f"{{{key}}}", str(value))

        result = {"automation": automation.name, "status": "error", "output": ""}

        try:
            if self._agent_factory:
                agent = self._agent_factory()
            else:
                from .agent import Agent
                agent = Agent(auto_approve=True, is_subagent=True)

            output = agent.run_turn(prompt or f"Execute automacao: {automation.name}")
            tokens = agent.session.total_tokens_in + agent.session.total_tokens_out

            automation.last_run = time.time()
            automation.run_count_today += 1
            automation.last_result = output[:500]

            result = {
                "automation": automation.name,
                "status": "completed",
                "output": output[:500],
                "tokens": tokens,
                "duration": round(time.time() - start, 2),
                "timestamp": time.time(),
            }

        except Exception as e:
            result = {
                "automation": automation.name,
                "status": "error",
                "output": str(e)[:500],
                "timestamp": time.time(),
                "duration": round(time.time() - start, 2),
            }

        # Loga execucao
        self._log_execution(result)
        log_action("automation_exec", f"{automation.name}: {result['status']}")

        return result

    def _log_execution(self, entry: dict) -> None:
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    @staticmethod
    def _parse_interval(interval_str: str) -> int:
        """Converte '5m', '1h', '30s' para segundos."""
        import re
        match = re.match(r"^(\d+)(s|m|h)$", interval_str.strip())
        if not match:
            return 600  # Default 10min
        value, unit = int(match.group(1)), match.group(2)
        return value * {"s": 1, "m": 60, "h": 3600}[unit]

    def handle_github_event(self, event_type: str, payload: dict) -> dict[str, Any]:
        """Rota eventos GitHub para automacoes com trigger github_event."""
        results = []
        action = payload.get("action", "")
        github_event = f"{event_type}.{action}" if action else event_type

        with self._lock:
            matching = [
                a for a in self._automations.values()
                if a.enabled and a.trigger_type == "github_event"
                and a.trigger_config.get("event") == github_event
            ]

        for automation in matching:
            result = self._execute(automation, {
                "trigger": "github_event",
                "event": github_event,
                "payload": json.dumps(payload)[:2000],
            })
            results.append(result)

        return {"matched": len(results), "results": results}


# Instancia global
_engine = AutomationsEngine()


def get_automations_engine() -> AutomationsEngine:
    return _engine
