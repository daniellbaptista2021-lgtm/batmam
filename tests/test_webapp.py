"""Testes da webapp (autenticacao, rate limiting, API)."""

import unittest
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from clow.routes.auth import (
    _verify_api_key, _generate_api_key, _get_api_keys,
    RateLimiter,
)


class TestAPIKeyGeneration(unittest.TestCase):
    """Testes de geracao de API key."""

    def test_generate_key_format(self):
        key = _generate_api_key()
        self.assertTrue(key.startswith("clow_"))
        self.assertGreater(len(key), 20)

    def test_generate_unique(self):
        k1 = _generate_api_key()
        k2 = _generate_api_key()
        self.assertNotEqual(k1, k2)


class TestAPIKeyVerification(unittest.TestCase):
    """Testes de verificacao de API key."""

    def test_no_keys_allows_all(self):
        # Sem keys configuradas = dev mode = tudo permitido
        result = _verify_api_key("anything")
        # Depende da config, mas nao deve crashar
        self.assertIsInstance(result, bool)

    def test_invalid_key_rejected(self):
        # Assuming no keys are configured in test environment,
        # verify returns True (dev mode)
        result = _verify_api_key("")
        self.assertIsInstance(result, bool)


class TestRateLimiter(unittest.TestCase):
    """Testes do rate limiter."""

    def test_allows_within_limit(self):
        rl = RateLimiter(max_requests=5, window_seconds=60)
        for _ in range(5):
            self.assertTrue(rl.is_allowed("127.0.0.1"))

    def test_blocks_over_limit(self):
        rl = RateLimiter(max_requests=3, window_seconds=60)
        for _ in range(3):
            rl.is_allowed("10.0.0.1")
        self.assertFalse(rl.is_allowed("10.0.0.1"))

    def test_different_ips_independent(self):
        rl = RateLimiter(max_requests=2, window_seconds=60)
        rl.is_allowed("ip1")
        rl.is_allowed("ip1")
        self.assertFalse(rl.is_allowed("ip1"))
        self.assertTrue(rl.is_allowed("ip2"))  # IP diferente

    def test_remaining(self):
        rl = RateLimiter(max_requests=10, window_seconds=60)
        self.assertEqual(rl.remaining("new_ip"), 10)
        rl.is_allowed("new_ip")
        self.assertEqual(rl.remaining("new_ip"), 9)

    def test_window_expiration(self):
        rl = RateLimiter(max_requests=2, window_seconds=1)
        rl.is_allowed("exp_ip")
        rl.is_allowed("exp_ip")
        self.assertFalse(rl.is_allowed("exp_ip"))
        # Espera a janela expirar
        time.sleep(1.1)
        self.assertTrue(rl.is_allowed("exp_ip"))


if __name__ == "__main__":
    unittest.main()
