"""Gerador de Single-Page Apps HTML/CSS/JS."""
from __future__ import annotations
from pathlib import Path
from .base import STATIC_DIR, ask_ai, slugify, file_url
import time


def generate(prompt: str) -> dict:
    from ..skills.loader import get_design_prompt_for
    design_rules = get_design_prompt_for(prompt) or get_design_prompt_for("app")

    system = f"""Voce e um desenvolvedor fullstack expert. Gere um app web single-page COMPLETO e FUNCIONAL.

{design_rules}

Regras tecnicas:
- HTML unico arquivo com CSS e JS embutidos
- Comece com <!DOCTYPE html>
- Use Tailwind CSS via CDN: <script src="https://cdn.tailwindcss.com"></script>
- Carregue fonts do Google Fonts (NAO use fonts genericas)
- App 100% funcional com logica JS completa
- Escolha estetica adequada ao tipo de app (nao sempre dark roxo)
- Background com profundidade, animacoes de entrada
- Responsivo e mobile-first
- Dados persistidos em localStorage quando aplicavel
- Textos em portugues brasileiro
- Retorne APENAS o codigo HTML, sem explicacoes, sem markdown, sem ```"""

    model = "claude-sonnet-4-20250514"
    html = ask_ai(prompt, system=system, model=model, max_tokens=4096)

    if html.startswith("```"):
        html = "\n".join(html.split("\n")[1:])
    if html.endswith("```"):
        html = html[:-3]
    html = html.strip()

    slug = slugify(prompt[:40]) or "app"
    ts = int(time.time())
    folder = f"{slug}-{ts}"
    out_dir = STATIC_DIR / "apps" / folder
    out_dir.mkdir(parents=True, exist_ok=True)

    filepath = out_dir / "index.html"
    filepath.write_text(html, encoding="utf-8")

    url = file_url(f"static/apps/{folder}/index.html")
    size = filepath.stat().st_size

    return {
        "type": "app",
        "name": f"{slug}",
        "url": url,
        "size": size,
        "path": str(filepath),
    }
