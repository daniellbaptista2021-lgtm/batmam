"""Structured Logging do Clow.

Formato JSON estruturado com suporte a:
- Trace IDs para correlacao de requests
- Metricas embutidas (duracao, tokens, contadores)
- Log rotation automatico
- Compatibilidade com OpenTelemetry (trace_id, span_id)
- Export para stdout, arquivo, ou collector externo

Configuracao em settings.json:
{
  "logging": {
    "level": "info",
    "format": "json",
    "rotation": {"max_bytes": 10485760, "backup_count": 5},
    "export": "file"
  }
}
"""

from __future__ import annotations
from .security.redact import redact as _redact
import json
import logging
import logging.handlers
import time
import os
import uuid
import threading
from pathlib import Path
from contextlib import contextmanager
from typing import Any, Generator
from . import config

LOG_DIR = config.CLOW_HOME / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Trace context thread-local
_trace_context = threading.local()


def get_trace_id() -> str:
    """Retorna trace_id atual ou gera um novo."""
    return getattr(_trace_context, "trace_id", "")


def get_span_id() -> str:
    """Retorna span_id atual."""
    return getattr(_trace_context, "span_id", "")


@contextmanager
def trace_context(trace_id: str | None = None, span_id: str | None = None) -> Generator[str, None, None]:
    """Context manager que define trace_id e span_id para o bloco."""
    old_trace = getattr(_trace_context, "trace_id", "")
    old_span = getattr(_trace_context, "span_id", "")

    _trace_context.trace_id = trace_id or uuid.uuid4().hex[:16]
    _trace_context.span_id = span_id or uuid.uuid4().hex[:8]

    try:
        yield _trace_context.trace_id
    finally:
        _trace_context.trace_id = old_trace
        _trace_context.span_id = old_span


class StructuredJSONFormatter(logging.Formatter):
    """Formatter JSON estruturado compativel com OpenTelemetry."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "timestamp_unix": record.created,
            "level": record.levelname.lower(),
            "logger": record.name,
            "module": record.module,
            "action": getattr(record, "action", record.funcName or ""),
            "message": record.getMessage(),
        }

        # Trace context (compativel com OpenTelemetry)
        trace_id = getattr(record, "trace_id", "") or get_trace_id()
        span_id = getattr(record, "span_id", "") or get_span_id()
        if trace_id:
            entry["trace_id"] = trace_id
        if span_id:
            entry["span_id"] = span_id

        # Campos extras estruturados
        for field in ("tool_name", "duration", "tokens", "session_id",
                       "user_id", "request_id", "status_code", "error_type",
                       "file_path", "command", "ip_address"):
            val = getattr(record, field, None)
            if val is not None:
                entry[field] = val

        # Metricas embutidas
        metrics = getattr(record, "metrics", None)
        if metrics and isinstance(metrics, dict):
            entry["metrics"] = metrics

        # Stack trace para erros
        if record.exc_info and record.exc_info[1]:
            entry["error_type"] = type(record.exc_info[1]).__name__
            entry["error_message"] = str(record.exc_info[1])

        return json.dumps(entry, ensure_ascii=False, default=str)


class MetricsCollector:
    """Coleta metricas em memoria para export."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def increment(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + value

    def gauge(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = value

    def observe(self, name: str, value: float) -> None:
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = []
            self._histograms[name].append(value)
            # Mantém apenas ultimos 1000 valores
            if len(self._histograms[name]) > 1000:
                self._histograms[name] = self._histograms[name][-1000:]

    def snapshot(self) -> dict:
        with self._lock:
            result: dict[str, Any] = {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
            }
            for name, values in self._histograms.items():
                if values:
                    sorted_vals = sorted(values)
                    n = len(sorted_vals)
                    result.setdefault("histograms", {})[name] = {
                        "count": n,
                        "min": sorted_vals[0],
                        "max": sorted_vals[-1],
                        "avg": sum(sorted_vals) / n,
                        "p50": sorted_vals[n // 2],
                        "p95": sorted_vals[int(n * 0.95)] if n > 1 else sorted_vals[0],
                        "p99": sorted_vals[int(n * 0.99)] if n > 1 else sorted_vals[0],
                    }
            return result

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()


# Instancia global de metricas
metrics = MetricsCollector()


def get_logger(name: str = "clow") -> logging.Logger:
    """Retorna logger JSON estruturado com rotation."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    settings = config.load_settings()
    log_cfg = settings.get("logging", {})
    level_name = log_cfg.get("level", "debug").upper()
    logger.setLevel(getattr(logging, level_name, logging.DEBUG))

    # Handler arquivo com rotation
    log_file = LOG_DIR / "clow.jsonl"
    rotation = log_cfg.get("rotation", {})
    max_bytes = rotation.get("max_bytes", 10 * 1024 * 1024)  # 10MB
    backup_count = rotation.get("backup_count", 5)

    file_handler = logging.handlers.RotatingFileHandler(
        str(log_file),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(StructuredJSONFormatter())
    logger.addHandler(file_handler)

    # Handler stderr so para erros
    stderr_handler = logging.StreamHandler()
    stderr_handler.setLevel(logging.ERROR)
    stderr_handler.setFormatter(StructuredJSONFormatter())
    logger.addHandler(stderr_handler)

    logger.propagate = False
    return logger


def log_action(
    action: str,
    details: str = "",
    level: str = "info",
    **extra: object,
) -> None:
    """Atalho para logar uma acao estruturada com metricas."""
    logger = get_logger()
    log_func = getattr(logger, level, logger.info)
    record_extra: dict[str, Any] = {"action": action}
    record_extra.update(extra)

    # Coleta metricas automaticamente
    metrics.increment(f"action.{action}")
    if "duration" in extra:
        metrics.observe(f"duration.{action}", float(extra["duration"]))
    if "tokens" in extra:
        metrics.increment("tokens.total", int(extra["tokens"]))

    old_factory = logging.getLogRecordFactory()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = old_factory(*args, **kwargs)
        for k, v in record_extra.items():
            setattr(record, k, v)
        return record

    logging.setLogRecordFactory(factory)
    log_func(details)
    logging.setLogRecordFactory(old_factory)


@contextmanager
def log_timer(action: str, **extra: Any) -> Generator[None, None, None]:
    """Context manager que mede e loga duracao de uma operacao."""
    start = time.time()
    try:
        yield
    finally:
        duration = time.time() - start
        log_action(action, f"completed in {duration:.3f}s", duration=duration, **extra)
