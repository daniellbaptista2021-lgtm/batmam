"""Gerador de Landing Pages HTML."""
from __future__ import annotations
from pathlib import Path
from .base import STATIC_DIR, ask_ai, slugify, file_url
import time


def generate(prompt: str) -> dict:
    system = """Voce e um web designer expert. Gere uma landing page HTML COMPLETA e funcional.
Regras:
- HTML unico arquivo, completo com <!DOCTYPE html>
- Use Tailwind CSS via CDN: <script src="https://cdn.tailwindcss.com"></script>
- Design moderno, responsivo, mobile-first
- Cores profissionais, tipografia limpa
- Secoes: hero, beneficios, CTA, footer
- Inclua emojis e icones onde apropriado
- Textos em portugues brasileiro
- Retorne APENAS o codigo HTML, sem explicacoes, sem markdown, sem ```"""

    model = "claude-sonnet-4-20250514"
    html = ask_ai(prompt, system=system, model=model, max_tokens=4096)

    # Limpa caso venha com markdown
    if html.startswith("```"):
        html = "\n".join(html.split("\n")[1:])
    if html.endswith("```"):
        html = html[:-3]
    html = html.strip()

    slug = slugify(prompt[:40]) or "landing"
    ts = int(time.time())
    folder = f"{slug}-{ts}"
    out_dir = STATIC_DIR / "pages" / folder
    out_dir.mkdir(parents=True, exist_ok=True)

    filepath = out_dir / "index.html"
    filepath.write_text(html, encoding="utf-8")

    url = file_url(f"static/pages/{folder}/index.html")
    size = filepath.stat().st_size

    return {
        "type": "landing_page",
        "name": f"{slug}.html",
        "url": url,
        "size": size,
        "path": str(filepath),
    }
