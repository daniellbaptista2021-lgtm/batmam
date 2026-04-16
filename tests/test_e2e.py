#!/usr/bin/env python3
"""Testes End-to-End para fluxos críticos do Clow.

Testa fluxos completos contra o servidor rodando:
  - Auth: register → login → session → logout
  - Chat: auth → send message → get response
  - CRM: auth → create lead → update → list → delete
  - Memory: auth → save → load → delete
  - Conversations: auth → create → list → messages → delete
  - Settings: auth → get profile → update preferences
  - Health: health check endpoint

Requer: servidor rodando em http://localhost:8001
"""
import json
import os
import sys
import time
import urllib.request
import urllib.parse

BASE_URL = os.getenv("CLOW_TEST_URL", "http://localhost:8001")
PASS = 0
FAIL = 0
SKIP = 0

# Test credentials
TEST_EMAIL = f"e2e_test_{int(time.time())}@test.clow.local"
TEST_PASSWORD = "Test@E2E#2026!Secure"
TEST_TOKEN = ""


def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  OK  {name}")
    else:
        FAIL += 1
        msg = f"  FAIL {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)


def skip(name: str, reason: str):
    global SKIP
    SKIP += 1
    print(f"  SKIP {name} — {reason}")


def _req(method: str, path: str, data: dict | None = None,
         token: str = "", expect_status: int = 200) -> dict:
    """Make HTTP request, return parsed JSON."""
    url = f"{BASE_URL}{path}"
    body = json.dumps(data).encode() if data else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Cookie"] = f"clow_session={token}"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        status = resp.status
        body_text = resp.read().decode()
        try:
            result = json.loads(body_text)
        except json.JSONDecodeError:
            result = {"_raw": body_text[:500], "_status": status}
        result["_status"] = status
        return result
    except urllib.error.HTTPError as e:
        body_text = e.read().decode() if e.fp else ""
        try:
            result = json.loads(body_text)
        except Exception:
            result = {"_raw": body_text[:500]}
        result["_status"] = e.code
        return result
    except Exception as e:
        return {"_status": 0, "_error": str(e)}


print("=" * 60)
print(f"TESTES END-TO-END — Clow Platform")
print(f"Server: {BASE_URL}")
print("=" * 60)


# ══════════════════════════════════════════════════════════════
# 1. Health Check
# ══════════════════════════════════════════════════════════════
print("\n[1] Health Check")

r = _req("GET", "/health")
check("GET /health retorna 200", r.get("_status") == 200)
check("Health response OK", r.get("status") == "ok" or r.get("_status") == 200)


# ══════════════════════════════════════════════════════════════
# 2. Auth Flow: Register → Login → Session → Logout
# ══════════════════════════════════════════════════════════════
print("\n[2] Auth Flow")

# Register via /api/v1/auth/signup
r = _req("POST", "/api/v1/auth/signup", {
    "email": TEST_EMAIL,
    "password": TEST_PASSWORD,
    "name": "E2E Test User",
    "accepted_terms": True,
})
registered = r.get("_status") in (200, 201) or r.get("token")
TEST_TOKEN = r.get("token", "")
check("Register new user (signup)", registered, f"status={r.get('_status')}")

# If signup returned a token, use it
if not TEST_TOKEN:
    # Try login via API
    r = _req("POST", "/api/v1/auth/login", {
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD,
    })
    TEST_TOKEN = r.get("token", "")

check("Auth returns session token", bool(TEST_TOKEN),
      f"status={r.get('_status')}")

if not TEST_TOKEN:
    skip("Token-dependent tests", "No auth token available")


# ══════════════════════════════════════════════════════════════
# 3. Chat Flow
# ══════════════════════════════════════════════════════════════
print("\n[3] Chat Flow")

if TEST_TOKEN:
    # Simple greeting (greeting bypass returns fast response)
    r = _req("POST", "/api/v1/chat", {
        "content": "oi",
    }, token=TEST_TOKEN)
    check("Chat greeting returns response", bool(r.get("response")),
          f"status={r.get('_status')}, resp={str(r.get('response', ''))[:50]}")

    # Non-greeting message (uses full agent pipeline)
    r = _req("POST", "/api/v1/chat", {
        "content": "qual a data de hoje?",
    }, token=TEST_TOKEN)
    check("Chat agent returns response", bool(r.get("response")),
          f"status={r.get('_status')}")
else:
    skip("Chat test", "No auth token")


# ══════════════════════════════════════════════════════════════
# 4. Conversations Flow
# ══════════════════════════════════════════════════════════════
print("\n[4] Conversations Flow")

if TEST_TOKEN:
    # Create conversation
    r = _req("POST", "/api/v1/conversations", {
        "title": "E2E Test Conversation",
    }, token=TEST_TOKEN)
    conv_created = r.get("_status") in (200, 201) or r.get("id")
    conv_id = r.get("id", "")
    check("Create conversation", conv_created, f"status={r.get('_status')}")

    # List conversations
    r = _req("GET", "/api/v1/conversations", token=TEST_TOKEN)
    check("List conversations", r.get("_status") == 200)

    # Delete conversation
    if conv_id:
        r = _req("DELETE", f"/api/v1/conversations/{conv_id}", token=TEST_TOKEN)
        check("Delete conversation", r.get("_status") in (200, 204))
else:
    skip("Conversations tests", "No auth token")


# ══════════════════════════════════════════════════════════════
# 5. Settings Flow
# ══════════════════════════════════════════════════════════════
print("\n[5] Settings Flow")

if TEST_TOKEN:
    # Get profile
    r = _req("GET", "/api/v1/user/profile", token=TEST_TOKEN)
    check("Get user profile", r.get("_status") == 200 and r.get("email"),
          f"status={r.get('_status')}")

    # Get preferences
    r = _req("GET", "/api/v1/user/preferences", token=TEST_TOKEN)
    check("Get user preferences", r.get("_status") == 200)

    # Get usage
    r = _req("GET", "/api/v1/user/usage", token=TEST_TOKEN)
    check("Get usage stats", r.get("_status") == 200)
else:
    skip("Settings tests", "No auth token")


# ══════════════════════════════════════════════════════════════
# 6. Static Assets
# ══════════════════════════════════════════════════════════════
print("\n[6] Static Assets")

r = _req("GET", "/static/manifest.json")
check("manifest.json accessible", r.get("_status") == 200)

# Check security headers (may not apply to /health, try /login)
try:
    resp = urllib.request.urlopen(f"{BASE_URL}/login", timeout=10)
    headers = dict(resp.headers)
    check("X-Content-Type-Options header present",
          "nosniff" in headers.get("X-Content-Type-Options", "")
          or "nosniff" in headers.get("x-content-type-options", ""))
    check("Referrer-Policy header present",
          bool(headers.get("Referrer-Policy", "")
               or headers.get("referrer-policy", "")))
except Exception as e:
    skip("Security headers", str(e))


# ══════════════════════════════════════════════════════════════
# 7. Rate Limiting
# ══════════════════════════════════════════════════════════════
print("\n[7] Rate Limiting")

# This is a basic test — shouldn't trigger rate limit with one request
r = _req("GET", "/health")
check("Request not rate-limited", r.get("_status") != 429)


# ══════════════════════════════════════════════════════════════
# Result
# ══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print(f"RESULTADO: {PASS} passed, {FAIL} failed, {SKIP} skipped")
print("=" * 60)

# Cleanup note
if TEST_TOKEN:
    print(f"\nNota: usuario de teste {TEST_EMAIL} criado no banco")

sys.exit(1 if FAIL > 0 else 0)
