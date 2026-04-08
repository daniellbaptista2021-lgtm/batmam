#!/usr/bin/env python3
"""Cria produtos e preços dos 4 planos Clow no Stripe.

Uso:
  1. Adicione STRIPE_SECRET_KEY ao ~/.clow/app/.env
  2. source ~/.clow/app/.env
  3. python3 scripts/create_stripe_plans.py

O script:
  - Cria (ou reutiliza) o produto de cada plano
  - Cria um preço recorrente mensal em BRL
  - Salva os price_ids no ~/.clow/app/.env automaticamente
"""

from __future__ import annotations
import os
import sys

try:
    import stripe
except ImportError:
    print("Instale o stripe: pip install stripe")
    sys.exit(1)

STRIPE_KEY = os.getenv("STRIPE_SECRET_KEY", "")
if not STRIPE_KEY:
    print("ERRO: STRIPE_SECRET_KEY nao definida. Adicione ao ~/.clow/app/.env e rode 'source ~/.clow/app/.env'")
    sys.exit(1)

stripe.api_key = STRIPE_KEY

ENV_FILE = os.path.expanduser("~/.clow/app/.env")

PLANOS = [
    {
        "env_var": "STRIPE_PRICE_ONE",
        "nome": "Clow ONE",
        "descricao": "1 WhatsApp com IA + plataforma. Ideal para autônomos e pequenos negócios.",
        "preco_centavos": 12990,  # R$129,90
    },
    {
        "env_var": "STRIPE_PRICE_SMART",
        "nome": "Clow SMART",
        "descricao": "2 WhatsApp + CRM Chatwoot + 8 fluxos n8n. Para negócios em crescimento.",
        "preco_centavos": 29700,  # R$297,00
    },
    {
        "env_var": "STRIPE_PRICE_PROFISSIONAL",
        "nome": "Clow PROFISSIONAL",
        "descricao": "3 WhatsApp + 5 usuários + 2.000 fluxos n8n. Para equipes.",
        "preco_centavos": 49700,  # R$497,00
    },
    {
        "env_var": "STRIPE_PRICE_BUSINESS",
        "nome": "Clow BUSINESS",
        "descricao": "5 WhatsApp + 10 usuários + 3.000 fluxos + API pública. Empresarial.",
        "preco_centavos": 89700,  # R$897,00
    },
]


def get_or_create_product(nome: str, descricao: str) -> str:
    """Busca produto existente pelo nome ou cria um novo."""
    produtos = stripe.Product.list(limit=100, active=True)
    for p in produtos.auto_paging_iter():
        if p.name == nome:
            print(f"  Produto existente: {p.id} ({nome})")
            return p.id
    produto = stripe.Product.create(name=nome, description=descricao)
    print(f"  Produto criado: {produto.id} ({nome})")
    return produto.id


def create_price(product_id: str, amount_cents: int) -> str:
    """Cria preço recorrente mensal em BRL."""
    preco = stripe.Price.create(
        product=product_id,
        unit_amount=amount_cents,
        currency="brl",
        recurring={"interval": "month"},
    )
    print(f"  Preço criado: {preco.id} (R${amount_cents/100:.2f}/mês)")
    return preco.id


def update_env(var: str, value: str) -> None:
    """Atualiza ou adiciona variável no .env."""
    if not os.path.exists(ENV_FILE):
        print(f"  AVISO: {ENV_FILE} não encontrado, criando...")
        with open(ENV_FILE, "w") as f:
            f.write("")

    with open(ENV_FILE, "r") as f:
        lines = f.readlines()

    found = False
    new_lines = []
    for line in lines:
        if line.startswith(f"{var}="):
            new_lines.append(f"{var}={value}\n")
            found = True
        else:
            new_lines.append(line)

    if not found:
        new_lines.append(f"{var}={value}\n")

    with open(ENV_FILE, "w") as f:
        f.writelines(new_lines)

    print(f"  .env atualizado: {var}={value}")


def main():
    print(f"Usando Stripe {'LIVE' if 'live' in STRIPE_KEY else 'TEST'}")
    print(f"Env file: {ENV_FILE}")
    print()

    resultados = {}
    for plano in PLANOS:
        print(f"=== {plano['nome']} ===")
        product_id = get_or_create_product(plano["nome"], plano["descricao"])
        price_id = create_price(product_id, plano["preco_centavos"])
        update_env(plano["env_var"], price_id)
        resultados[plano["env_var"]] = price_id
        print()

    print("✓ Concluído! Reinicie o Clow para aplicar os novos price_ids.")
    print()
    print("Resumo:")
    for var, pid in resultados.items():
        print(f"  {var}={pid}")


if __name__ == "__main__":
    main()
