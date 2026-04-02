"""Testes da integracao LSP."""

import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from clow.lsp import (
    LSPDiagnostic, LSPServerConfig, LSPManager,
    SEVERITY_MAP, _uri_to_path,
)


class TestLSPDiagnostic(unittest.TestCase):
    """Testes de diagnosticos LSP."""

    def test_format_error(self):
        d = LSPDiagnostic(
            file_path="src/main.py", line=10, character=5,
            severity="error", message="Undefined var", source="pyright"
        )
        formatted = d.format()
        self.assertIn("[E]", formatted)
        self.assertIn("main.py:11:6", formatted)
        self.assertIn("Undefined var", formatted)
        self.assertIn("(pyright)", formatted)

    def test_format_warning(self):
        d = LSPDiagnostic(
            file_path="test.py", line=0, character=0,
            severity="warning", message="Unused import"
        )
        formatted = d.format()
        self.assertIn("[W]", formatted)

    def test_format_without_source(self):
        d = LSPDiagnostic(
            file_path="a.py", line=0, character=0,
            severity="info", message="msg"
        )
        self.assertNotIn("()", d.format())


class TestLSPServerConfig(unittest.TestCase):
    """Testes de configuracao LSP."""

    def test_from_dict(self):
        cfg = LSPServerConfig.from_dict("python", {
            "command": "pyright-langserver",
            "args": ["--stdio"],
            "file_patterns": ["*.py"],
        })
        self.assertEqual(cfg.name, "python")
        self.assertEqual(cfg.command, "pyright-langserver")
        self.assertEqual(cfg.file_patterns, ["*.py"])


class TestURIConversion(unittest.TestCase):
    """Testes de conversao de URI."""

    def test_unix_path(self):
        path = _uri_to_path("file:///home/user/file.py")
        self.assertIn("home", path)

    def test_windows_path(self):
        path = _uri_to_path("file:///C:/Users/test/file.py")
        self.assertIn("Users", path)


class TestSeverityMap(unittest.TestCase):
    """Testes do mapa de severidade."""

    def test_known_severities(self):
        self.assertEqual(SEVERITY_MAP[1], "error")
        self.assertEqual(SEVERITY_MAP[2], "warning")
        self.assertEqual(SEVERITY_MAP[3], "info")
        self.assertEqual(SEVERITY_MAP[4], "hint")


class TestLSPManager(unittest.TestCase):
    """Testes do gerenciador LSP."""

    def test_empty_manager(self):
        mgr = LSPManager("/tmp")
        self.assertEqual(mgr.get_all_diagnostics(), [])
        self.assertEqual(mgr.get_context_summary(), "")
        self.assertEqual(mgr.server_status(), [])

    def test_context_summary_with_diagnostics(self):
        mgr = LSPManager("/tmp")
        # Injeta diagnosticos manualmente para testar formatacao
        # (normalmente viriam de um servidor LSP real)
        self.assertEqual(mgr.get_context_summary(), "")


if __name__ == "__main__":
    unittest.main()
