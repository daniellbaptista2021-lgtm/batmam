"""Feature #23: Log Estruturado em JSON.

Formato: {"timestamp", "level", "module", "action", "details"}
Facilita integração com n8n, Supabase, ou qualquer log aggregator.
"""

from __future__ import annotations
import json
import logging
import time
import os
from pathlib import Path
from . import config

LOG_DIR = config.CLOW_HOME / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


class JSONFormatter(logging.Formatter):
    """Formatter que gera JSON estruturado por linha."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname.lower(),
            "module": record.module,
            "action": getattr(record, "action", record.funcName or ""),
            "details": record.getMessage(),
        }
        # Campos extras opcionais
        if hasattr(record, "tool_name"):
            entry["tool_name"] = record.tool_name
        if hasattr(record, "duration"):
            entry["duration"] = record.duration
        if hasattr(record, "tokens"):
            entry["tokens"] = record.tokens
        if hasattr(record, "session_id"):
            entry["session_id"] = record.session_id
        return json.dumps(entry, ensure_ascii=False)


def get_logger(name: str = "clow") -> logging.Logger:
    """Retorna logger JSON configurado. Reutiliza se já existe."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # Handler arquivo JSON (rotação diária por nome)
    log_file = LOG_DIR / "clow.jsonl"
    file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(JSONFormatter())
    logger.addHandler(file_handler)

    # Handler stderr só para erros (não polui stdout)
    stderr_handler = logging.StreamHandler()
    stderr_handler.setLevel(logging.ERROR)
    stderr_handler.setFormatter(JSONFormatter())
    logger.addHandler(stderr_handler)

    # Não propaga para root logger
    logger.propagate = False

    return logger


def log_action(
    action: str,
    details: str = "",
    level: str = "info",
    **extra: object,
) -> None:
    """Atalho para logar uma ação estruturada."""
    logger = get_logger()
    log_func = getattr(logger, level, logger.info)
    record_extra = {"action": action}
    record_extra.update(extra)

    # Cria um LogRecord customizado para injetar extras
    old_factory = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = old_factory(*args, **kwargs)
        for k, v in record_extra.items():
            setattr(record, k, v)
        return record

    logging.setLogRecordFactory(factory)
    log_func(details)
    logging.setLogRecordFactory(old_factory)
