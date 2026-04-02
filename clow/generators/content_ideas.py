"""Gerador de ideias de conteudo para redes sociais."""
from __future__ import annotations
from .base import ask_ai


def generate(prompt: str) -> dict:
    system = """Voce e um social media strategist expert. Gere 7 ideias de conteudo para redes sociais.

Para CADA ideia inclua:

### Ideia X: [Tema]
- **Formato:** Reels / Carrossel / Stories / Post estatico
- **Plataforma:** Instagram / TikTok / LinkedIn
- **Legenda pronta:**
[legenda completa com emojis e quebras de linha]
- **Hashtags:** #hash1 #hash2 #hash3 ...
- **Melhor horario:** ex: Terca 19h

---

Use portugues brasileiro, tom engajador.
Ideias variadas entre educativo, entretenimento e venda.
Legendas prontas para copiar e colar."""

    text = ask_ai(prompt, system=system, max_tokens=2048)

    return {
        "type": "text",
        "content": text,
    }
