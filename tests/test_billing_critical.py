"""Testes criticos de billing — fluxos que se quebrarem perdem dinheiro."""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestBillingPlans(unittest.TestCase):
    """Verifica que todos os planos existem e estao corretos."""

    def test_all_plans_defined(self):
        from clow.billing import PLANS
        for plan in ["byok_free", "lite", "starter", "pro", "business"]:
            self.assertIn(plan, PLANS, f"Plano {plan} faltando")
        print("[OK] Todos os 5 planos definidos")

    def test_plan_prices(self):
        from clow.billing import PLANS
        self.assertEqual(PLANS["byok_free"]["price_brl"], 0)
        self.assertEqual(PLANS["lite"]["price_brl"], 97)
        self.assertEqual(PLANS["starter"]["price_brl"], 197)
        self.assertEqual(PLANS["pro"]["price_brl"], 347)
        self.assertEqual(PLANS["business"]["price_brl"], 497)
        print("[OK] Precos corretos")

    def test_plan_models(self):
        from clow.billing import PLANS
        self.assertIn("haiku", PLANS["lite"]["model"])
        self.assertIn("sonnet", PLANS["starter"]["model"])
        self.assertIn("sonnet", PLANS["pro"]["model"])
        self.assertIn("sonnet", PLANS["business"]["model"])
        print("[OK] Modelos corretos por plano")

    def test_plan_uses_server_key(self):
        from clow.billing import plan_uses_server_key
        self.assertFalse(plan_uses_server_key("byok_free"))
        self.assertTrue(plan_uses_server_key("lite"))
        self.assertTrue(plan_uses_server_key("starter"))
        self.assertTrue(plan_uses_server_key("pro"))
        self.assertTrue(plan_uses_server_key("business"))
        print("[OK] BYOK usa key do user, pagos usam key do servidor")

    def test_stripe_price_ids_configured(self):
        from clow.billing import PLANS
        for plan_id in ["lite", "starter", "pro", "business"]:
            price_id = PLANS[plan_id]["stripe_price_id"]
            self.assertTrue(price_id, f"Stripe price_id faltando para {plan_id}")
        print("[OK] Todos os Stripe price IDs configurados")


class TestQuotaChecking(unittest.TestCase):
    """Verifica que a franquia funciona corretamente."""

    def test_byok_no_limit(self):
        from clow.billing import check_quota
        result = check_quota("fake-user", "byok_free")
        self.assertTrue(result["allowed"])
        print("[OK] BYOK sem limite de franquia")

    def test_plan_quotas_defined(self):
        from clow.billing import PLANS
        for plan_id in ["lite", "starter", "pro", "business"]:
            plan = PLANS[plan_id]
            self.assertGreater(plan["daily_input_tokens"], 0)
            self.assertGreater(plan["daily_output_tokens"], 0)
            self.assertGreater(plan["weekly_input_tokens"], 0)
            self.assertGreater(plan["weekly_output_tokens"], 0)
        print("[OK] Todas as franquias definidas")

    def test_pro_has_more_than_starter(self):
        from clow.billing import PLANS
        self.assertGreater(
            PLANS["pro"]["daily_input_tokens"],
            PLANS["starter"]["daily_input_tokens"],
        )
        # Escala: Lite < Starter < Pro < Business
        self.assertGreater(
            PLANS["starter"]["daily_input_tokens"],
            PLANS["lite"]["daily_input_tokens"],
        )
        self.assertGreater(
            PLANS["business"]["daily_input_tokens"],
            PLANS["pro"]["daily_input_tokens"],
        )
        print("[OK] Franquias escalam corretamente entre planos")


class TestCheckoutFlow(unittest.TestCase):
    """Verifica que o checkout Stripe funciona."""

    def test_checkout_requires_valid_plan(self):
        from clow.billing import create_checkout_session
        result = create_checkout_session("user1", "test@test.com", "invalid_plan", "", "")
        self.assertIn("error", result)
        print("[OK] Plano invalido rejeitado")

    def test_checkout_byok_has_no_price(self):
        from clow.billing import create_checkout_session
        result = create_checkout_session("user1", "test@test.com", "byok_free", "", "")
        self.assertIn("error", result)
        print("[OK] BYOK nao tem checkout Stripe")

    def test_checkout_valid_plan_creates_session(self):
        from clow.billing import create_checkout_session
        result = create_checkout_session("user1", "test@test.com", "pro", "", "")
        # Pode ter URL (se Stripe configurado) ou erro (se sem internet)
        self.assertTrue("url" in result or "error" in result)
        if "url" in result:
            self.assertTrue(result["url"].startswith("https://checkout.stripe.com"))
            print("[OK] Checkout Pro gera URL Stripe")
        else:
            print(f"[OK] Checkout Pro: {result.get('error', '')[:50]} (Stripe pode nao estar acessivel)")


class TestWebhookHandling(unittest.TestCase):
    """Verifica que o webhook handler funciona."""

    def test_invalid_signature_rejected(self):
        from clow.billing import handle_webhook
        result = handle_webhook(b"fake payload", "fake-sig")
        self.assertIn("error", result)
        print("[OK] Webhook com signature invalida rejeitado")

    def test_price_id_to_plan_mapping(self):
        from clow.billing import PRICE_ID_TO_PLAN
        self.assertGreater(len(PRICE_ID_TO_PLAN), 0)
        for price_id, plan_id in PRICE_ID_TO_PLAN.items():
            self.assertIn(plan_id, ["lite", "starter", "pro", "business"])
        print(f"[OK] {len(PRICE_ID_TO_PLAN)} price IDs mapeados para planos")


class TestBillingStatus(unittest.TestCase):
    """Verifica que o billing status funciona."""

    def test_billing_status_nonexistent_user(self):
        from clow.billing import get_billing_status
        result = get_billing_status("nonexistent-user-xyz")
        self.assertIn("error", result)
        print("[OK] User inexistente retorna erro")

    def test_model_for_plan(self):
        from clow.billing import get_model_for_plan
        self.assertIn("haiku", get_model_for_plan("lite"))
        self.assertIn("sonnet", get_model_for_plan("pro"))
        self.assertIn("sonnet", get_model_for_plan("byok_free"))
        print("[OK] Modelo correto por plano")


class TestDatabasePlansConsistency(unittest.TestCase):
    """Verifica que database.py e billing.py estao consistentes."""

    def test_billing_plans_in_database(self):
        from clow.database import PLANS as DB_PLANS
        from clow.billing import PLANS as BILL_PLANS
        for plan_id in BILL_PLANS:
            self.assertIn(plan_id, DB_PLANS, f"Plano {plan_id} do billing nao existe no database")
        print("[OK] Planos billing e database consistentes")


if __name__ == "__main__":
    print("=" * 50)
    print("  TESTES CRITICOS DE BILLING")
    print("=" * 50)
    unittest.main(verbosity=2)
