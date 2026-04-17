"""Fase 3 — Specs: divide pagina em secoes e gera spec markdown por componente via deepseek-reasoner."""
from __future__ import annotations

import base64
import json
import logging
import re
from pathlib import Path

from ... import config as config_module

logger = logging.getLogger(__name__)


def _slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()
    return s or "section"


def _pascal(name: str) -> str:
    parts = re.split(r"[^a-zA-Z0-9]+", name)
    return "".join(p.capitalize() for p in parts if p) or "Section"


def _name_for_section(section: dict, idx: int) -> str:
    """Decide um nome semantico baseado em tag/id/classes/textPreview."""
    tag = section.get("tag", "section")
    sid = (section.get("id") or "").strip()
    classes = (section.get("classes") or "").strip()
    text = (section.get("textPreview") or "").strip()

    # Heuristicas comuns
    haystack = f"{sid} {classes} {text}".lower()
    if tag == "header" or "header" in haystack[:80]:
        return "Header"
    if tag == "footer" or "footer" in haystack:
        return "Footer"
    if tag == "nav" or any(k in haystack for k in ("menu", "navbar", "navigation")):
        return f"Nav{idx:02d}"
    if any(k in haystack for k in ("hero", "banner")):
        return "Hero"
    if any(k in haystack for k in ("feature", "benefit")):
        return f"Features{idx:02d}"
    if any(k in haystack for k in ("testimonial", "review", "depoimento")):
        return f"Testimonials{idx:02d}"
    if any(k in haystack for k in ("price", "pricing", "plano")):
        return f"Pricing{idx:02d}"
    if any(k in haystack for k in ("cta", "call-to-action", "subscribe", "register")):
        return f"Cta{idx:02d}"
    if any(k in haystack for k in ("faq", "question")):
        return "FAQ"
    if sid:
        return _pascal(sid)
    if classes:
        # primeira classe util
        first = classes.split()[0] if classes else ""
        first = re.sub(r"[^a-zA-Z0-9-]", "", first)
        if first and len(first) >= 3:
            return _pascal(first)[:24]
    return f"Section{idx:02d}"


def _filter_sections(topology: list[dict], max_sections: int = 12) -> list[dict]:
    """Remove secoes triviais ou aninhadas. Mantem apenas as top-level visualmente significativas."""
    if not topology:
        return []

    # Ordenar por Y
    topo = sorted(topology, key=lambda s: s.get("y", 0))

    # Remover secoes muito pequenas (< 60px) ou contidas em outras maiores
    kept: list[dict] = []
    for s in topo:
        h = s.get("height", 0)
        if h < 60:
            continue
        # Se esta dentro de outra ja escolhida, pula
        contained = False
        sy, sh = s.get("y", 0), s.get("height", 0)
        for k in kept:
            ky, kh = k.get("y", 0), k.get("height", 0)
            if sy >= ky and (sy + sh) <= (ky + kh + 4):
                contained = True
                break
        if not contained:
            kept.append(s)
        if len(kept) >= max_sections:
            break

    return kept


def _take_section_screenshot(browser, section: dict, output_path: str) -> bool:
    """Recorta screenshot da regiao da secao (clip)."""
    try:
        page = browser._page
        x = max(0, section.get("x", 0))
        y = max(0, section.get("y", 0))
        w = section.get("width", 1440)
        h = section.get("height", 800)
        # Limita altura para nao explodir (algumas footer detection retornam absurdo)
        h = min(h, 4000)
        page.screenshot(path=output_path, clip={"x": x, "y": y, "width": w, "height": h}, full_page=True)
        return True
    except Exception as e:
        logger.warning("screenshot da secao falhou: %s", e)
        return False


def _call_reasoner(system: str, user_text: str, image_path: str | None = None, max_tokens: int = 4000) -> str:
    """Chama deepseek-reasoner. Vision suportado se image_path fornecido."""
    try:
        from openai import OpenAI
    except ImportError:
        return ""
    cfg = config_module
    if not cfg.DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY ausente")
        return ""

    client = OpenAI(**cfg.get_deepseek_client_kwargs())

    content: list[dict] = []
    if image_path and Path(image_path).exists():
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
    content.append({"type": "text", "text": user_text})

    try:
        resp = client.chat.completions.create(
            model=cfg.CLOW_CLONE_MODEL,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": content if image_path else user_text},
            ],
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.error("reasoner call falhou: %s", e)
        return ""


def run_specs(browser, output_dir: str | Path, recon_result: dict) -> dict:
    """Para cada secao detectada: recorta screenshot, chama reasoner, salva spec.md."""
    from .prompts import SPEC_SYSTEM

    output_dir = Path(output_dir)
    components_dir = output_dir / "docs" / "research" / "components"
    section_shots_dir = output_dir / "docs" / "research" / "screenshots" / "sections"
    components_dir.mkdir(parents=True, exist_ok=True)
    section_shots_dir.mkdir(parents=True, exist_ok=True)

    topology = recon_result.get("topology", [])
    max_sections = config_module.CLOW_CLONE_MAX_SECTIONS
    sections = _filter_sections(topology, max_sections=max_sections)

    if not sections:
        return {"status": "error", "error": "Nenhuma secao detectada na topologia"}

    specs = []
    used_names: set[str] = set()

    for idx, section in enumerate(sections):
        name = _name_for_section(section, idx)
        # garantir unicidade
        base_name = name
        counter = 2
        while name in used_names:
            name = f"{base_name}{counter}"
            counter += 1
        used_names.add(name)

        slug = _slug(name)
        shot_path = section_shots_dir / f"{slug}.png"
        shot_ok = _take_section_screenshot(browser, section, str(shot_path))

        # Monta context pro reasoner
        ctx = {
            "section_name": name,
            "tag": section.get("tag"),
            "dimensions": f"{section.get('width')}x{section.get('height')}",
            "y_offset": section.get("y"),
            "id": section.get("id"),
            "classes": (section.get("classes") or "")[:300],
            "text_preview": (section.get("textPreview") or "")[:500],
        }

        user_text = (
            f"Componente: **{name}**\n\n"
            f"Contexto extraido do DOM:\n```json\n{json.dumps(ctx, indent=2, ensure_ascii=False)}\n```\n\n"
            f"Use o screenshot acima (recorte da secao no desktop 1440px) e o contexto do DOM "
            f"para produzir o spec markdown completo, seguindo o formato definido."
        )

        spec_md = _call_reasoner(
            system=SPEC_SYSTEM,
            user_text=user_text,
            image_path=str(shot_path) if shot_ok else None,
            max_tokens=3500,
        )

        if not spec_md:
            spec_md = f"# {name}\n\n_(spec generation falhou — fallback minimal)_\n\nTag: {section.get('tag')}\nDimensoes: {ctx['dimensions']}\nTexto: {ctx['text_preview']}\n"

        spec_path = components_dir / f"{slug}.spec.md"
        spec_path.write_text(spec_md, encoding="utf-8")

        specs.append({
            "name": name,
            "slug": slug,
            "spec_file": str(spec_path.relative_to(output_dir)),
            "screenshot": str(shot_path.relative_to(output_dir)) if shot_ok else None,
            "spec_chars": len(spec_md),
            "section": section,
        })

    return {
        "status": "ok",
        "specs_count": len(specs),
        "specs": specs,
        "components_dir": str(components_dir),
    }
