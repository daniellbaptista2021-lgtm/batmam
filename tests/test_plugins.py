"""Testes do sistema de plugins com manifesto."""

import unittest
import sys
import os
import tempfile
import json
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from clow.plugins import PluginManifest, PluginManager


class TestPluginManifest(unittest.TestCase):
    """Testes do manifesto de plugin."""

    def test_create_manifest(self):
        m = PluginManifest(name="test", version="1.0.0", description="Test plugin")
        self.assertEqual(m.name, "test")
        self.assertEqual(m.version, "1.0.0")

    def test_validate_valid(self):
        m = PluginManifest(name="test", version="1.0.0")
        self.assertEqual(m.validate(), [])

    def test_validate_missing_name(self):
        m = PluginManifest(name="", version="1.0.0")
        errors = m.validate()
        self.assertGreater(len(errors), 0)

    def test_to_dict(self):
        m = PluginManifest(name="test", version="2.0", description="Desc", tools=["MyTool"])
        d = m.to_dict()
        self.assertEqual(d["name"], "test")
        self.assertEqual(d["version"], "2.0")
        self.assertEqual(d["tools"], ["MyTool"])

    def test_from_dict(self):
        data = {
            "name": "meu-plugin",
            "version": "1.2.3",
            "description": "Plugin legal",
            "entry_point": "init.py",
            "permissions": ["bash", "write"],
            "hooks": {"pre_tool_call": "check.sh"},
        }
        m = PluginManifest.from_dict(data)
        self.assertEqual(m.name, "meu-plugin")
        self.assertEqual(m.entry_point, "init.py")
        self.assertEqual(m.permissions, ["bash", "write"])
        self.assertEqual(m.hooks, {"pre_tool_call": "check.sh"})

    def test_roundtrip(self):
        m = PluginManifest(
            name="roundtrip", version="3.0", description="Test",
            tools=["A", "B"], hooks={"on_start": "start.sh"}
        )
        d = m.to_dict()
        m2 = PluginManifest.from_dict(d)
        self.assertEqual(m.name, m2.name)
        self.assertEqual(m.tools, m2.tools)
        self.assertEqual(m.hooks, m2.hooks)

    def test_from_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "plugin.json"
            manifest_path.write_text(json.dumps({
                "name": "file-test",
                "version": "1.0.0",
                "description": "From file",
            }))
            m = PluginManifest.from_file(manifest_path)
            self.assertEqual(m.name, "file-test")


class TestPluginManager(unittest.TestCase):
    """Testes do gerenciador de plugins."""

    def test_empty_manager(self):
        pm = PluginManager()
        self.assertEqual(pm.loaded_count, 0)
        self.assertEqual(pm.error_count, 0)
        self.assertEqual(pm.list_plugins(), [])

    def test_uninstall_nonexistent(self):
        pm = PluginManager()
        success, msg = pm.uninstall("nonexistent")
        self.assertFalse(success)


if __name__ == "__main__":
    unittest.main()
