"""Testes de regressao de seguranca pos-incidente.

Cada teste mapeia uma camada de defesa:
- test_redact_*: ETAPA 1 — secrets nao vazam em logs/outputs
- test_admin_only_tools_*: ETAPA 2 — tenant nao recebe tools admin
- test_cross_tenant_*: ETAPA 4 — tenant A nao le dados do tenant B
- test_guardrail_*: ETAPA 5 — system prompt do tenant tem regras
- test_tenant_creds_*: ETAPA 3 — Fernet encrypt/decrypt funciona
"""
import os
import uuid

import pytest

import clow.config  # noqa: F401


# ── ETAPA 1: REDACT ───────────────────────────────────────────
class TestRedact:
    def test_bearer_token_redacted(self):
        from clow.security import redact
        assert "abc123XYZ456789" not in redact("Authorization: Bearer abc123XYZ456789defghijklmn")

    def test_access_token_redacted(self):
        from clow.security import redact
        out = redact("access_token=EAAMETAabc123def456ghi789jklmn")
        assert "EAAMETAabc123def456ghi789jklmn" not in out

    def test_sk_key_redacted(self):
        from clow.security import redact
        assert "sk-b22c4eb123a04570b7a7af0ee71c06a1" not in redact("DEEPSEEK_API_KEY=sk-b22c4eb123a04570b7a7af0ee71c06a1")

    def test_zapi_client_token_redacted(self):
        from clow.security import redact
        # Z-API tokens tem padrao Fxxx...xxxS
        out = redact("Client-Token: F986fce42e250445fb74cc9ec87593732S")
        assert "F986fce42e250445fb74cc9ec87593732S" not in out

    def test_env_value_auto_redacted(self):
        """Valor literal vindo do .env deve ser redactado mesmo sem padrao reconhecivel."""
        from clow.security import redact, refresh_env_values
        refresh_env_values()
        # Pega um valor sensivel real do env (Fernet key sempre existe agora)
        fkey = os.getenv("CLOW_FERNET_KEY", "")
        if not fkey:
            pytest.skip("CLOW_FERNET_KEY nao setada")
        msg = f"oops i leaked the fernet key: {fkey} pls dont look"
        out = redact(msg)
        assert fkey not in out, f"FERNET KEY VAZOU: {out!r}"


# ── ETAPA 2: ADMIN-ONLY TOOLS ────────────────────────────────
class TestAdminOnlyTools:
    def test_tenant_does_not_get_bash(self, tenant_user):
        from clow.security.roles import filter_tools_for_role
        result = filter_tools_for_role({"bash", "web_search"}, is_admin=False)
        assert "bash" not in result
        assert "web_search" in result

    def test_tenant_does_not_get_meta_ads(self, tenant_user):
        from clow.security.roles import filter_tools_for_role, ADMIN_ONLY_TOOLS
        for tool in ["meta_ads", "read", "write", "edit", "http_request",
                     "supabase_query", "canva_tools", "ssh_vps", "docker_manage"]:
            assert tool in ADMIN_ONLY_TOOLS, f"{tool} deveria estar em ADMIN_ONLY_TOOLS"
            assert tool not in filter_tools_for_role({tool}, is_admin=False)

    def test_admin_gets_everything(self, admin_user):
        from clow.security.roles import filter_tools_for_role
        result = filter_tools_for_role({"bash", "meta_ads", "read", "web_search"}, is_admin=True)
        assert result == {"bash", "meta_ads", "read", "web_search"}

    def test_is_user_admin_check(self, admin_user, tenant_user):
        from clow.security.roles import is_user_admin
        assert is_user_admin(admin_user) is True
        assert is_user_admin(tenant_user) is False
        assert is_user_admin(None) is False
        assert is_user_admin("") is False

    def test_unknown_user_is_not_admin(self):
        """Defensive: unknown user_id should NOT be admin."""
        from clow.security.roles import is_user_admin, clear_admin_cache
        clear_admin_cache()
        assert is_user_admin("nao-existe-" + uuid.uuid4().hex) is False


# ── ETAPA 4: CROSS-TENANT ISOLATION ──────────────────────────
class TestCrossTenantIsolation:
    def test_get_messages_blocks_cross_user(self, tenant_user, tenant_user_b):
        from clow.database import create_conversation, save_message, get_messages
        conv_a = create_conversation(tenant_user, "secret_conv")
        save_message(conv_a, "user", "INFORMACAO PRIVADA DO TENANT A")
        # B tenta ler conversa de A
        msgs = get_messages(conv_a, tenant_user_b)
        assert msgs == [], f"Cross-tenant leak: B viu mensagens de A: {msgs}"
        # A le suas proprias mensagens normalmente
        own = get_messages(conv_a, tenant_user)
        assert any("PRIVADA DO TENANT A" in m["content"] for m in own)

    def test_get_messages_empty_user_id(self, tenant_user):
        """user_id vazio deve retornar lista vazia, sem erro."""
        from clow.database import create_conversation, save_message, get_messages
        conv = create_conversation(tenant_user, "x")
        save_message(conv, "user", "anything")
        assert get_messages(conv, "") == []
        assert get_messages(conv, None) == []  # type: ignore


# ── ETAPA 5: GUARDRAIL NO SYSTEM PROMPT ──────────────────────
class TestGuardrail:
    GUARDRAIL_MARKER = "Nao posso compartilhar esse tipo de informacao. Posso te ajudar"

    def _build_agent(self, user_id):
        from clow.agent import Agent
        from clow.models import Session
        sess = Session(id=f"t_{user_id[:6]}", messages=[], cwd=os.getcwd(), model="deepseek-chat")
        return Agent(
            cwd=os.getcwd(), model="deepseek-chat", api_key="x",
            auto_approve=True, session=sess, user_id=user_id,
        )

    def test_tenant_gets_guardrail(self, tenant_user):
        ag = self._build_agent(tenant_user)
        sys_msg = ag.session.messages[0]["content"]
        assert self.GUARDRAIL_MARKER in sys_msg

    def test_admin_does_not_get_guardrail(self, admin_user):
        ag = self._build_agent(admin_user)
        sys_msg = ag.session.messages[0]["content"]
        assert self.GUARDRAIL_MARKER not in sys_msg


# ── ETAPA 3: TENANT CREDENTIALS (FERNET) ─────────────────────
class TestTenantCredentials:
    def test_set_get_roundtrip(self, tenant_user):
        from clow.security.tenant_credentials import set_secret, get_secret, delete_secret
        token = "test_token_" + uuid.uuid4().hex
        set_secret(tenant_user, "test_provider", token)
        assert get_secret(tenant_user, "test_provider") == token
        delete_secret(tenant_user, "test_provider")
        assert get_secret(tenant_user, "test_provider") is None

    def test_cross_tenant_credentials_isolated(self, tenant_user, tenant_user_b):
        from clow.security.tenant_credentials import set_secret, get_secret, delete_secret
        set_secret(tenant_user, "shared_provider", "TOKEN_A")
        set_secret(tenant_user_b, "shared_provider", "TOKEN_B")
        assert get_secret(tenant_user, "shared_provider") == "TOKEN_A"
        assert get_secret(tenant_user_b, "shared_provider") == "TOKEN_B"
        delete_secret(tenant_user, "shared_provider")
        assert get_secret(tenant_user, "shared_provider") is None
        assert get_secret(tenant_user_b, "shared_provider") == "TOKEN_B"

    def test_tampered_token_returns_none(self, tenant_user):
        """Fernet detecta tampering via HMAC."""
        from clow.security.tenant_credentials import set_secret, get_secret, delete_secret
        from clow.database import get_db
        set_secret(tenant_user, "tamper_test", "real_token")
        with get_db() as db:
            db.execute(
                "UPDATE tenant_credentials SET encrypted_token=? WHERE user_id=? AND provider=?",
                (b"GARBAGE_BYTES", tenant_user, "tamper_test"),
            )
            db.commit()
        assert get_secret(tenant_user, "tamper_test") is None
        delete_secret(tenant_user, "tamper_test")
