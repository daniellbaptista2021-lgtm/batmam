"""Lifecycle management do Clow — graceful shutdown e crash recovery.

Gerencia:
- Signal handlers (SIGINT, SIGTERM) para shutdown limpo
- Salvamento automatico de sessao antes de sair
- Crash recovery: restaura sessao apos crash inesperado
- Lock file para evitar instancias duplicadas
- Cleanup de recursos (MCP, cron, triggers, worktrees)
"""

from __future__ import annotations
import signal
import sys
import os
import json
import time
import atexit
from pathlib import Path
from typing import Any, Callable
from . import config
from .logging import log_action


CRASH_RECOVERY_FILE = config.CLOW_HOME / ".crash_recovery.json"
LOCK_FILE = config.CLOW_HOME / ".clow.lock"

_shutdown_handlers: list[Callable[[], None]] = []
_is_shutting_down = False


def register_shutdown_handler(handler: Callable[[], None]) -> None:
    """Registra um handler para ser chamado durante shutdown graceful."""
    _shutdown_handlers.append(handler)


def _graceful_shutdown(signum: int | None = None, frame: Any = None) -> None:
    """Handler de shutdown graceful — salva estado e limpa recursos."""
    global _is_shutting_down
    if _is_shutting_down:
        return  # Evita re-entrancia
    _is_shutting_down = True

    sig_name = signal.Signals(signum).name if signum else "atexit"
    log_action("shutdown_start", f"Signal: {sig_name}")

    # Executa handlers registrados
    for handler in reversed(_shutdown_handlers):
        try:
            handler()
        except Exception as e:
            log_action("shutdown_handler_error", str(e), level="warning")

    # Remove lock file
    _release_lock()

    # Remove crash recovery (shutdown limpo = nao precisa recovery)
    if CRASH_RECOVERY_FILE.exists():
        try:
            CRASH_RECOVERY_FILE.unlink()
        except OSError:
            pass

    log_action("shutdown_complete", f"Signal: {sig_name}")


def setup_signal_handlers() -> None:
    """Instala signal handlers para graceful shutdown."""
    signal.signal(signal.SIGINT, _graceful_shutdown)
    signal.signal(signal.SIGTERM, _graceful_shutdown)
    atexit.register(_graceful_shutdown)


# ── Lock File (evita instancias duplicadas) ─────────────────────

def acquire_lock() -> bool:
    """Tenta adquirir lock. Retorna False se outra instancia esta rodando."""
    if LOCK_FILE.exists():
        try:
            with open(LOCK_FILE) as f:
                data = json.load(f)
            pid = data.get("pid", 0)

            # Verifica se o processo ainda esta vivo
            if _is_process_alive(pid):
                return False  # Outra instancia rodando

            # Processo morto — lock stale, pode limpar
            log_action("lock_stale", f"Removendo lock stale do PID {pid}")
        except (json.JSONDecodeError, OSError):
            pass

    # Cria lock
    try:
        with open(LOCK_FILE, "w") as f:
            json.dump({
                "pid": os.getpid(),
                "started_at": time.time(),
                "cwd": os.getcwd(),
            }, f)
        return True
    except OSError:
        return False


def _release_lock() -> None:
    """Libera lock file."""
    if LOCK_FILE.exists():
        try:
            with open(LOCK_FILE) as f:
                data = json.load(f)
            # So remove se o lock e nosso
            if data.get("pid") == os.getpid():
                LOCK_FILE.unlink()
        except (json.JSONDecodeError, OSError):
            pass


def _is_process_alive(pid: int) -> bool:
    """Verifica se um processo esta vivo."""
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            # Windows
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        else:
            # Unix
            os.kill(pid, 0)
            return True
    except (OSError, PermissionError):
        return False


# ── Crash Recovery ──────────────────────────────────────────────

def save_crash_recovery(session_id: str, cwd: str, model: str, messages_count: int) -> None:
    """Salva estado minimo para recovery apos crash."""
    try:
        with open(CRASH_RECOVERY_FILE, "w") as f:
            json.dump({
                "session_id": session_id,
                "cwd": cwd,
                "model": model,
                "messages_count": messages_count,
                "timestamp": time.time(),
                "pid": os.getpid(),
            }, f)
    except OSError:
        pass


def check_crash_recovery() -> dict | None:
    """Verifica se ha uma sessao para recuperar apos crash.

    Retorna dict com info da sessao ou None.
    """
    if not CRASH_RECOVERY_FILE.exists():
        return None

    try:
        with open(CRASH_RECOVERY_FILE) as f:
            data = json.load(f)

        # Verifica se o crash recovery e recente (< 24h)
        age = time.time() - data.get("timestamp", 0)
        if age > 86400:
            CRASH_RECOVERY_FILE.unlink()
            return None

        # Verifica se o PID antigo ainda esta vivo (se sim, nao e crash)
        old_pid = data.get("pid", 0)
        if _is_process_alive(old_pid) and old_pid != os.getpid():
            return None

        return data

    except (json.JSONDecodeError, OSError):
        return None


def clear_crash_recovery() -> None:
    """Limpa o arquivo de crash recovery (sessao restaurada com sucesso)."""
    if CRASH_RECOVERY_FILE.exists():
        try:
            CRASH_RECOVERY_FILE.unlink()
        except OSError:
            pass
