"""Testes do sistema MCP com multiplos transportes."""

import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from clow.mcp import (
    MCPServerConfig, MCPServer, MCPSSEServer, MCPHTTPServer,
    MCPManager, MCPToolProxy, _format_mcp_response,
)


class TestMCPServerConfig(unittest.TestCase):
    """Testes de configuracao MCP."""

    def test_stdio_config(self):
        cfg = MCPServerConfig.from_dict("test", {"command": "echo", "transport": "stdio"})
        self.assertEqual(cfg.transport, "stdio")
        self.assertEqual(cfg.command, "echo")

    def test_sse_config(self):
        cfg = MCPServerConfig.from_dict("remote", {
            "url": "https://example.com/sse",
            "transport": "sse",
            "headers": {"Authorization": "Bearer xxx"},
        })
        self.assertEqual(cfg.transport, "sse")
        self.assertEqual(cfg.url, "https://example.com/sse")
        self.assertEqual(cfg.headers["Authorization"], "Bearer xxx")

    def test_http_config(self):
        cfg = MCPServerConfig.from_dict("api", {
            "url": "https://example.com/api",
            "transport": "http",
        })
        self.assertEqual(cfg.transport, "http")

    def test_default_transport_is_stdio(self):
        cfg = MCPServerConfig.from_dict("default", {"command": "tool"})
        self.assertEqual(cfg.transport, "stdio")

    def test_enabled_default(self):
        cfg = MCPServerConfig.from_dict("test", {})
        self.assertTrue(cfg.enabled)


class TestMCPResponseFormatting(unittest.TestCase):
    """Testes de formatacao de resposta MCP."""

    def test_text_content(self):
        resp = {"content": [{"type": "text", "text": "Hello"}]}
        self.assertEqual(_format_mcp_response(resp), "Hello")

    def test_image_content(self):
        resp = {"content": [{"type": "image", "mimeType": "image/png"}]}
        self.assertIn("imagem", _format_mcp_response(resp))

    def test_multiple_content(self):
        resp = {"content": [
            {"type": "text", "text": "A"},
            {"type": "text", "text": "B"},
        ]}
        result = _format_mcp_response(resp)
        self.assertIn("A", result)
        self.assertIn("B", result)

    def test_no_content(self):
        resp = {"data": "raw"}
        result = _format_mcp_response(resp)
        self.assertIn("data", result)


class TestMCPManager(unittest.TestCase):
    """Testes do gerenciador MCP."""

    def test_empty_manager(self):
        mgr = MCPManager()
        self.assertEqual(mgr.server_status(), [])

    def test_stop_all_empty(self):
        mgr = MCPManager()
        mgr.stop_all()  # Nao deve falhar


if __name__ == "__main__":
    unittest.main()
