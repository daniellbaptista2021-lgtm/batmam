"""Validador de design — verifica se HTML segue o design system."""
from __future__ import annotations
import re

BANNED_FONTS = ["inter", "roboto", "open sans", "arial", "lato", "helvetica", "system-ui"]
APPROVED_FONTS = [
    "clash display", "cabinet grotesk", "bricolage grotesque", "playfair display",
    "fraunces", "space grotesk", "satoshi", "ibm plex sans", "source sans 3",
    "crimson pro", "dm sans", "jetbrains mono", "fira code", "ibm plex mono",
]


def validate(html: str) -> dict:
    """Valida HTML contra o design system. Retorna score 0-100 e issues."""
    issues = []
    score = 100
    lower = html.lower()

    # 1. Fonts genericas
    for font in BANNED_FONTS:
        if font in lower and f"'{font}'" not in lower.split("fallback", 1)[0]:
            # Check if it's a primary font, not just fallback
            pattern = rf'font-family\s*:\s*["\']?{re.escape(font)}'
            if re.search(pattern, lower):
                issues.append(f"Font generica detectada: {font}")
                score -= 15
                break

    # 2. Fonts aprovadas
    has_approved = any(f in lower for f in APPROVED_FONTS)
    if not has_approved:
        # Check Google Fonts link
        if "fonts.googleapis.com" in lower:
            has_approved = True
        else:
            issues.append("Nenhuma font aprovada do design system encontrada")
            score -= 10

    # 3. CSS Variables
    has_vars = "--" in html and "var(--" in html
    if not has_vars:
        issues.append("Nao usa CSS variables para cores")
        score -= 10

    # 4. Background com profundidade
    has_gradient = "gradient" in lower or "background-image" in lower
    has_solid_only = not has_gradient and ("background:" in lower or "background-color:" in lower)
    if has_solid_only:
        issues.append("Background parece ser solido sem profundidade")
        score -= 8

    # 5. Animacoes
    has_animation = "animation" in lower or "@keyframes" in lower or "transition" in lower
    if not has_animation:
        issues.append("Sem animacoes ou transitions")
        score -= 10

    # 6. Responsivo
    has_responsive = "@media" in lower or "tailwind" in lower or "sm:" in html or "md:" in html or "lg:" in html
    if not has_responsive:
        issues.append("Sem media queries ou classes responsivas")
        score -= 10

    # 7. Hover states
    has_hover = ":hover" in lower or "hover:" in html
    if not has_hover:
        issues.append("Sem hover states nos elementos interativos")
        score -= 8

    # 8. Viewport meta
    has_viewport = "viewport" in lower
    if not has_viewport:
        issues.append("Falta meta viewport para mobile")
        score -= 5

    # 9. Tailwind ou CSS structure
    has_tailwind = "tailwindcss" in lower or "cdn.tailwindcss" in lower
    has_good_css = has_vars or has_tailwind
    if not has_good_css:
        issues.append("Sem framework CSS ou sistema de variables")
        score -= 5

    # 10. AI slop check
    slop_patterns = [
        (r'font-family.*?:\s*["\']?arial', "Arial como font primaria"),
        (r'background.*?:\s*#fff\s*;', "Fundo branco solido (#fff)"),
        (r'color\s*:\s*#333', "Texto #333 generico"),
    ]
    for pattern, desc in slop_patterns:
        if re.search(pattern, lower):
            issues.append(f"AI slop: {desc}")
            score -= 7

    score = max(0, score)

    return {
        "score": score,
        "grade": "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D" if score >= 40 else "F",
        "issues": issues,
        "has_approved_fonts": has_approved,
        "has_css_vars": has_vars,
        "has_animations": has_animation,
        "has_responsive": has_responsive,
    }


def format_report(result: dict) -> str:
    """Formata resultado da validacao."""
    lines = [f"## Design Score: {result['score']}/100 ({result['grade']})\n"]
    checks = [
        ("Fonts aprovadas", result["has_approved_fonts"]),
        ("CSS Variables", result["has_css_vars"]),
        ("Animacoes", result["has_animations"]),
        ("Responsivo", result["has_responsive"]),
    ]
    for label, ok in checks:
        lines.append(f"{'✅' if ok else '❌'} {label}")

    if result["issues"]:
        lines.append(f"\n### Problemas ({len(result['issues'])}):")
        for issue in result["issues"]:
            lines.append(f"- ⚠️ {issue}")
    else:
        lines.append("\n✨ Nenhum problema encontrado!")

    return "\n".join(lines)
