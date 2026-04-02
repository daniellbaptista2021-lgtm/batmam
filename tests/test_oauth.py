"""Testes do sistema OAuth com PKCE."""

import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from clow.oauth import (
    generate_pkce, base64url_encode, build_authorization_url,
    OAuthCredential, parse_callback_params, PKCEChallenge,
)


class TestPKCE(unittest.TestCase):
    """Testes da geracao PKCE."""

    def test_generate_pkce(self):
        pkce = generate_pkce()
        self.assertIsInstance(pkce, PKCEChallenge)
        self.assertGreaterEqual(len(pkce.code_verifier), 43)
        self.assertGreater(len(pkce.code_challenge), 0)
        self.assertEqual(pkce.method, "S256")

    def test_s256_correctness(self):
        """Verifica que S256 e calculado corretamente."""
        import hashlib
        import base64

        pkce = generate_pkce()
        digest = hashlib.sha256(pkce.code_verifier.encode("ascii")).digest()
        expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        self.assertEqual(pkce.code_challenge, expected)

    def test_uniqueness(self):
        """Cada chamada gera um par diferente."""
        p1 = generate_pkce()
        p2 = generate_pkce()
        self.assertNotEqual(p1.code_verifier, p2.code_verifier)

    def test_no_padding(self):
        """Base64url nao deve ter padding '='."""
        pkce = generate_pkce()
        self.assertNotIn("=", pkce.code_verifier)
        self.assertNotIn("=", pkce.code_challenge)


class TestBase64URL(unittest.TestCase):
    """Testes do base64url encoding."""

    def test_no_padding(self):
        result = base64url_encode(b"hello")
        self.assertNotIn("=", result)

    def test_url_safe(self):
        result = base64url_encode(b"\xff\xfe\xfd")
        self.assertNotIn("+", result)
        self.assertNotIn("/", result)


class TestAuthorizationURL(unittest.TestCase):
    """Testes da construcao de URL de autorizacao."""

    def test_contains_required_params(self):
        pkce = generate_pkce()
        url = build_authorization_url(
            "https://auth.example.com/authorize",
            "client_id_123",
            "http://localhost:9876/callback",
            ["read", "write"],
            pkce,
        )
        self.assertIn("client_id=client_id_123", url)
        self.assertIn("response_type=code", url)
        self.assertIn("code_challenge=", url)
        self.assertIn("code_challenge_method=S256", url)
        self.assertIn("state=", url)

    def test_custom_state(self):
        pkce = generate_pkce()
        url = build_authorization_url(
            "https://auth.example.com", "id", "http://localhost",
            [], pkce, state="custom_state"
        )
        self.assertIn("state=custom_state", url)


class TestOAuthCredential(unittest.TestCase):
    """Testes de credenciais OAuth."""

    def test_create(self):
        cred = OAuthCredential(provider="github", access_token="abc")
        self.assertEqual(cred.provider, "github")
        self.assertEqual(cred.access_token, "abc")

    def test_not_expired_no_expiry(self):
        cred = OAuthCredential(provider="test", access_token="x")
        self.assertFalse(cred.is_expired)

    def test_expired(self):
        import time
        cred = OAuthCredential(
            provider="test", access_token="x",
            expires_at=time.time() - 100
        )
        self.assertTrue(cred.is_expired)

    def test_not_expired(self):
        import time
        cred = OAuthCredential(
            provider="test", access_token="x",
            expires_at=time.time() + 3600
        )
        self.assertFalse(cred.is_expired)

    def test_roundtrip(self):
        cred = OAuthCredential(
            provider="github", access_token="abc",
            refresh_token="def", token_type="bearer",
            scopes=["repo", "user"]
        )
        d = cred.to_dict()
        cred2 = OAuthCredential.from_dict(d)
        self.assertEqual(cred.access_token, cred2.access_token)
        self.assertEqual(cred.refresh_token, cred2.refresh_token)
        self.assertEqual(cred.scopes, cred2.scopes)


class TestCallbackParsing(unittest.TestCase):
    """Testes de parsing de callback URL."""

    def test_parse_code_and_state(self):
        params = parse_callback_params(
            "http://localhost:9876/callback?code=abc123&state=xyz"
        )
        self.assertEqual(params["code"], "abc123")
        self.assertEqual(params["state"], "xyz")

    def test_parse_error(self):
        params = parse_callback_params(
            "http://localhost/callback?error=access_denied&error_description=User+denied"
        )
        self.assertEqual(params["error"], "access_denied")


if __name__ == "__main__":
    unittest.main()
