"""Fixtures pra testes de seguranca: cria/limpa users de teste."""
import os
import time
import uuid
import pytest

# Garante que .env carrega antes de qualquer import do clow
import clow.config  # noqa: F401

from clow.database import get_db
from clow.security.roles import clear_admin_cache


def _mk_user(is_admin: bool) -> str:
    uid = ("adm_" if is_admin else "ten_") + uuid.uuid4().hex[:10]
    now = time.time()
    with get_db() as db:
        db.execute(
            "INSERT INTO users (id, email, password_hash, plan, is_admin, created_at) VALUES (?,?,?,?,?,?)",
            (uid, uid + "@test.local", "x", "free", 1 if is_admin else 0, now),
        )
        db.commit()
    return uid


def _del_user(uid: str) -> None:
    with get_db() as db:
        db.execute("DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE user_id=?)", (uid,))
        db.execute("DELETE FROM conversations WHERE user_id=?", (uid,))
        db.execute("DELETE FROM tenant_credentials WHERE user_id=?", (uid,))
        db.execute("DELETE FROM users WHERE id=?", (uid,))
        db.commit()


@pytest.fixture
def admin_user():
    uid = _mk_user(is_admin=True)
    clear_admin_cache()
    yield uid
    _del_user(uid)
    clear_admin_cache()


@pytest.fixture
def tenant_user():
    uid = _mk_user(is_admin=False)
    clear_admin_cache()
    yield uid
    _del_user(uid)
    clear_admin_cache()


@pytest.fixture
def tenant_user_b():
    """Segundo tenant pra testes de cross-tenant."""
    uid = _mk_user(is_admin=False)
    clear_admin_cache()
    yield uid
    _del_user(uid)
    clear_admin_cache()
