"""Testes dos endpoints HTTP da webapp (FastAPI TestClient)."""

import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from fastapi.testclient import TestClient
    from clow.webapp import app
    from clow.routes.auth import _create_session
    from clow.routes.pages import _template_cache
    HAS_DEPS = app is not None
except (ImportError, Exception):
    HAS_DEPS = False


@unittest.skipUnless(HAS_DEPS, "FastAPI or webapp not available")
class TestPublicEndpoints(unittest.TestCase):
    """Testes de endpoints publicos."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, raise_server_exceptions=False)

    def test_health_returns_200(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("status", data)

    def test_login_page_returns_200(self):
        r = self.client.get("/login")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers.get("content-type", ""))

    def test_root_redirects_to_login(self):
        r = self.client.get("/", follow_redirects=False)
        self.assertIn(r.status_code, [302, 307])
        self.assertIn("/login", r.headers.get("location", ""))

    def test_dashboard_redirects_to_login(self):
        r = self.client.get("/dashboard", follow_redirects=False)
        self.assertIn(r.status_code, [302, 307])


@unittest.skipUnless(HAS_DEPS, "FastAPI or webapp not available")
class TestStaticAssets(unittest.TestCase):
    """Testes de assets estaticos (CSS/JS)."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, raise_server_exceptions=False)

    def test_chat_css_accessible(self):
        r = self.client.get("/static/css/chat.css")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/css", r.headers.get("content-type", ""))

    def test_chat_js_accessible(self):
        r = self.client.get("/static/js/chat.js")
        self.assertEqual(r.status_code, 200)

    def test_login_css_accessible(self):
        r = self.client.get("/static/css/login.css")
        self.assertEqual(r.status_code, 200)

    def test_dashboard_css_accessible(self):
        r = self.client.get("/static/css/dashboard.css")
        self.assertEqual(r.status_code, 200)

    def test_nonexistent_returns_404(self):
        r = self.client.get("/static/css/nonexistent.css")
        self.assertEqual(r.status_code, 404)


@unittest.skipUnless(HAS_DEPS, "FastAPI or webapp not available")
class TestTemplateLoading(unittest.TestCase):
    """Testes do sistema de template loading."""

    def test_chat_template_loads(self):
        from clow.routes.pages import _webapp_html
        html = _webapp_html()
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("chat.css", html)
        self.assertIn("chat.js", html)

    def test_login_template_loads(self):
        from clow.routes.pages import _login_html
        html = _login_html()
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("__ERROR_MSG__", html)

    def test_dashboard_template_loads(self):
        from clow.routes.pages import _dashboard_html
        html = _dashboard_html()
        self.assertIn("<!DOCTYPE html>", html)

    def test_admin_template_loads(self):
        from clow.routes.pages import _admin_html
        html = _admin_html()
        self.assertIn("<!DOCTYPE html>", html)

    def test_template_cache_works(self):
        from clow.routes.pages import _get_template, _template_cache
        _template_cache.clear()
        html1 = _get_template("chat.html")
        html2 = _get_template("chat.html")
        self.assertIs(html1, html2)  # Same object = cached


@unittest.skipUnless(HAS_DEPS, "FastAPI or webapp not available")
class TestAuthProtection(unittest.TestCase):
    """Testes de protecao de endpoints autenticados."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, raise_server_exceptions=False)

    def test_api_chat_requires_auth(self):
        r = self.client.post("/api/v1/chat", json={"content": "test"})
        self.assertIn(r.status_code, [401, 403])

    def test_api_conversations_requires_auth(self):
        r = self.client.get("/api/v1/conversations")
        self.assertIn(r.status_code, [401, 403])

    def test_api_upload_requires_auth(self):
        r = self.client.post("/api/v1/upload")
        self.assertIn(r.status_code, [401, 403, 422])

    def test_api_me_requires_auth(self):
        r = self.client.get("/api/v1/me")
        self.assertIn(r.status_code, [401, 403])

    def test_admin_stats_requires_auth(self):
        r = self.client.get("/api/v1/admin/stats")
        self.assertIn(r.status_code, [401, 403])


@unittest.skipUnless(HAS_DEPS, "FastAPI or webapp not available")
class TestAPIResponses(unittest.TestCase):
    """Testes de formato de resposta da API."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, raise_server_exceptions=False)

    def test_health_has_required_fields(self):
        r = self.client.get("/health")
        data = r.json()
        self.assertIn("status", data)
        self.assertIn("version", data)

    def test_openapi_docs_available(self):
        r = self.client.get("/openapi.json")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("paths", data)


if __name__ == "__main__":
    unittest.main()
