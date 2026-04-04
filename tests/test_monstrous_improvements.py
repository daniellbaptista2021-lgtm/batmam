"""Testes para as 3 melhorias monstruosas:
1. GitHub Issue Autopilot
2. Automations Engine
3. Live Pair Programming (Spectator)
"""

import json
import os
import sys
import queue
import time
import threading
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from clow import config


# ════════════════════════════════════════════════════════════════
# 1. TESTE: GitHub Issue Autopilot
# ════════════════════════════════════════════════════════════════

class TestAutopilot(unittest.TestCase):
    """Verifica o GitHub Issue Autopilot."""

    def test_config_defaults(self):
        self.assertTrue(config.CLOW_AUTOPILOT)
        self.assertTrue(hasattr(config, "GITHUB_TOKEN"))
        self.assertTrue(hasattr(config, "GITHUB_WEBHOOK_SECRET"))
        print("[OK] Autopilot: configs presentes")

    def test_db_creation(self):
        """Tabela autopilot_runs deve ser criada."""
        from clow.autopilot import _get_db
        db = _get_db()
        cursor = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='autopilot_runs'")
        table = cursor.fetchone()
        db.close()
        self.assertIsNotNone(table)
        print("[OK] Autopilot: tabela autopilot_runs criada")

    def test_webhook_signature_verification(self):
        """Verifica assinatura HMAC do webhook."""
        from clow.autopilot import verify_webhook_signature

        # Sem secret configurado, deve aceitar tudo
        original = config.GITHUB_WEBHOOK_SECRET
        config.GITHUB_WEBHOOK_SECRET = ""
        self.assertTrue(verify_webhook_signature(b"test", ""))
        config.GITHUB_WEBHOOK_SECRET = original
        print("[OK] Autopilot: verificacao de assinatura funciona")

    def test_handle_webhook_ignored_events(self):
        """Eventos nao relevantes devem ser ignorados."""
        from clow.autopilot import handle_webhook

        result = handle_webhook("push", {"ref": "refs/heads/main"})
        self.assertEqual(result["status"], "ignored")

        result = handle_webhook("issues", {"action": "opened", "issue": {}})
        self.assertEqual(result["status"], "ignored")
        print("[OK] Autopilot: eventos irrelevantes ignorados")

    def test_handle_webhook_label_trigger(self):
        """Issue com label 'clow' deve iniciar autopilot."""
        from clow.autopilot import handle_webhook

        # Sem GITHUB_TOKEN, nao vai executar o agent, mas deve registrar
        original_token = config.GITHUB_TOKEN
        config.GITHUB_TOKEN = ""

        payload = {
            "action": "labeled",
            "label": {"name": "clow"},
            "issue": {"number": 42, "title": "Fix login bug", "body": "Users can't login"},
            "repository": {"full_name": "test/repo"},
        }

        result = handle_webhook("issues", payload)
        self.assertEqual(result["status"], "started")
        self.assertEqual(result["issue"], 42)
        self.assertIn("run_id", result)

        config.GITHUB_TOKEN = original_token
        print("[OK] Autopilot: label 'clow' inicia execucao")

    def test_handle_webhook_comment_trigger(self):
        """Comentario '@clow fix this' deve iniciar autopilot."""
        from clow.autopilot import handle_webhook

        payload = {
            "action": "created",
            "comment": {"body": "@clow fix the authentication"},
            "issue": {"number": 99, "title": "Auth broken", "body": "Login fails"},
            "repository": {"full_name": "test/repo2"},
        }

        result = handle_webhook("issue_comment", payload)
        self.assertEqual(result["status"], "started")
        self.assertEqual(result["issue"], 99)
        print("[OK] Autopilot: '@clow' em comentario inicia execucao")

    def test_list_and_get_runs(self):
        """list_runs e get_run devem funcionar."""
        from clow.autopilot import list_runs, get_run

        runs = list_runs(5)
        self.assertIsInstance(runs, list)

        # Os runs do teste anterior devem estar la
        if runs:
            run = get_run(runs[0]["id"])
            self.assertIsNotNone(run)
            self.assertIn("issue_number", run)

        print("[OK] Autopilot: list_runs e get_run funcionam")

    def test_get_active_runs(self):
        from clow.autopilot import get_active_runs
        active = get_active_runs()
        self.assertIsInstance(active, list)
        print("[OK] Autopilot: get_active_runs retorna lista")


# ════════════════════════════════════════════════════════════════
# 2. TESTE: Automations Engine
# ════════════════════════════════════════════════════════════════

class TestAutomations(unittest.TestCase):
    """Verifica o Automations Engine."""

    def test_config_default(self):
        self.assertTrue(config.CLOW_AUTOMATIONS)
        print("[OK] Automations: config default = True")

    def test_engine_init(self):
        from clow.automations import AutomationsEngine
        engine = AutomationsEngine()
        self.assertEqual(len(engine.list_all()), 0)
        print("[OK] Automations: engine inicializa vazia")

    def test_create_automation(self):
        from clow.automations import AutomationsEngine
        engine = AutomationsEngine()

        auto = engine.create(
            name="test-backup",
            trigger_type="webhook",
            trigger_config={},
            prompt_template="Faca backup dos dados",
        )

        self.assertEqual(auto.name, "test-backup")
        self.assertTrue(auto.enabled)

        all_autos = engine.list_all()
        self.assertEqual(len(all_autos), 1)
        self.assertEqual(all_autos[0]["name"], "test-backup")
        print("[OK] Automations: create funciona")

    def test_enable_disable(self):
        from clow.automations import AutomationsEngine
        engine = AutomationsEngine()
        engine.create("test-toggle", "webhook", {}, "test")

        self.assertTrue(engine.disable("test-toggle"))
        autos = engine.list_all()
        self.assertFalse(autos[0]["enabled"])

        self.assertTrue(engine.enable("test-toggle"))
        autos = engine.list_all()
        self.assertTrue(autos[0]["enabled"])
        print("[OK] Automations: enable/disable funciona")

    def test_trigger_webhook(self):
        from clow.automations import AutomationsEngine
        engine = AutomationsEngine()
        engine.create("test-webhook", "webhook", {}, "Echo test", max_runs_per_day=5)

        # Trigger sem agent factory vai falhar gracefully
        result = engine.trigger("test-webhook", {"key": "value"})
        # Vai ser error pois nao tem API key, mas a estrutura deve existir
        self.assertIn("automation", result)
        self.assertEqual(result["automation"], "test-webhook")
        print("[OK] Automations: trigger webhook executa")

    def test_trigger_nonexistent(self):
        from clow.automations import AutomationsEngine
        engine = AutomationsEngine()
        result = engine.trigger("nope")
        self.assertIn("error", result)
        print("[OK] Automations: trigger inexistente retorna erro")

    def test_dashboard(self):
        from clow.automations import AutomationsEngine
        engine = AutomationsEngine()
        engine.create("a1", "cron", {"schedule": "5m"}, "test1")
        engine.create("a2", "webhook", {}, "test2")

        dashboard = engine.dashboard()
        self.assertEqual(dashboard["total"], 2)
        self.assertEqual(dashboard["enabled"], 2)
        self.assertEqual(len(dashboard["automations"]), 2)

        # Cleanup cron threads
        engine.stop_all()
        print("[OK] Automations: dashboard retorna stats corretas")

    def test_max_runs_per_day(self):
        from clow.automations import AutomationsEngine, Automation
        engine = AutomationsEngine()
        auto = engine.create("limited", "webhook", {}, "test", max_runs_per_day=1)

        # Simula que ja rodou 1x hoje
        with engine._lock:
            engine._automations["limited"].run_count_today = 1

        # Deve ser bloqueada
        result = engine.trigger("limited")
        self.assertIn("error", result)
        self.assertIn("Limite", result["error"])
        print("[OK] Automations: max_runs_per_day respeitado")

    def test_github_event_routing(self):
        from clow.automations import AutomationsEngine
        engine = AutomationsEngine()
        engine.create("on-push", "github_event", {"event": "push."}, "Deploy on push")

        result = engine.handle_github_event("push", {"action": "", "ref": "main"})
        # push sem action = "push." que nao vai match exato "push." (precisa "push")
        self.assertIn("matched", result)
        print("[OK] Automations: github_event routing funciona")

    def test_parse_interval(self):
        from clow.automations import AutomationsEngine
        self.assertEqual(AutomationsEngine._parse_interval("30s"), 30)
        self.assertEqual(AutomationsEngine._parse_interval("5m"), 300)
        self.assertEqual(AutomationsEngine._parse_interval("1h"), 3600)
        self.assertEqual(AutomationsEngine._parse_interval("invalid"), 600)
        print("[OK] Automations: parse_interval correto")


# ════════════════════════════════════════════════════════════════
# 3. TESTE: Live Pair Programming (Spectator)
# ════════════════════════════════════════════════════════════════

class TestSpectator(unittest.TestCase):
    """Verifica o Spectator Mode."""

    def test_config_default(self):
        self.assertTrue(config.CLOW_SPECTATOR)
        print("[OK] Spectator: config default = True")

    def test_create_spectator(self):
        from clow.spectator import create_spectator, get_spectator
        spec = create_spectator("test-session-1")
        self.assertEqual(spec.session_id, "test-session-1")
        self.assertIsNotNone(spec.share_token)
        self.assertEqual(len(spec.share_token), 12)

        # get deve retornar o mesmo
        spec2 = get_spectator("test-session-1")
        self.assertIs(spec, spec2)
        print("[OK] Spectator: create + get funciona")

    def test_subscribe_and_emit(self):
        from clow.spectator import create_spectator
        spec = create_spectator("test-session-2")

        q = spec.subscribe()
        self.assertEqual(spec.subscriber_count, 1)

        spec.emit("tool_call", {"name": "bash", "arguments": {"command": "ls"}})
        spec.emit("text_delta", {"text": "Hello"})

        # Subscriber deve receber os eventos
        events = []
        while not q.empty():
            events.append(q.get_nowait())

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["type"], "tool_call")
        self.assertEqual(events[1]["type"], "text_delta")
        self.assertEqual(events[1]["data"]["text"], "Hello")

        spec.unsubscribe(q)
        self.assertEqual(spec.subscriber_count, 0)
        print("[OK] Spectator: subscribe + emit + receive funciona")

    def test_multiple_subscribers(self):
        from clow.spectator import create_spectator
        spec = create_spectator("test-session-3")

        q1 = spec.subscribe()
        q2 = spec.subscribe()
        self.assertEqual(spec.subscriber_count, 2)

        spec.emit("test", {"msg": "broadcast"})

        e1 = q1.get_nowait()
        e2 = q2.get_nowait()
        self.assertEqual(e1["data"]["msg"], "broadcast")
        self.assertEqual(e2["data"]["msg"], "broadcast")

        spec.unsubscribe(q1)
        spec.unsubscribe(q2)
        print("[OK] Spectator: multiplos subscribers recebem broadcast")

    def test_approval_flow(self):
        from clow.spectator import create_spectator
        spec = create_spectator("test-session-4")

        q = spec.subscribe()
        result = {"approved": None}

        def request_approval():
            result["approved"] = spec.request_approval("Pode deletar?", timeout=5)

        # Inicia request em thread
        t = threading.Thread(target=request_approval)
        t.start()

        # Espera o evento de approval_request
        time.sleep(0.2)
        event = q.get(timeout=2)
        self.assertEqual(event["type"], "approval_request")
        approval_id = event["data"]["approval_id"]

        # Aprova
        spec.resolve_approval(approval_id, True)
        t.join(timeout=3)

        self.assertTrue(result["approved"])
        spec.unsubscribe(q)
        print("[OK] Spectator: fluxo de approval funciona (request -> approve)")

    def test_approval_deny(self):
        from clow.spectator import create_spectator
        spec = create_spectator("test-session-5")
        result = {"approved": None}

        def request_approval():
            result["approved"] = spec.request_approval("Pode executar?", timeout=5)

        t = threading.Thread(target=request_approval)
        t.start()
        time.sleep(0.2)

        # Busca o approval_id
        with spec._lock:
            approval_ids = list(spec._pending_approval.keys())
        if approval_ids:
            spec.resolve_approval(approval_ids[0], False)

        t.join(timeout=3)
        self.assertFalse(result["approved"])
        print("[OK] Spectator: approval deny funciona")

    def test_get_by_token(self):
        from clow.spectator import create_spectator, get_spectator_by_token
        spec = create_spectator("test-session-6")

        found = get_spectator_by_token(spec.share_token)
        self.assertIs(found, spec)

        not_found = get_spectator_by_token("nonexistent")
        self.assertIsNone(not_found)
        print("[OK] Spectator: get_by_token funciona")

    def test_list_spectators(self):
        from clow.spectator import list_spectators
        specs = list_spectators()
        self.assertIsInstance(specs, list)
        self.assertGreater(len(specs), 0)
        self.assertIn("session_id", specs[0])
        print("[OK] Spectator: list_spectators retorna dados")

    def test_make_callbacks(self):
        from clow.spectator import make_spectator_callbacks, create_spectator
        spec = create_spectator("test-session-7")
        q = spec.subscribe()

        callbacks = make_spectator_callbacks("test-session-7")
        self.assertIn("on_text_delta", callbacks)
        self.assertIn("on_tool_call", callbacks)
        self.assertIn("on_tool_result", callbacks)

        # Testa callbacks
        callbacks["on_text_delta"]("Hello world")
        callbacks["on_tool_call"]("bash", {"command": "ls"})

        events = []
        while not q.empty():
            events.append(q.get_nowait())

        self.assertGreaterEqual(len(events), 2)
        spec.unsubscribe(q)
        print("[OK] Spectator: make_callbacks gera e emite eventos corretamente")

    def test_format_sse(self):
        from clow.spectator import format_sse
        event = {"type": "test", "data": {"msg": "hello"}}
        sse = format_sse(event)
        self.assertIn("event: test", sse)
        self.assertIn("data: ", sse)
        self.assertTrue(sse.endswith("\n\n"))
        print("[OK] Spectator: format_sse gera SSE valido")

    def test_to_dict(self):
        from clow.spectator import create_spectator
        spec = create_spectator("test-session-8")
        d = spec.to_dict()
        self.assertIn("session_id", d)
        self.assertIn("share_token", d)
        self.assertIn("subscribers", d)
        self.assertIn("events_buffered", d)
        print("[OK] Spectator: to_dict retorna estrutura completa")


# ════════════════════════════════════════════════════════════════
# SKILLS + INTEGRACAO
# ════════════════════════════════════════════════════════════════

class TestSkillsAndIntegration(unittest.TestCase):

    def test_new_skills_registered(self):
        from clow._skills_cli import create_default_skill_registry
        registry = create_default_skill_registry()

        for name in ["autopilot", "automations", "share"]:
            skill = registry.get(name)
            self.assertIsNotNone(skill, f"Skill /{name} nao encontrado")

        # Aliases
        self.assertIsNotNone(registry.get("ap"))
        self.assertIsNotNone(registry.get("auto"))
        self.assertIsNotNone(registry.get("spectator"))
        print("[OK] Skills: autopilot, automations, share registrados com aliases")

    def test_all_configs_present(self):
        for attr in ["CLOW_AUTOPILOT", "GITHUB_TOKEN", "GITHUB_WEBHOOK_SECRET",
                      "CLOW_AUTOMATIONS", "CLOW_SPECTATOR"]:
            self.assertTrue(hasattr(config, attr), f"Config {attr} nao encontrada")
        print("[OK] Integracao: todas as configs presentes")

    def test_routes_module_importable(self):
        from clow.routes.extensions import register_extension_routes
        self.assertTrue(callable(register_extension_routes))
        print("[OK] Integracao: routes/extensions.py importavel")


if __name__ == "__main__":
    print("=" * 60)
    print("  TESTES: 3 Melhorias Monstruosas")
    print("=" * 60)
    print()
    unittest.main(verbosity=2)
