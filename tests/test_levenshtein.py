"""Testes da sugestao de comandos por Levenshtein."""

import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from clow.cli import _levenshtein_distance, suggest_slash_command, KNOWN_SLASH_COMMANDS


class TestLevenshteinDistance(unittest.TestCase):
    """Testes da funcao de distancia de Levenshtein."""

    def test_identical_strings(self):
        self.assertEqual(_levenshtein_distance("abc", "abc"), 0)

    def test_empty_strings(self):
        self.assertEqual(_levenshtein_distance("", ""), 0)

    def test_one_empty(self):
        self.assertEqual(_levenshtein_distance("abc", ""), 3)
        self.assertEqual(_levenshtein_distance("", "abc"), 3)

    def test_single_insertion(self):
        self.assertEqual(_levenshtein_distance("abc", "ab"), 1)

    def test_single_substitution(self):
        self.assertEqual(_levenshtein_distance("abc", "axc"), 1)

    def test_single_deletion(self):
        self.assertEqual(_levenshtein_distance("abc", "abcd"), 1)

    def test_classic_example(self):
        self.assertEqual(_levenshtein_distance("kitten", "sitting"), 3)

    def test_symmetry(self):
        self.assertEqual(
            _levenshtein_distance("abc", "xyz"),
            _levenshtein_distance("xyz", "abc"),
        )


class TestSlashCommandSuggestion(unittest.TestCase):
    """Testes de sugestao de slash commands."""

    def test_close_typo(self):
        self.assertEqual(suggest_slash_command("/comit"), "/commit")

    def test_missing_letter(self):
        self.assertEqual(suggest_slash_command("/hep"), "/help")

    def test_swapped_letters(self):
        self.assertEqual(suggest_slash_command("/exti"), "/exit")

    def test_extra_letter(self):
        self.assertEqual(suggest_slash_command("/toolss"), "/tools")

    def test_very_different_returns_none(self):
        self.assertIsNone(suggest_slash_command("/zzzzzzzzzzz"))

    def test_exact_match_returns_itself(self):
        self.assertEqual(suggest_slash_command("/help"), "/help")

    def test_known_commands_exist(self):
        self.assertIn("/help", KNOWN_SLASH_COMMANDS)
        self.assertIn("/exit", KNOWN_SLASH_COMMANDS)
        self.assertIn("/commit", KNOWN_SLASH_COMMANDS)
        self.assertIn("/tools", KNOWN_SLASH_COMMANDS)


if __name__ == "__main__":
    unittest.main()
