"""Testes de integracao end-to-end do Clow.

Testa fluxos completos que envolvem multiplos modulos.
"""

import unittest
import sys
import os
import json
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestConfigIntegration(unittest.TestCase):
    """Testa que config hierarquico funciona com outros modulos."""

    def test_settings_affects_permissions(self):
        from clow.config import load_settings
        from clow.permissions import get_current_level, PermissionLevel

        # Default mode deve ser PROMPT
        level = get_current_level()
        self.assertIsInstance(level, PermissionLevel)

    def test_settings_affects_hooks(self):
        from clow.hooks import HookRunner
        runner = HookRunner()
        # Deve carregar sem erro mesmo sem hooks configurados
        self.assertIsInstance(runner.list_hooks(), dict)


class TestContextIntegration(unittest.TestCase):
    """Testa contexto com projetos reais."""

    def test_loads_from_real_project(self):
        from clow.context import load_project_context

        # O diretorio pai tem CLAUDE.md
        parent = str(Path(__file__).parent.parent.parent)
        ctx = load_project_context(parent)
        # Pode ou nao encontrar, mas nao deve crashar
        self.assertIsInstance(ctx, str)

    def test_context_with_multiple_files(self):
        from clow.context import load_project_context

        with tempfile.TemporaryDirectory() as tmpdir:
            # Cria CLOW.md e CLOW.local.md
            (Path(tmpdir) / "CLOW.md").write_text("# Main Config", encoding="utf-8")
            (Path(tmpdir) / "CLOW.local.md").write_text("# Local Override", encoding="utf-8")

            ctx = load_project_context(tmpdir)
            self.assertIn("Main Config", ctx)
            self.assertIn("Local Override", ctx)


class TestPermissionsIntegration(unittest.TestCase):
    """Testa permissoes com classificacao de comandos."""

    def test_safe_bash_commands_auto_approve(self):
        from clow.permissions import classify_bash_command, classify_action

        # Comandos safe devem ser classificados corretamente
        safe_cmds = ["ls -la", "git status", "echo hello", "pwd"]
        for cmd in safe_cmds:
            result = classify_bash_command(cmd)
            self.assertEqual(result, "safe", f"{cmd} deveria ser safe")

        # Acao completa
        action = classify_action("bash", {"command": "ls"})
        self.assertEqual(action["level"], "safe")

    def test_dangerous_commands_blocked(self):
        from clow.permissions import classify_bash_command

        dangerous = ["rm -rf /tmp/x", "git push --force", "kill 1234"]
        for cmd in dangerous:
            result = classify_bash_command(cmd)
            self.assertIn(result, ("dangerous", "blocked"), f"{cmd} deveria ser dangerous/blocked")


class TestSandboxIntegration(unittest.TestCase):
    """Testa sandbox com comandos reais."""

    def test_echo_command(self):
        from clow.sandbox import Sandbox
        s = Sandbox()
        result = s.execute("echo integration_test")
        self.assertEqual(result.return_code, 0)
        self.assertIn("integration_test", result.stdout)

    def test_blocked_command_rejected(self):
        from clow.sandbox import Sandbox
        s = Sandbox()
        result = s.execute("rm -rf /")
        self.assertNotEqual(result.return_code, 0)

    def test_timeout_enforcement(self):
        from clow.sandbox import Sandbox
        s = Sandbox()
        result = s.execute("ping -n 10 127.0.0.1" if os.name == "nt" else "sleep 10", timeout=1)
        self.assertTrue(result.timed_out)


class TestPluginSystemIntegration(unittest.TestCase):
    """Testa sistema de plugins com manifesto."""

    def test_create_plugin_with_manifest(self):
        from clow.plugins import PluginManifest

        with tempfile.TemporaryDirectory() as tmpdir:
            # Cria plugin com manifesto
            plugin_dir = Path(tmpdir) / "test-plugin"
            plugin_dir.mkdir()

            manifest = {
                "name": "test-plugin",
                "version": "1.0.0",
                "description": "Plugin de teste",
                "entry_point": "main.py",
                "permissions": ["read"],
            }
            (plugin_dir / "plugin.json").write_text(json.dumps(manifest))
            (plugin_dir / "main.py").write_text("def register(registry, hooks): pass")

            m = PluginManifest.from_file(plugin_dir / "plugin.json")
            self.assertEqual(m.name, "test-plugin")
            self.assertEqual(m.validate(), [])


class TestMCPIntegration(unittest.TestCase):
    """Testa MCP com diferentes transportes."""

    def test_config_parsing_all_transports(self):
        from clow.mcp import MCPServerConfig

        configs = {
            "stdio": {"command": "tool", "transport": "stdio"},
            "sse": {"url": "https://example.com/sse", "transport": "sse"},
            "http": {"url": "https://example.com/api", "transport": "http"},
        }

        for name, data in configs.items():
            cfg = MCPServerConfig.from_dict(name, data)
            self.assertEqual(cfg.transport, name)


class TestSessionPersistence(unittest.TestCase):
    """Testa persistencia de sessao."""

    def test_session_model(self):
        from clow.models import Session

        s = Session(cwd="/tmp", model="test-model")
        self.assertGreater(len(s.id), 0)
        self.assertEqual(s.cwd, "/tmp")
        self.assertEqual(s.model, "test-model")


class TestToolRegistry(unittest.TestCase):
    """Testa registro de ferramentas."""

    def test_default_registry_has_tools(self):
        from clow.tools.base import create_default_registry

        registry = create_default_registry()
        names = registry.names()
        self.assertGreater(len(names), 10)

        # Tools essenciais devem existir
        essential = ["bash", "read", "write", "edit", "glob", "grep"]
        for tool in essential:
            self.assertIn(tool, names, f"Tool essencial '{tool}' faltando")

    def test_tool_has_schema(self):
        from clow.tools.base import create_default_registry

        registry = create_default_registry()
        for name in ["bash", "read", "write", "edit"]:
            tool = registry.get(name)
            self.assertIsNotNone(tool, f"Tool {name} nao encontrada")
            schema = tool.get_schema()
            self.assertIsInstance(schema, dict)
            self.assertIn("properties", schema)


class TestMemorySystem(unittest.TestCase):
    """Testa sistema de memoria."""

    def test_list_memories(self):
        from clow.memory import list_memories
        memories = list_memories()
        self.assertIsInstance(memories, list)

    def test_save_and_list(self):
        from clow.memory import save_memory, list_memories, delete_memory
        import time

        name = f"test_integration_{int(time.time())}"
        try:
            save_memory(name, "Conteudo de teste", memory_type="general")
            memories = list_memories()
            names = [m["name"] for m in memories]
            self.assertIn(name, names)
        finally:
            delete_memory(name)


if __name__ == "__main__":
    unittest.main()
