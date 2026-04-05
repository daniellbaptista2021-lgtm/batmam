"""Testes do CRM Auto Funnel — movimentacao automatica de leads."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestFunnelRules(unittest.TestCase):
    """Testes de regras do funil."""

    def test_default_rules_exist(self):
        from clow.crm_auto_funnel import DEFAULT_RULES
        for stage in ("novo", "contatado", "qualificado", "proposta"):
            self.assertIn(stage, DEFAULT_RULES)
            self.assertIn("move_to", DEFAULT_RULES[stage])
            self.assertIn("trigger", DEFAULT_RULES[stage])

    def test_default_rules_pipeline_order(self):
        from clow.crm_auto_funnel import DEFAULT_RULES
        self.assertEqual(DEFAULT_RULES["novo"]["move_to"], "contatado")
        self.assertEqual(DEFAULT_RULES["contatado"]["move_to"], "qualificado")
        self.assertEqual(DEFAULT_RULES["qualificado"]["move_to"], "proposta")
        self.assertEqual(DEFAULT_RULES["proposta"]["move_to"], "ganho")

    def test_get_rules_returns_default(self):
        from clow.crm_auto_funnel import get_rules
        rules = get_rules("nonexistent-tenant", "nonexistent-instance")
        self.assertIn("novo", rules)
        self.assertEqual(rules["novo"]["move_to"], "contatado")

    def test_set_and_get_custom_rules(self):
        from clow.crm_auto_funnel import set_rules, get_rules, _FUNNEL_DIR
        tenant = "test-tenant-rules"
        instance = "test-inst-rules"
        custom = {"novo": {"move_to": "proposta", "trigger": "custom trigger"}}
        try:
            set_rules(tenant, instance, custom)
            loaded = get_rules(tenant, instance)
            self.assertEqual(loaded["novo"]["move_to"], "proposta")
            self.assertEqual(loaded["novo"]["trigger"], "custom trigger")
        finally:
            import shutil
            shutil.rmtree(str(_FUNNEL_DIR / tenant), ignore_errors=True)


class TestFunnelEnableDisable(unittest.TestCase):
    """Testes de ativacao/desativacao do funil."""

    def test_disabled_by_default(self):
        from clow.crm_auto_funnel import is_enabled
        self.assertFalse(is_enabled("nonexistent", "nonexistent"))

    def test_enable_and_disable(self):
        from clow.crm_auto_funnel import is_enabled, set_enabled, _FUNNEL_DIR
        tenant = "test-tenant-enable"
        instance = "test-inst-enable"
        try:
            set_enabled(tenant, instance, True)
            self.assertTrue(is_enabled(tenant, instance))
            set_enabled(tenant, instance, False)
            self.assertFalse(is_enabled(tenant, instance))
        finally:
            import shutil
            shutil.rmtree(str(_FUNNEL_DIR / tenant), ignore_errors=True)


class TestSuggestions(unittest.TestCase):
    """Testes do sistema de sugestoes pendentes."""

    def test_no_suggestions_by_default(self):
        from clow.crm_auto_funnel import get_pending_suggestions
        self.assertEqual(get_pending_suggestions("x", "y"), [])

    def test_add_and_dismiss_suggestion(self):
        from clow.crm_auto_funnel import (
            add_suggestion, get_pending_suggestions, dismiss_suggestion, _FUNNEL_DIR
        )
        tenant = "test-tenant-sug"
        instance = "test-inst-sug"
        try:
            add_suggestion(tenant, instance, "lead1", "novo", "contatado", "respondeu", 0.7)
            sug = get_pending_suggestions(tenant, instance)
            self.assertEqual(len(sug), 1)
            self.assertEqual(sug[0]["lead_id"], "lead1")
            self.assertEqual(sug[0]["suggested_stage"], "contatado")

            dismiss_suggestion(tenant, instance, "lead1")
            sug = get_pending_suggestions(tenant, instance)
            self.assertEqual(len(sug), 0)
        finally:
            import shutil
            shutil.rmtree(str(_FUNNEL_DIR / tenant), ignore_errors=True)

    def test_duplicate_suggestion_replaces(self):
        from clow.crm_auto_funnel import add_suggestion, get_pending_suggestions, _FUNNEL_DIR
        tenant = "test-tenant-dup"
        instance = "test-inst-dup"
        try:
            add_suggestion(tenant, instance, "lead1", "novo", "contatado", "r1", 0.6)
            add_suggestion(tenant, instance, "lead1", "novo", "qualificado", "r2", 0.9)
            sug = get_pending_suggestions(tenant, instance)
            self.assertEqual(len(sug), 1)
            self.assertEqual(sug[0]["suggested_stage"], "qualificado")
        finally:
            import shutil
            shutil.rmtree(str(_FUNNEL_DIR / tenant), ignore_errors=True)


class TestProcessNewMessage(unittest.TestCase):
    """Testes do processamento de novas mensagens."""

    def test_skips_if_disabled(self):
        from clow.crm_auto_funnel import process_new_message
        # Nao deve levantar erro quando desabilitado
        process_new_message("t", "i", "lead1", "novo", [])

    def test_skips_terminal_statuses(self):
        from clow.crm_auto_funnel import process_new_message, set_enabled, _FUNNEL_DIR
        tenant = "test-tenant-skip"
        instance = "test-inst-skip"
        try:
            set_enabled(tenant, instance, True)
            # Status "ganho" e "perdido" sao terminais — nao devem processar
            process_new_message(tenant, instance, "lead1", "ganho", [{"role": "user", "content": "oi"}])
            process_new_message(tenant, instance, "lead1", "perdido", [{"role": "user", "content": "oi"}])
        finally:
            import shutil
            shutil.rmtree(str(_FUNNEL_DIR / tenant), ignore_errors=True)


class TestAnalyzeConversation(unittest.TestCase):
    """Testes da analise de conversas."""

    def test_returns_none_for_unknown_status(self):
        from clow.crm_auto_funnel import analyze_conversation, DEFAULT_RULES
        result = analyze_conversation("t", "l", "unknown_stage", [], DEFAULT_RULES)
        self.assertIsNone(result)

    def test_returns_none_for_empty_messages(self):
        from clow.crm_auto_funnel import analyze_conversation, DEFAULT_RULES
        result = analyze_conversation("t", "l", "novo", [], DEFAULT_RULES)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
