"""Gerador de copies para anuncios."""
from __future__ import annotations
from .base import ask_ai


def generate(prompt: str) -> dict:
    system = """Voce e um copywriter expert em marketing digital e trafego pago.
Gere 3 variacoes de copy para anuncios baseado no pedido do usuario.

Para CADA variacao, inclua:
- Headline (titulo chamativo, max 40 chars)
- Texto principal (persuasivo, com gatilhos mentais)
- CTA (call to action direto)

Formate assim:

## Facebook / Instagram Ads

### Variacao 1
**Headline:** ...
**Texto:** ...
**CTA:** ...

### Variacao 2
**Headline:** ...
**Texto:** ...
**CTA:** ...

### Variacao 3
**Headline:** ...
**Texto:** ...
**CTA:** ...

## Google Ads

### Titulo 1 (max 30 chars): ...
### Titulo 2 (max 30 chars): ...
### Titulo 3 (max 30 chars): ...
### Descricao 1 (max 90 chars): ...
### Descricao 2 (max 90 chars): ...

Use portugues brasileiro, tom profissional mas acessivel."""

    text = ask_ai(prompt, system=system, max_tokens=2048)

    return {
        "type": "text",
        "content": text,
    }
