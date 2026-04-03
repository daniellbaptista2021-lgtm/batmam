"""Testes do rate limiter per-user."""

import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from clow.rate_limit import RateLimiter, PLAN_LIMITS, IP_LIMIT


class TestRateLimiterIP(unittest.TestCase):
    """Testes de rate limit por IP."""

    def test_allows_within_limit(self):
        rl = RateLimiter()
        for _ in range(10):
            ok, _ = rl.check_ip("1.2.3.4")
            self.assertTrue(ok)

    def test_blocks_over_limit(self):
        rl = RateLimiter()
        for _ in range(IP_LIMIT.requests):
            rl.check_ip("5.6.7.8")
        ok, rem = rl.check_ip("5.6.7.8")
        self.assertFalse(ok)
        self.assertEqual(rem, 0)

    def test_different_ips_independent(self):
        rl = RateLimiter()
        for _ in range(IP_LIMIT.requests):
            rl.check_ip("ip1")
        ok1, _ = rl.check_ip("ip1")
        ok2, _ = rl.check_ip("ip2")
        self.assertFalse(ok1)
        self.assertTrue(ok2)


class TestRateLimiterUser(unittest.TestCase):
    """Testes de rate limit por usuario."""

    def test_free_plan_limit(self):
        rl = RateLimiter()
        limit = PLAN_LIMITS["free"]
        for _ in range(limit.requests):
            rl.check_user("user1", "free")
        ok, _ = rl.check_user("user1", "free")
        self.assertFalse(ok)

    def test_pro_plan_higher_limit(self):
        rl = RateLimiter()
        free_limit = PLAN_LIMITS["free"].requests
        # Pro should allow more than free
        for _ in range(free_limit):
            ok, _ = rl.check_user("pro_user", "pro")
            self.assertTrue(ok)
        # Should still have remaining
        ok, rem = rl.check_user("pro_user", "pro")
        self.assertTrue(ok)
        self.assertGreater(rem, 0)

    def test_admin_effectively_unlimited(self):
        rl = RateLimiter()
        for _ in range(100):
            ok, _ = rl.check_user("admin1", "admin")
            self.assertTrue(ok)

    def test_different_users_independent(self):
        rl = RateLimiter()
        limit = PLAN_LIMITS["free"]
        for _ in range(limit.requests):
            rl.check_user("u1", "free")
        ok1, _ = rl.check_user("u1", "free")
        ok2, _ = rl.check_user("u2", "free")
        self.assertFalse(ok1)
        self.assertTrue(ok2)


class TestRateLimiterCombined(unittest.TestCase):
    """Testes do check combinado (IP + user)."""

    def test_check_both(self):
        rl = RateLimiter()
        ok, rem = rl.check("1.1.1.1", "user1", "pro")
        self.assertTrue(ok)
        self.assertGreater(rem, 0)

    def test_ip_blocked_overrides_user(self):
        rl = RateLimiter()
        for _ in range(IP_LIMIT.requests):
            rl.check("blocked_ip", "user1", "admin")
        ok, _ = rl.check("blocked_ip", "user1", "admin")
        self.assertFalse(ok)

    def test_user_blocked_with_ip_ok(self):
        rl = RateLimiter()
        limit = PLAN_LIMITS["free"]
        for _ in range(limit.requests):
            rl.check("ok_ip", "limited_user", "free")
        ok, _ = rl.check("ok_ip", "limited_user", "free")
        self.assertFalse(ok)


class TestPlanLimits(unittest.TestCase):
    """Testes das configuracoes de limites."""

    def test_all_plans_defined(self):
        for plan in ("free", "pro", "unlimited", "admin"):
            self.assertIn(plan, PLAN_LIMITS)

    def test_limits_ascending(self):
        self.assertLess(PLAN_LIMITS["free"].requests, PLAN_LIMITS["pro"].requests)
        self.assertLess(PLAN_LIMITS["pro"].requests, PLAN_LIMITS["unlimited"].requests)
        self.assertLess(PLAN_LIMITS["unlimited"].requests, PLAN_LIMITS["admin"].requests)


if __name__ == "__main__":
    unittest.main()
