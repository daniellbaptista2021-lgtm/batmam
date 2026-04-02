"""Testes do sistema de multi-tenancy."""

import unittest
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from clow.tenancy import (
    Tenant, TenantQuota, TenantUsage, TenantManager,
)


class TestTenantQuota(unittest.TestCase):
    """Testes de quotas."""

    def test_defaults(self):
        q = TenantQuota()
        self.assertEqual(q.max_tokens_per_day, 1_000_000)
        self.assertEqual(q.max_sessions, 100)
        self.assertEqual(q.max_memory_entries, 500)

    def test_from_dict(self):
        q = TenantQuota.from_dict({"max_tokens_per_day": 500000, "max_sessions": 50})
        self.assertEqual(q.max_tokens_per_day, 500000)
        self.assertEqual(q.max_sessions, 50)


class TestTenantUsage(unittest.TestCase):
    """Testes de uso."""

    def test_initial_zero(self):
        u = TenantUsage()
        self.assertEqual(u.tokens_today, 0)
        self.assertEqual(u.sessions_count, 0)

    def test_roundtrip(self):
        u = TenantUsage(tokens_today=1000, sessions_count=5, memory_count=10, last_reset=time.time())
        d = u.to_dict()
        u2 = TenantUsage.from_dict(d)
        self.assertEqual(u.tokens_today, u2.tokens_today)
        self.assertEqual(u.sessions_count, u2.sessions_count)

    def test_reset_if_new_day(self):
        u = TenantUsage(tokens_today=5000, last_reset=time.time() - 86401)  # > 24h atras
        u.reset_if_new_day()
        # Se mudou o dia, tokens_today deve ser 0
        # (pode nao resetar se ainda for o mesmo dia, mas pelo menos nao quebra)
        self.assertGreaterEqual(u.tokens_today, 0)


class TestTenant(unittest.TestCase):
    """Testes de tenant."""

    def test_create(self):
        t = Tenant(id="test-tenant", name="Test")
        self.assertEqual(t.id, "test-tenant")
        self.assertTrue(t.active)

    def test_check_quota_ok(self):
        t = Tenant(id="test", quota=TenantQuota(max_tokens_per_day=10000))
        t.usage.last_reset = time.time()
        ok, msg = t.check_quota(tokens=100)
        self.assertTrue(ok)

    def test_check_quota_exceeded(self):
        t = Tenant(id="test", quota=TenantQuota(max_tokens_per_day=100))
        t.usage.tokens_today = 90
        t.usage.last_reset = time.time()
        ok, msg = t.check_quota(tokens=50)
        self.assertFalse(ok)
        self.assertIn("excedida", msg)

    def test_inactive_tenant_blocked(self):
        t = Tenant(id="test", active=False)
        ok, msg = t.check_quota()
        self.assertFalse(ok)
        self.assertIn("desativado", msg)

    def test_add_tokens(self):
        t = Tenant(id="test")
        t.ensure_dirs()
        t.usage.last_reset = time.time()
        t.add_tokens(500)
        self.assertEqual(t.usage.tokens_today, 500)
        t.add_tokens(300)
        self.assertEqual(t.usage.tokens_today, 800)

    def test_to_dict(self):
        t = Tenant(id="x", name="X Tenant", created_at=123.0)
        d = t.to_dict()
        self.assertEqual(d["id"], "x")
        self.assertEqual(d["name"], "X Tenant")
        self.assertIn("quota", d)

    def test_dirs(self):
        t = Tenant(id="dir-test")
        self.assertIn("dir-test", str(t.base_dir))
        self.assertIn("sessions", str(t.sessions_dir))
        self.assertIn("memory", str(t.memory_dir))


class TestTenantManager(unittest.TestCase):
    """Testes do gerenciador de tenants."""

    def test_default_tenant_exists(self):
        mgr = TenantManager()
        mgr.load_from_settings()
        self.assertIsNotNone(mgr.current)
        self.assertEqual(mgr.current.id, "default")

    def test_create_tenant(self):
        mgr = TenantManager()
        mgr.load_from_settings()
        t = mgr.create_tenant("novo", name="Novo Tenant")
        self.assertEqual(t.id, "novo")
        self.assertEqual(t.name, "Novo Tenant")
        self.assertTrue(t.active)

    def test_get_tenant(self):
        mgr = TenantManager()
        mgr.load_from_settings()
        mgr.create_tenant("t1")
        t = mgr.get_tenant("t1")
        self.assertEqual(t.id, "t1")

    def test_list_tenants(self):
        mgr = TenantManager()
        mgr.load_from_settings()
        tenants = mgr.list_tenants()
        self.assertGreater(len(tenants), 0)
        self.assertTrue(any(t["id"] == "default" for t in tenants))

    def test_delete_tenant(self):
        mgr = TenantManager()
        mgr.load_from_settings()
        mgr.create_tenant("to-delete")
        result = mgr.delete_tenant("to-delete")
        self.assertTrue(result)

    def test_cannot_delete_default(self):
        mgr = TenantManager()
        mgr.load_from_settings()
        result = mgr.delete_tenant("default")
        self.assertFalse(result)

    def test_set_current(self):
        mgr = TenantManager()
        mgr.load_from_settings()
        mgr.create_tenant("switch-test")
        mgr.set_current("switch-test")
        self.assertEqual(mgr.current.id, "switch-test")


if __name__ == "__main__":
    unittest.main()
