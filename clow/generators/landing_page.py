"""Gerador de Landing Pages HTML com Design System."""
from __future__ import annotations
from pathlib import Path
from .base import STATIC_DIR, ask_ai, slugify, file_url
import time


def generate(prompt: str) -> dict:
    from ..skills.loader import get_design_prompt_for
    design_rules = get_design_prompt_for(prompt) or get_design_prompt_for("landing page")

    system = f"""Voce e um web designer expert de nivel mundial. Gere uma landing page HTML COMPLETA e funcional.

{design_rules}

Regras tecnicas:
- HTML unico arquivo, completo com <!DOCTYPE html>
- Use Tailwind CSS via CDN: <script src="https://cdn.tailwindcss.com"></script>
- Carregue fonts do Google Fonts via <link> no <head>
- NAO use fonts genericas (Inter, Roboto, Arial, Open Sans)
- Escolha font pairing unico e adequado ao nicho do projeto
- Defina CSS variables para cores
- Background com profundidade (gradient, pattern, glow)
- Animacoes de entrada com staggered delay
- Hover states em todos elementos interativos
- Mobile-first e responsivo
- Secoes: hero, beneficios, CTA, footer (minimo)
- Textos em portugues brasileiro
- Retorne APENAS o codigo HTML, sem explicacoes, sem markdown, sem ```"""

    model = "deepseek-chat"
    html = ask_ai(prompt, system=system, model=model, max_tokens=4096)

    if html.startswith("```"):
        html = "\n".join(html.split("\n")[1:])
    if html.endswith("```"):
        html = html[:-3]
    html = html.strip()

    # Validar design
    try:
        from ..skills.design_system.validate_design import validate
        result = validate(html)
        if result["score"] < 60:
            # Regenera com feedback
            issues_text = "\n".join(result["issues"])
            html2 = ask_ai(
                f"Corrija estes problemas de design no HTML:\n{issues_text}\n\nHTML original:\n{html[:2000]}",
                system=system, model=model, max_tokens=4096,
            )
            if html2.startswith("```"):
                html2 = "\n".join(html2.split("\n")[1:])
            if html2.endswith("```"):
                html2 = html2[:-3]
            html = html2.strip() or html
    except Exception:
        pass

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
