"""Modulo Pagamentos — Stripe e Mercado Pago."""
from __future__ import annotations
import requests

TIMEOUT = 30


# ── Stripe ──────────────────────────────────────────────────────

def stripe_balance(creds: dict) -> str:
    r = requests.get("https://api.stripe.com/v1/balance",
        auth=(creds["api_key"], ""), timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    lines = ["## Saldo Stripe\n"]
    for b in data.get("available", []):
        lines.append(f"- Disponivel: {b['currency'].upper()} {b['amount']/100:.2f}")
    for b in data.get("pending", []):
        lines.append(f"- Pendente: {b['currency'].upper()} {b['amount']/100:.2f}")
    return "\n".join(lines)


def stripe_transactions(creds: dict, limit: int = 20) -> str:
    r = requests.get(f"https://api.stripe.com/v1/charges?limit={limit}",
        auth=(creds["api_key"], ""), timeout=TIMEOUT)
    r.raise_for_status()
    charges = r.json().get("data", [])
    if not charges:
        return "Nenhuma transacao encontrada."
    lines = ["## Transacoes Stripe\n", "| Status | Valor | Descricao | Data |", "|--------|-------|-----------|------|"]
    for c in charges:
        st = "✅" if c["paid"] else "❌"
        from datetime import datetime
        dt = datetime.fromtimestamp(c["created"]).strftime("%d/%m %H:%M")
        lines.append(f"| {st} | R${c['amount']/100:.2f} | {c.get('description', '-')[:30]} | {dt} |")
    return "\n".join(lines)


# ── Mercado Pago ────────────────────────────────────────────────

def mp_balance(creds: dict) -> str:
    r = requests.get("https://api.mercadopago.com/users/me",
        headers={"Authorization": f"Bearer {creds['access_token']}"}, timeout=TIMEOUT)
    r.raise_for_status()
    user = r.json()

    r2 = requests.get("https://api.mercadopago.com/mercadopago_account/balance",
        headers={"Authorization": f"Bearer {creds['access_token']}"}, timeout=TIMEOUT)

    if r2.status_code == 200:
        bal = r2.json()
        return f"## Mercado Pago — {user.get('nickname', user.get('first_name', ''))}\n\n- Disponivel: R${bal.get('available_balance', 0):.2f}\n- Total: R${bal.get('total_amount', 0):.2f}"

    return f"## Mercado Pago — {user.get('nickname', '')}\n\nConectado. Use 'listar pagamentos mercado pago' para ver transacoes."


def mp_payments(creds: dict, limit: int = 20) -> str:
    r = requests.get(f"https://api.mercadopago.com/v1/payments/search?sort=date_created&criteria=desc&limit={limit}",
        headers={"Authorization": f"Bearer {creds['access_token']}"}, timeout=TIMEOUT)
    r.raise_for_status()
    results = r.json().get("results", [])
    if not results:
        return "Nenhum pagamento encontrado."
    lines = ["## Pagamentos Mercado Pago\n", "| Status | Valor | Descricao | Data |", "|--------|-------|-----------|------|"]
    for p in results:
        st = {"approved": "✅", "pending": "⏳", "rejected": "❌"}.get(p.get("status", ""), "⚪")
        dt = str(p.get("date_created", ""))[:10]
        lines.append(f"| {st} | R${p.get('transaction_amount', 0):.2f} | {str(p.get('description', '-'))[:30]} | {dt} |")
    return "\n".join(lines)
