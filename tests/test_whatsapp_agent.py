"""Testes do WhatsApp Agent — instancias, mensagens, Z-API."""

import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestWhatsAppInstance(unittest.TestCase):
    """Testes do dataclass WhatsAppInstance."""

    def test_create_instance(self):
        from clow.whatsapp_agent import WhatsAppInstance
        inst = WhatsAppInstance(
            id="test123",
            tenant_id="tenant1",
            name="Meu WhatsApp",
            zapi_instance_id="zapi123",
            zapi_token="token123",
        )
        self.assertEqual(inst.id, "test123")
        self.assertEqual(inst.tenant_id, "tenant1")
        self.assertTrue(inst.active)
        self.assertTrue(inst.auto_reply_enabled)
        self.assertEqual(inst.context_size, 20)

    def test_webhook_url(self):
        from clow.whatsapp_agent import WhatsAppInstance
        inst = WhatsAppInstance(
            id="abc123", tenant_id="t1", name="Test",
            zapi_instance_id="z1", zapi_token="tk1",
        )
        self.assertIn("abc123", inst.webhook_url)
        self.assertTrue(inst.webhook_url.startswith("https://"))

    def test_to_dict_masks_token(self):
        from clow.whatsapp_agent import WhatsAppInstance
        inst = WhatsAppInstance(
            id="test1", tenant_id="t1", name="Test",
            zapi_instance_id="z1", zapi_token="supersecrettoken123",
        )
        d = inst.to_dict()
        self.assertNotEqual(d["zapi_token"], "supersecrettoken123")
        self.assertTrue(d["zapi_token"].endswith("..."))

    def test_to_dict_truncates_long_fields(self):
        from clow.whatsapp_agent import WhatsAppInstance
        inst = WhatsAppInstance(
            id="test1", tenant_id="t1", name="Test",
            zapi_instance_id="z1", zapi_token="tk",
            system_prompt="x" * 500,
            rag_text="y" * 500,
        )
        d = inst.to_dict()
        self.assertLessEqual(len(d["system_prompt"]), 200)
        self.assertTrue(d["rag_text"].endswith("..."))

    def test_save_and_load(self):
        from clow.whatsapp_agent import WhatsAppInstance, WA_BASE_DIR
        import shutil
        tenant = "test-save-tenant"
        inst = WhatsAppInstance(
            id="savetest", tenant_id=tenant, name="Save Test",
            zapi_instance_id="z1", zapi_token="tk1",
            system_prompt="Ola, sou um bot.",
        )
        try:
            inst.save()
            loaded = WhatsAppInstance.load(inst.instance_dir)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.id, "savetest")
            self.assertEqual(loaded.name, "Save Test")
            self.assertEqual(loaded.system_prompt, "Ola, sou um bot.")
        finally:
            shutil.rmtree(str(WA_BASE_DIR / tenant), ignore_errors=True)

    def test_load_nonexistent_returns_none(self):
        from clow.whatsapp_agent import WhatsAppInstance
        result = WhatsAppInstance.load(Path("/nonexistent/path"))
        self.assertIsNone(result)


class TestWhatsAppAgentManager(unittest.TestCase):
    """Testes do gerenciador de instancias."""

    def setUp(self):
        from clow.whatsapp_agent import WhatsAppAgentManager, WA_BASE_DIR
        self.manager = WhatsAppAgentManager()
        self.tenant = "test-manager-tenant"
        self.wa_base = WA_BASE_DIR

    def tearDown(self):
        import shutil
        shutil.rmtree(str(self.wa_base / self.tenant), ignore_errors=True)

    def test_create_instance(self):
        result = self.manager.create_instance(
            self.tenant, "Bot Vendas", "zapi1", "token1", "Sou um bot de vendas"
        )
        self.assertTrue(result.get("success"))
        self.assertIn("instance", result)
        self.assertEqual(result["instance"]["name"], "Bot Vendas")

    def test_get_instances_empty(self):
        instances = self.manager.get_instances("nonexistent-tenant-xyz")
        self.assertEqual(instances, [])

    def test_create_and_list_instances(self):
        self.manager.create_instance(self.tenant, "Bot 1", "z1", "t1")
        self.manager.create_instance(self.tenant, "Bot 2", "z2", "t2")
        instances = self.manager.get_instances(self.tenant)
        self.assertEqual(len(instances), 2)

    def test_update_instance(self):
        result = self.manager.create_instance(self.tenant, "Bot", "z1", "t1")
        inst_id = result["instance"]["id"]
        updated = self.manager.update_instance(inst_id, self.tenant, name="Bot Atualizado")
        self.assertTrue(updated.get("success"))
        self.assertEqual(updated["instance"]["name"], "Bot Atualizado")

    def test_update_nonexistent_instance(self):
        result = self.manager.update_instance("nonexistent", self.tenant, name="X")
        self.assertIn("error", result)

    def test_delete_instance(self):
        result = self.manager.create_instance(self.tenant, "Bot", "z1", "t1")
        inst_id = result["instance"]["id"]
        deleted = self.manager.delete_instance(inst_id, self.tenant)
        self.assertTrue(deleted)

    def test_delete_nonexistent_returns_false(self):
        self.assertFalse(self.manager.delete_instance("xxx", "yyy"))

    def test_get_instance_by_id(self):
        result = self.manager.create_instance(self.tenant, "Bot", "z1", "t1")
        inst_id = result["instance"]["id"]
        inst = self.manager.get_instance(inst_id, self.tenant)
        self.assertIsNotNone(inst)
        self.assertEqual(inst.name, "Bot")

    def test_get_instance_nonexistent(self):
        inst = self.manager.get_instance("xxx", "yyy")
        self.assertIsNone(inst)


class TestConversationHistory(unittest.TestCase):
    """Testes do historico de conversas."""

    def setUp(self):
        from clow.whatsapp_agent import WhatsAppAgentManager, WhatsAppInstance, WA_BASE_DIR
        self.manager = WhatsAppAgentManager()
        self.tenant = "test-conv-tenant"
        self.wa_base = WA_BASE_DIR
        result = self.manager.create_instance(self.tenant, "Bot", "z1", "t1")
        self.inst = self.manager.get_instance(result["instance"]["id"], self.tenant)

    def tearDown(self):
        import shutil
        shutil.rmtree(str(self.wa_base / self.tenant), ignore_errors=True)

    def test_empty_history(self):
        history = self.manager.get_conversation_history(self.inst, "5511999999999")
        self.assertEqual(history, [])

    def test_save_and_retrieve_messages(self):
        self.manager._save_message(self.inst, "5511999", "user", "Oi")
        self.manager._save_message(self.inst, "5511999", "assistant", "Ola!")
        history = self.manager.get_conversation_history(self.inst, "5511999")
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["role"], "user")
        self.assertEqual(history[1]["content"], "Ola!")

    def test_clear_conversation(self):
        self.manager._save_message(self.inst, "5511888", "user", "Oi")
        cleared = self.manager.clear_conversation(self.inst, "5511888")
        self.assertTrue(cleared)
        history = self.manager.get_conversation_history(self.inst, "5511888")
        self.assertEqual(history, [])

    def test_clear_nonexistent_conversation(self):
        cleared = self.manager.clear_conversation(self.inst, "0000000")
        self.assertFalse(cleared)

    def test_list_conversations(self):
        self.manager._save_message(self.inst, "5511111", "user", "Msg 1")
        self.manager._save_message(self.inst, "5511222", "user", "Msg 2")
        convs = self.manager.list_conversations(self.inst)
        self.assertEqual(len(convs), 2)
        for c in convs:
            self.assertIn("phone", c)
            self.assertIn("total_messages", c)


class TestExtraCost(unittest.TestCase):
    """Testes de custo extra por instancias adicionais."""

    def test_no_extra_cost_within_included(self):
        from clow.whatsapp_agent import WhatsAppAgentManager
        manager = WhatsAppAgentManager()
        # Nao tem instancias = sem custo
        cost = manager.get_extra_cost("nonexistent")
        self.assertEqual(cost, 0)

    def test_handoff_detection(self):
        from clow.whatsapp_agent import WhatsAppAgentManager, WhatsAppInstance, WA_BASE_DIR
        import shutil
        manager = WhatsAppAgentManager()
        tenant = "test-handoff"
        try:
            result = manager.create_instance(tenant, "Bot", "z1", "t1")
            inst = manager.get_instance(result["instance"]["id"], tenant)
            inst.handoff_enabled = True
            inst.handoff_keyword = "humano"

            # Sem historico, nao ha handoff
            self.assertFalse(manager._is_handoff_active(inst, "5511999"))

            # Salva mensagem com keyword
            manager._save_message(inst, "5511999", "user", "quero falar com humano")
            self.assertTrue(manager._is_handoff_active(inst, "5511999"))
        finally:
            shutil.rmtree(str(WA_BASE_DIR / tenant), ignore_errors=True)


class TestGlobalManager(unittest.TestCase):
    """Testa o singleton global."""

    def test_get_wa_manager(self):
        from clow.whatsapp_agent import get_wa_manager, WhatsAppAgentManager
        manager = get_wa_manager()
        self.assertIsInstance(manager, WhatsAppAgentManager)


if __name__ == "__main__":
    unittest.main()
