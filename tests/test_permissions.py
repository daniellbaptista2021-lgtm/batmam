"""Testes do sistema de permissoes em 5 camadas."""

import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from clow.permissions import (
    PermissionLevel, get_tool_requirement, needs_confirmation,
    is_tool_allowed, is_dangerous_command, classify_bash_command,
    classify_action, TOOL_REQUIREMENTS, PERMISSION_MODES,
)


class TestPermissionLevels(unittest.TestCase):
    """Testes dos 5 niveis de permissao."""

    def test_level_ordering(self):
        self.assertLess(PermissionLevel.READ_ONLY, PermissionLevel.WORKSPACE_WRITE)
        self.assertLess(PermissionLevel.WORKSPACE_WRITE, PermissionLevel.PROMPT)
        self.assertLess(PermissionLevel.PROMPT, PermissionLevel.DANGER_FULL_ACCESS)
        self.assertLess(PermissionLevel.DANGER_FULL_ACCESS, PermissionLevel.ALLOW)

    def test_level_values(self):
        self.assertEqual(PermissionLevel.READ_ONLY, 0)
        self.assertEqual(PermissionLevel.ALLOW, 4)

    def test_mode_mapping(self):
        self.assertEqual(PERMISSION_MODES["readonly"], PermissionLevel.READ_ONLY)
        self.assertEqual(PERMISSION_MODES["default"], PermissionLevel.PROMPT)
        self.assertEqual(PERMISSION_MODES["allow"], PermissionLevel.ALLOW)
        self.assertEqual(PERMISSION_MODES["danger"], PermissionLevel.DANGER_FULL_ACCESS)


class TestToolRequirements(unittest.TestCase):
    """Testes de requisitos de ferramentas."""

    def test_read_tools_are_readonly(self):
        for tool in ("read", "glob", "grep", "web_search", "web_fetch", "task_list", "task_get"):
            self.assertEqual(
                get_tool_requirement(tool), PermissionLevel.READ_ONLY,
                f"{tool} deveria ser READ_ONLY"
            )

    def test_write_tools_are_workspace(self):
        for tool in ("write", "edit", "notebook_edit", "task_create"):
            self.assertEqual(
                get_tool_requirement(tool), PermissionLevel.WORKSPACE_WRITE,
                f"{tool} deveria ser WORKSPACE_WRITE"
            )

    def test_dangerous_tools_are_full_access(self):
        for tool in ("bash", "docker_manage", "supabase_query"):
            self.assertEqual(
                get_tool_requirement(tool), PermissionLevel.DANGER_FULL_ACCESS,
                f"{tool} deveria ser DANGER_FULL_ACCESS"
            )

    def test_unknown_tool_defaults_to_danger(self):
        self.assertEqual(
            get_tool_requirement("unknown_tool"),
            PermissionLevel.DANGER_FULL_ACCESS,
        )


class TestNeedsConfirmation(unittest.TestCase):
    """Testes da funcao needs_confirmation."""

    def test_read_tools_never_need_confirmation(self):
        for tool in ("read", "glob", "grep", "task_list", "task_get"):
            self.assertFalse(needs_confirmation(tool, {}))

    def test_web_tools_free(self):
        self.assertFalse(needs_confirmation("web_search", {}))
        self.assertFalse(needs_confirmation("web_fetch", {}))

    def test_agent_tool_free(self):
        self.assertFalse(needs_confirmation("agent", {}))

    def test_external_tools_need_confirmation(self):
        for tool in ("whatsapp_send", "docker_manage", "supabase_query"):
            self.assertTrue(needs_confirmation(tool, {}))


class TestDangerousCommands(unittest.TestCase):
    """Testes de deteccao de comandos perigosos."""

    def test_dangerous_patterns(self):
        self.assertTrue(is_dangerous_command("rm -rf /"))
        self.assertTrue(is_dangerous_command("git push --force"))
        self.assertTrue(is_dangerous_command("drop table users"))
        self.assertTrue(is_dangerous_command("shutdown now"))

    def test_safe_commands(self):
        self.assertFalse(is_dangerous_command("ls -la"))
        self.assertFalse(is_dangerous_command("git status"))
        self.assertFalse(is_dangerous_command("echo hello"))


class TestBashClassification(unittest.TestCase):
    """Testes de classificacao de comandos bash."""

    def test_safe_commands(self):
        for cmd in ("ls -la", "cat file.txt", "git status", "pwd", "echo hi"):
            self.assertEqual(classify_bash_command(cmd), "safe", f"{cmd} deveria ser safe")

    def test_write_commands(self):
        for cmd in ("git add .", "git commit -m x", "pip install flask", "mkdir dir"):
            self.assertEqual(classify_bash_command(cmd), "write", f"{cmd} deveria ser write")

    def test_dangerous_commands(self):
        for cmd in ("rm file", "git push origin main", "kill 1234"):
            self.assertEqual(classify_bash_command(cmd), "dangerous", f"{cmd} deveria ser dangerous")

    def test_blocked_commands(self):
        self.assertEqual(classify_bash_command("rm -rf /"), "blocked")


class TestActionClassification(unittest.TestCase):
    """Testes de classificacao completa de acoes."""

    def test_read_action(self):
        result = classify_action("read", {})
        self.assertEqual(result["level"], "safe")
        self.assertTrue(result["reversible"])
        self.assertFalse(result["external"])

    def test_bash_action_classification(self):
        safe = classify_action("bash", {"command": "ls -la"})
        self.assertEqual(safe["level"], "safe")

        dangerous = classify_action("bash", {"command": "rm -rf /tmp"})
        self.assertIn(dangerous["level"], ("dangerous", "blocked"))

    def test_external_action(self):
        result = classify_action("whatsapp_send", {})
        self.assertTrue(result["external"])
        self.assertFalse(result["reversible"])


if __name__ == "__main__":
    unittest.main()
