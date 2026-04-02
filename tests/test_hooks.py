"""Testes do sistema de hooks com protocolo exit-code."""

import unittest
import sys
import os
import platform

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from clow.hooks import Hook, HookRunner, HookResult, EXIT_ALLOW, EXIT_DENY


class TestHookExitCodeProtocol(unittest.TestCase):
    """Testes do protocolo exit-code (0=allow, 2=deny, outro=warn)."""

    def test_exit_constants(self):
        self.assertEqual(EXIT_ALLOW, 0)
        self.assertEqual(EXIT_DENY, 2)

    def test_allow_result(self):
        h = Hook(event="pre_tool_call", command="echo ok")
        r = HookResult(hook=h, success=True, output="ok", error="", return_code=0, action="allow")
        self.assertFalse(r.blocked)
        self.assertFalse(r.is_warning)
        self.assertEqual(r.action, "allow")

    def test_deny_result(self):
        h = Hook(event="pre_tool_call", command="exit 2")
        r = HookResult(hook=h, success=False, output="negado", error="", return_code=2, action="deny")
        self.assertTrue(r.blocked)
        self.assertFalse(r.is_warning)
        self.assertIn("DENIED", r.feedback)

    def test_warn_result(self):
        h = Hook(event="pre_tool_call", command="exit 1")
        r = HookResult(hook=h, success=False, output="cuidado", error="", return_code=1, action="warn")
        self.assertFalse(r.blocked)
        self.assertTrue(r.is_warning)
        self.assertIn("WARNING", r.feedback)

    def test_legacy_stop_on_failure(self):
        h = Hook(event="pre_tool_call", command="false", stop_on_failure=True)
        r = HookResult(hook=h, success=False, output="", error="fail", return_code=1, action="warn")
        # Legado: stop_on_failure=True + not success = blocked
        self.assertTrue(r.blocked)

    def test_feedback_formatting(self):
        h = Hook(event="test", command="echo")
        # Allow com output
        r1 = HookResult(hook=h, success=True, output="msg", error="", return_code=0, action="allow")
        self.assertEqual(r1.feedback, "msg")

        # Deny com output
        r2 = HookResult(hook=h, success=False, output="motivo", error="", return_code=2, action="deny")
        self.assertIn("[hook DENIED]", r2.feedback)

        # Warn com output
        r3 = HookResult(hook=h, success=False, output="aviso", error="", return_code=1, action="warn")
        self.assertIn("[hook WARNING]", r3.feedback)


class TestHookExecution(unittest.TestCase):
    """Testes de execucao real de hooks."""

    @unittest.skipIf(platform.system() == "Windows", "Shell commands differ on Windows")
    def test_hook_allow_exit_0(self):
        h = Hook(event="test", command="echo 'aprovado'", timeout=5)
        runner = HookRunner.__new__(HookRunner)
        runner._hooks = {"test": [h]}
        results = runner.run_hooks("test")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].action, "allow")
        self.assertIn("aprovado", results[0].output)

    def test_hook_timeout(self):
        # Usa ping com timeout longo que funciona em Windows e Linux
        if os.name == "nt":
            cmd = "ping -n 10 127.0.0.1"
        else:
            cmd = "sleep 10"
        h = Hook(event="pre_turn", command=cmd, timeout=1)
        runner = HookRunner.__new__(HookRunner)
        runner._hooks = {e: [] for e in HookRunner.VALID_EVENTS}
        runner._hooks["pre_turn"] = [h]
        results = runner.run_hooks("pre_turn")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].action, "warn")  # Timeout = warn
        self.assertIn("expirou", results[0].error)

    def test_invalid_event(self):
        runner = HookRunner.__new__(HookRunner)
        runner._hooks = {e: [] for e in HookRunner.VALID_EVENTS}
        results = runner.run_hooks("invalid_event")
        self.assertEqual(results, [])

    def test_tool_filter(self):
        h = Hook(event="pre_tool_call", command="echo ok", tool="bash")
        runner = HookRunner.__new__(HookRunner)
        runner._hooks = {"pre_tool_call": [h]}

        # Deve filtrar: tool_name != bash
        results = runner.run_hooks("pre_tool_call", {"tool_name": "write"})
        self.assertEqual(len(results), 0)


class TestHookDataclass(unittest.TestCase):
    """Testes de serialização do Hook."""

    def test_from_dict(self):
        h = Hook.from_dict({
            "event": "pre_turn",
            "command": "echo test",
            "tool": "bash",
            "enabled": True,
            "timeout": 10,
        })
        self.assertEqual(h.event, "pre_turn")
        self.assertEqual(h.command, "echo test")
        self.assertEqual(h.tool, "bash")
        self.assertEqual(h.timeout, 10)

    def test_to_dict(self):
        h = Hook(event="post_turn", command="echo done", tool="", timeout=30)
        d = h.to_dict()
        self.assertEqual(d["event"], "post_turn")
        self.assertEqual(d["command"], "echo done")

    def test_roundtrip(self):
        h = Hook(event="on_error", command="notify.sh", tool="bash", timeout=15)
        d = h.to_dict()
        h2 = Hook.from_dict(d)
        self.assertEqual(h.event, h2.event)
        self.assertEqual(h.command, h2.command)
        self.assertEqual(h.tool, h2.tool)


if __name__ == "__main__":
    unittest.main()
