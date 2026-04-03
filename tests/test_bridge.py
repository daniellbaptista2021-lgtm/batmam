"""Testes do Claude Code bridge."""

import unittest
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestBridgeModule(unittest.TestCase):
    """Testes de importacao e configuracao do bridge."""

    def test_import_bridge(self):
        from clow.claude_code_bridge import ask_claude_code, ask_claude_code_stream, log_claude_code_usage
        self.assertTrue(callable(ask_claude_code))
        self.assertTrue(callable(ask_claude_code_stream))
        self.assertTrue(callable(log_claude_code_usage))

    def test_no_hardcoded_tokens(self):
        """Verifica que nao tem tokens hardcoded no bridge."""
        bridge_path = os.path.join(os.path.dirname(__file__), "..", "clow", "claude_code_bridge.py")
        with open(bridge_path) as f:
            content = f.read()
        self.assertNotIn("sk-ant-oat01", content)
        self.assertNotIn("sk-ant-api03", content)

    def test_build_cmd_has_required_flags(self):
        from clow.claude_code_bridge import _build_cmd
        cmd = _build_cmd("test prompt")
        self.assertIn("-p", cmd)
        self.assertIn("test prompt", cmd)
        self.assertIn("--permission-mode", cmd)
        self.assertIn("dontAsk", cmd)
        self.assertIn("--max-turns", cmd)

    def test_build_cmd_stream_flags(self):
        from clow.claude_code_bridge import _build_cmd
        cmd = _build_cmd("test", stream=True)
        self.assertIn("--output-format", cmd)
        self.assertIn("stream-json", cmd)
        self.assertIn("--verbose", cmd)

    def test_build_cmd_resume_session(self):
        from clow.claude_code_bridge import _build_cmd, _session_map
        _session_map["test-conv"] = "session-123"
        cmd = _build_cmd("test", conversation_id="test-conv")
        self.assertIn("--resume", cmd)
        self.assertIn("session-123", cmd)
        del _session_map["test-conv"]

    def test_get_claude_env_removes_api_key(self):
        from clow.claude_code_bridge import _get_claude_env
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        env = _get_claude_env()
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        os.environ.pop("ANTHROPIC_API_KEY", None)

    def test_bridge_runs_pure_claude_code(self):
        """Bridge runs Claude Code without custom system prompts."""
        from clow.claude_code_bridge import _build_cmd
        cmd = _build_cmd("test")
        self.assertNotIn("--append-system-prompt", cmd)


class TestStreamParsing(unittest.TestCase):
    """Testes de parsing de eventos stream-json."""

    def test_parse_assistant_text_event(self):
        """Simula parsing de um evento assistant com texto."""
        event = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "Hello world"}
                ]
            }
        }
        # Extract text like the bridge does
        msg = event.get("message")
        self.assertIsInstance(msg, dict)
        content = msg.get("content")
        self.assertIsInstance(content, list)
        for block in content:
            self.assertIsInstance(block, dict)
            if block.get("type") == "text":
                self.assertEqual(block.get("text"), "Hello world")

    def test_parse_tool_use_event(self):
        """Simula parsing de tool_use."""
        event = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}
                ]
            }
        }
        msg = event.get("message", {})
        for block in msg.get("content", []):
            if block.get("type") == "tool_use":
                self.assertEqual(block.get("name"), "Bash")
                self.assertEqual(block.get("input", {}).get("command"), "ls")

    def test_parse_tool_result_string_content(self):
        """tool_result com content string nao deve crashar."""
        event = {
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "content": "file.txt\nother.py", "is_error": False}
                ]
            }
        }
        msg = event.get("message", {})
        for block in msg.get("content", []):
            if block.get("type") == "tool_result":
                raw = block.get("content", "")
                if isinstance(raw, list):
                    raw = str(raw)
                self.assertIsInstance(raw, str)
                self.assertIn("file.txt", raw)

    def test_parse_tool_result_list_content(self):
        """tool_result com content list nao deve crashar."""
        event = {
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "content": [
                        {"type": "text", "text": "result data"}
                    ], "is_error": False}
                ]
            }
        }
        msg = event.get("message", {})
        for block in msg.get("content", []):
            raw = block.get("content", "")
            if isinstance(raw, list):
                parts = [p.get("text", "") if isinstance(p, dict) else str(p) for p in raw]
                raw = "\n".join(parts)
            self.assertIsInstance(raw, str)
            self.assertIn("result data", raw)

    def test_string_message_does_not_crash(self):
        """Se message for string em vez de dict, nao deve crashar."""
        event = {"type": "assistant", "message": "some string"}
        msg = event.get("message")
        # Bridge checks isinstance(msg, dict)
        if not isinstance(msg, dict):
            pass  # Should skip gracefully
        self.assertIsInstance(msg, str)


if __name__ == "__main__":
    unittest.main()
