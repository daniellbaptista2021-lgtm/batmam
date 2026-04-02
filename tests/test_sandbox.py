"""Testes do sandbox com deteccao de container."""

import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from clow.sandbox import (
    Sandbox, IsolationMode, ContainerInfo,
    detect_container, BLOCKED_PATTERNS, DANGEROUS_PATTERNS,
)


class TestContainerDetection(unittest.TestCase):
    """Testes de deteccao de container."""

    def test_returns_container_info(self):
        info = detect_container()
        self.assertIsInstance(info, ContainerInfo)

    def test_has_required_fields(self):
        info = detect_container()
        self.assertIsInstance(info.is_container, bool)
        self.assertIsInstance(info.runtime, str)
        self.assertIsInstance(info.details, str)


class TestIsolationModes(unittest.TestCase):
    """Testes dos modos de isolamento."""

    def test_off_allows_everything(self):
        s = Sandbox(cwd="/tmp", isolation=IsolationMode.OFF)
        self.assertIsNone(s._check_isolation("ls", "/anywhere"))

    def test_workspace_allows_inside(self):
        s = Sandbox(cwd=os.getcwd(), isolation=IsolationMode.WORKSPACE_ONLY)
        subdir = os.path.join(os.getcwd(), "sub")
        self.assertIsNone(s._check_isolation("ls", os.getcwd()))

    def test_workspace_blocks_outside(self):
        s = Sandbox(cwd=os.getcwd(), isolation=IsolationMode.WORKSPACE_ONLY)
        # Tenta executar fora do workspace
        outside = os.path.dirname(os.getcwd())
        # So bloqueia se de fato e diferente
        if outside != os.getcwd():
            result = s._check_isolation("ls", outside)
            self.assertIsNotNone(result)

    def test_allowlist_mode(self):
        allowed = [os.getcwd()]
        s = Sandbox(cwd=os.getcwd(), isolation=IsolationMode.ALLOWLIST, allowed_dirs=allowed)
        self.assertIsNone(s._check_isolation("ls", os.getcwd()))


class TestSandboxBlocking(unittest.TestCase):
    """Testes de bloqueio de comandos."""

    def test_blocked_commands(self):
        s = Sandbox()
        self.assertIsNotNone(s.is_blocked("rm -rf /"))
        self.assertIsNotNone(s.is_blocked("dd if=/dev/zero of=/dev/sda"))
        self.assertIsNotNone(s.is_blocked(":(){:|:&};:"))

    def test_safe_commands_not_blocked(self):
        s = Sandbox()
        self.assertIsNone(s.is_blocked("ls -la"))
        self.assertIsNone(s.is_blocked("echo hello"))
        self.assertIsNone(s.is_blocked("git status"))

    def test_dangerous_detection(self):
        s = Sandbox()
        self.assertTrue(s.is_dangerous("rm -rf /tmp"))
        self.assertTrue(s.is_dangerous("git push --force"))
        self.assertFalse(s.is_dangerous("ls"))

    def test_execute_blocked(self):
        s = Sandbox()
        result = s.execute("rm -rf /")
        self.assertNotEqual(result.return_code, 0)
        self.assertIn("bloqueado", result.stderr)


class TestSandboxExecution(unittest.TestCase):
    """Testes de execucao no sandbox."""

    def test_simple_command(self):
        s = Sandbox()
        result = s.execute("echo hello")
        self.assertEqual(result.return_code, 0)
        self.assertIn("hello", result.stdout)

    def test_timeout(self):
        s = Sandbox()
        result = s.execute("sleep 10", timeout=1)
        self.assertTrue(result.timed_out)
        self.assertEqual(result.return_code, -1)

    def test_duration_tracked(self):
        s = Sandbox()
        result = s.execute("echo fast")
        self.assertGreater(result.duration, 0)


if __name__ == "__main__":
    unittest.main()
