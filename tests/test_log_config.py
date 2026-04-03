"""Testes do logging estruturado (log_config.py)."""

import unittest
import sys
import os
import json
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from clow.log_config import JSONFormatter, get_logger


class TestJSONFormatter(unittest.TestCase):
    """Testes do formatter JSON."""

    def test_format_returns_json(self):
        fmt = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO,
            pathname="test.py", lineno=1,
            msg="hello world", args=(), exc_info=None,
        )
        output = fmt.format(record)
        data = json.loads(output)
        self.assertEqual(data["message"], "hello world")
        self.assertEqual(data["level"], "INFO")

    def test_format_includes_extra_fields(self):
        fmt = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO,
            pathname="test.py", lineno=1,
            msg="action", args=(), exc_info=None,
        )
        record.action = "user_login"
        record.user_id = "u123"
        output = fmt.format(record)
        data = json.loads(output)
        self.assertEqual(data["action"], "user_login")
        self.assertEqual(data["user_id"], "u123")


class TestGetLogger(unittest.TestCase):

    def test_returns_named_logger(self):
        lg = get_logger("test_mod")
        self.assertEqual(lg.name, "clow.test_mod")


if __name__ == "__main__":
    unittest.main()
