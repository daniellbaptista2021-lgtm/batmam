"""Testes do lifecycle management (graceful shutdown + crash recovery)."""

import unittest
import sys
import os
import json
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from clow.lifecycle import (
    save_crash_recovery, check_crash_recovery, clear_crash_recovery,
    acquire_lock, _release_lock, _is_process_alive,
    register_shutdown_handler, CRASH_RECOVERY_FILE, LOCK_FILE,
)


class TestCrashRecovery(unittest.TestCase):
    """Testes de crash recovery."""

    def setUp(self):
        # Limpa arquivos de recovery antes de cada teste
        if CRASH_RECOVERY_FILE.exists():
            CRASH_RECOVERY_FILE.unlink()

    def tearDown(self):
        if CRASH_RECOVERY_FILE.exists():
            CRASH_RECOVERY_FILE.unlink()

    def test_save_and_check(self):
        save_crash_recovery("sess123", "/home/user", "claude-sonnet", 50)
        data = check_crash_recovery()
        self.assertIsNotNone(data)
        self.assertEqual(data["session_id"], "sess123")
        self.assertEqual(data["cwd"], "/home/user")
        self.assertEqual(data["model"], "claude-sonnet")
        self.assertEqual(data["messages_count"], 50)

    def test_clear_recovery(self):
        save_crash_recovery("sess456", "/tmp", "gpt-4", 10)
        self.assertIsNotNone(check_crash_recovery())
        clear_crash_recovery()
        self.assertIsNone(check_crash_recovery())

    def test_no_recovery_when_empty(self):
        self.assertIsNone(check_crash_recovery())

    def test_stale_recovery_ignored(self):
        """Recovery mais velha que 24h deve ser ignorada."""
        data = {
            "session_id": "old",
            "cwd": "/tmp",
            "model": "test",
            "messages_count": 1,
            "timestamp": time.time() - 90000,  # > 24h atras
            "pid": 99999999,
        }
        with open(CRASH_RECOVERY_FILE, "w") as f:
            json.dump(data, f)
        self.assertIsNone(check_crash_recovery())


class TestProcessAlive(unittest.TestCase):
    """Testes de verificacao de processo."""

    def test_current_process_alive(self):
        self.assertTrue(_is_process_alive(os.getpid()))

    def test_invalid_pid(self):
        self.assertFalse(_is_process_alive(0))
        self.assertFalse(_is_process_alive(-1))

    def test_nonexistent_pid(self):
        # PID muito alto provavelmente nao existe
        self.assertFalse(_is_process_alive(99999999))


class TestLockFile(unittest.TestCase):
    """Testes de lock file."""

    def tearDown(self):
        _release_lock()

    def test_acquire_lock(self):
        result = acquire_lock()
        self.assertTrue(result)
        self.assertTrue(LOCK_FILE.exists())

    def test_release_lock(self):
        acquire_lock()
        _release_lock()
        self.assertFalse(LOCK_FILE.exists())


class TestShutdownHandlers(unittest.TestCase):
    """Testes de registro de handlers."""

    def test_register_handler(self):
        called = []
        register_shutdown_handler(lambda: called.append(True))
        # Handler registrado mas nao executado ainda
        self.assertEqual(len(called), 0)


if __name__ == "__main__":
    unittest.main()
