"""Testes do sistema de configuracao hierarquica."""

import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from clow.config import _deep_merge, load_settings


class TestDeepMerge(unittest.TestCase):
    """Testes do deep merge hierarquico."""

    def test_simple_merge(self):
        result = _deep_merge({"a": 1}, {"b": 2})
        self.assertEqual(result, {"a": 1, "b": 2})

    def test_override(self):
        result = _deep_merge({"a": 1}, {"a": 2})
        self.assertEqual(result, {"a": 2})

    def test_nested_merge(self):
        base = {"nested": {"x": 10, "y": 20}}
        override = {"nested": {"y": 99, "z": 30}}
        result = _deep_merge(base, override)
        self.assertEqual(result["nested"], {"x": 10, "y": 99, "z": 30})

    def test_array_replacement(self):
        result = _deep_merge({"arr": [1, 2]}, {"arr": [3]})
        self.assertEqual(result["arr"], [3])

    def test_empty_base(self):
        result = _deep_merge({}, {"a": 1})
        self.assertEqual(result, {"a": 1})

    def test_empty_override(self):
        result = _deep_merge({"a": 1}, {})
        self.assertEqual(result, {"a": 1})

    def test_deep_nested(self):
        base = {"a": {"b": {"c": 1}}}
        override = {"a": {"b": {"d": 2}}}
        result = _deep_merge(base, override)
        self.assertEqual(result["a"]["b"], {"c": 1, "d": 2})

    def test_base_not_mutated(self):
        base = {"a": {"x": 1}}
        override = {"a": {"y": 2}}
        _deep_merge(base, override)
        self.assertNotIn("y", base["a"])


class TestLoadSettings(unittest.TestCase):
    """Testes de carregamento de settings."""

    def test_returns_dict(self):
        result = load_settings()
        self.assertIsInstance(result, dict)


if __name__ == "__main__":
    unittest.main()
