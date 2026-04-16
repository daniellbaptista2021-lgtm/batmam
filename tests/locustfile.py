"""Load testing para Clow Platform usando Locust.

Uso:
  pip install locust
  locust -f tests/locustfile.py --host http://localhost:8001

  # Headless (CI):
  locust -f tests/locustfile.py --host http://localhost:8001 \
    --headless -u 50 -r 5 -t 60s --csv=results/loadtest

Cenários:
  - HealthCheck: verifica /health (smoke test)
  - AuthUser: faz signup + login + profile
  - ChatUser: faz login + envia mensagens no chat
  - BrowseUser: navega páginas públicas
"""
from locust import HttpUser, task, between, events
import json
import time
import logging

logger = logging.getLogger(__name__)


class HealthCheck(HttpUser):
    """Smoke test — só verifica que o servidor responde."""
    weight = 1
    wait_time = between(1, 3)

    @task
    def health(self):
        self.client.get("/health")


class BrowseUser(HttpUser):
    """Simula visitante navegando páginas públicas."""
    weight = 3
    wait_time = between(2, 5)

    @task(5)
    def view_login(self):
        self.client.get("/login")

    @task(2)
    def view_landing(self):
        self.client.get("/landing")

    @task(1)
    def view_termos(self):
        self.client.get("/termos")

    @task(1)
    def view_manifest(self):
        self.client.get("/static/manifest.json")

    @task(3)
    def view_css(self):
        self.client.get("/static/css/chat.css")

    @task(3)
    def view_js(self):
        self.client.get("/static/js/chat.js")


class AuthUser(HttpUser):
    """Simula fluxo de autenticação: signup → login → profile → preferences."""
    weight = 2
    wait_time = between(3, 8)

    def on_start(self):
        """Cria conta e faz login no início."""
        self.email = f"loadtest_{id(self)}_{int(time.time())}@test.local"
        self.password = "LoadTest2026!Secure"
        self.token = ""

        # Signup
        resp = self.client.post("/api/v1/auth/signup", json={
            "email": self.email,
            "password": self.password,
            "name": "Load Test User",
            "accepted_terms": True,
        })
        if resp.status_code == 200:
            data = resp.json()
            self.token = data.get("token", "")

    @task(3)
    def get_profile(self):
        if self.token:
            self.client.get("/api/v1/user/profile",
                          cookies={"clow_session": self.token})

    @task(2)
    def get_preferences(self):
        if self.token:
            self.client.get("/api/v1/user/preferences",
                          cookies={"clow_session": self.token})

    @task(2)
    def get_usage(self):
        if self.token:
            self.client.get("/api/v1/user/usage",
                          cookies={"clow_session": self.token})

    @task(1)
    def list_conversations(self):
        if self.token:
            self.client.get("/api/v1/conversations",
                          cookies={"clow_session": self.token})


class ChatUser(HttpUser):
    """Simula usuário interagindo no chat."""
    weight = 2
    wait_time = between(5, 15)  # Chat requests are slower

    def on_start(self):
        """Cria conta e faz login."""
        self.email = f"chattest_{id(self)}_{int(time.time())}@test.local"
        self.password = "ChatTest2026!Secure"
        self.token = ""

        resp = self.client.post("/api/v1/auth/signup", json={
            "email": self.email,
            "password": self.password,
            "name": "Chat Test User",
            "accepted_terms": True,
        })
        if resp.status_code == 200:
            self.token = resp.json().get("token", "")

    @task(5)
    def send_greeting(self):
        """Envia saudação (greeting bypass, rápido)."""
        if self.token:
            self.client.post("/api/v1/chat",
                           json={"content": "oi"},
                           cookies={"clow_session": self.token})

    @task(1)
    def send_help(self):
        """Envia comando /help (processado internamente)."""
        if self.token:
            self.client.post("/api/v1/chat",
                           json={"content": "/help"},
                           cookies={"clow_session": self.token})

    @task(1)
    def send_usage(self):
        """Envia comando /usage."""
        if self.token:
            self.client.post("/api/v1/chat",
                           json={"content": "/usage"},
                           cookies={"clow_session": self.token})
