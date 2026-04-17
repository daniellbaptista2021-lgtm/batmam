"""Fase 1 — Reconnaissance: screenshots multi-viewport, design tokens, DOM topology, behaviors."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

VIEWPORTS = [
    {"name": "desktop", "width": 1440, "height": 900},
    {"name": "mobile", "width": 390, "height": 844},
]

# JS injetado na pagina pra coletar tudo numa unica chamada (evita roundtrips)
_RECON_JS = r"""
() => {
  const get = (el, prop) => getComputedStyle(el)[prop];
  const px = (v) => parseFloat(v) || 0;

  // 1. Topology — secoes principais
  const topology = [];
  const SEMANTIC = ['header', 'nav', 'main', 'section', 'article', 'aside', 'footer'];
  document.querySelectorAll(SEMANTIC.join(',')).forEach((el, idx) => {
    if (el.offsetHeight < 40) return;
    const rect = el.getBoundingClientRect();
    topology.push({
      idx,
      tag: el.tagName.toLowerCase(),
      id: el.id || null,
      classes: el.className && typeof el.className === 'string' ? el.className.slice(0, 200) : '',
      role: el.getAttribute('role'),
      ariaLabel: el.getAttribute('aria-label'),
      x: Math.round(rect.x),
      y: Math.round(rect.y + window.scrollY),
      width: Math.round(rect.width),
      height: Math.round(rect.height),
      childCount: el.children.length,
      textPreview: (el.innerText || '').replace(/\s+/g, ' ').slice(0, 120),
    });
  });

  // 2. Design tokens — coleta cores e fontes dos elementos principais
  const colorCounts = {};
  const fontCounts = {};
  const tally = (map, key) => { if (key) map[key] = (map[key] || 0) + 1; };

  document.querySelectorAll('body *').forEach((el, i) => {
    if (i > 600) return;
    const cs = getComputedStyle(el);
    tally(colorCounts, cs.color);
    tally(colorCounts, cs.backgroundColor);
    tally(colorCounts, cs.borderColor);
    tally(fontCounts, cs.fontFamily);
  });

  const topColors = Object.entries(colorCounts)
    .filter(([c]) => c && !c.includes('rgba(0, 0, 0, 0)'))
    .sort((a, b) => b[1] - a[1])
    .slice(0, 12)
    .map(([color, count]) => ({ color, count }));

  const topFonts = Object.entries(fontCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6)
    .map(([font, count]) => ({ font, count }));

  // 3. Google Fonts URLs
  const googleFonts = [];
  document.querySelectorAll('link[href*="fonts.googleapis.com"]').forEach(el => {
    googleFonts.push(el.href);
  });

  // 4. Meta
  const meta = {
    title: document.title,
    description: document.querySelector('meta[name="description"]')?.content || '',
    lang: document.documentElement.lang || 'en',
    favicon: document.querySelector('link[rel*="icon"]')?.href || '',
  };

  // 5. Body baseline
  const body = document.body;
  const bodyStyles = {
    backgroundColor: get(body, 'backgroundColor'),
    color: get(body, 'color'),
    fontFamily: get(body, 'fontFamily'),
    fontSize: get(body, 'fontSize'),
    lineHeight: get(body, 'lineHeight'),
  };

  return { topology, topColors, topFonts, googleFonts, meta, bodyStyles };
}
"""


def run_recon(browser, url: str, output_dir: str) -> dict:
    """Executa fase de reconnaissance. Retorna dict com paths/dados.

    `browser` deve ser uma instancia de clow.tools.browser.Browser ja inicializada.
    Salva:
      - <output>/docs/research/RECON.json
      - <output>/docs/research/PAGE_TOPOLOGY.md
      - <output>/docs/research/BEHAVIORS.md
      - <output>/docs/research/screenshots/<viewport>.png
    """
    research_dir = Path(output_dir) / "docs" / "research"
    screenshots_dir = research_dir / "screenshots"
    research_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    parsed = urlparse(url)
    recon = {
        "url": url,
        "domain": parsed.hostname,
        "viewports": [],
    }

    primary_data = None  # dados do desktop sao a verdade

    for vp in VIEWPORTS:
        try:
            browser._page.set_viewport_size({"width": vp["width"], "height": vp["height"]})
        except Exception:
            pass

        # navegar de novo se for o primeiro viewport (browser ja deve estar na pagina)
        # mobile precisa scrollar de novo pra triggerar lazy
        try:
            browser.scroll_to_bottom(delay=0.3)
            browser._page.evaluate("window.scrollTo(0, 0)")
        except Exception:
            pass

        # screenshot
        shot_path = screenshots_dir / f"{vp['name']}.png"
        sr = browser.screenshot(str(shot_path), full_page=True)

        # extrai dados via JS
        try:
            data_raw = browser._page.evaluate(_RECON_JS)
        except Exception as e:
            data_raw = {"error": str(e)}

        recon["viewports"].append({
            "name": vp["name"],
            "width": vp["width"],
            "height": vp["height"],
            "screenshot": f"docs/research/screenshots/{vp['name']}.png" if "error" not in sr else None,
            "screenshot_size": sr.get("size"),
            "data": data_raw,
        })

        if vp["name"] == "desktop":
            primary_data = data_raw

    # === Renderizar PAGE_TOPOLOGY.md ===
    topo_lines = [f"# Page Topology — {recon['domain']}", ""]
    if primary_data and "topology" in primary_data:
        topo_lines.append("Secoes detectadas (desktop 1440x900, ordem visual):")
        topo_lines.append("")
        for s in primary_data["topology"]:
            classes_short = re.sub(r"\s+", " ", s.get("classes", ""))[:80]
            topo_lines.append(
                f"- **{s['tag']}** [{s['width']}x{s['height']}] @y={s['y']} "
                f"id=`{s['id'] or '-'}` classes=`{classes_short}`"
            )
            if s.get("textPreview"):
                topo_lines.append(f"  > {s['textPreview']}")
    (research_dir / "PAGE_TOPOLOGY.md").write_text("\n".join(topo_lines), encoding="utf-8")

    # === Renderizar BEHAVIORS.md ===
    beh_lines = [f"# Behaviors — {recon['domain']}", ""]
    beh_lines.append("> Comportamentos detectados ou suspeitos. Cada item deve ser verificado durante a fase de specs.")
    beh_lines.append("")
    if primary_data:
        gf = primary_data.get("googleFonts", [])
        if gf:
            beh_lines.append("## Fontes Google detectadas")
            for f in gf:
                beh_lines.append(f"- `{f}`")
            beh_lines.append("")
        beh_lines.append("## Cores dominantes")
        for c in (primary_data.get("topColors") or [])[:8]:
            beh_lines.append(f"- `{c['color']}` (uso ~{c['count']}x)")
        beh_lines.append("")
        beh_lines.append("## Familias de fontes")
        for f in (primary_data.get("topFonts") or [])[:4]:
            beh_lines.append(f"- `{f['font']}` (uso ~{f['count']}x)")
    (research_dir / "BEHAVIORS.md").write_text("\n".join(beh_lines), encoding="utf-8")

    # === Salvar RECON.json ===
    (research_dir / "RECON.json").write_text(json.dumps(recon, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "status": "ok",
        "research_dir": str(research_dir),
        "viewports_count": len(recon["viewports"]),
        "sections_detected": len(primary_data.get("topology", [])) if primary_data else 0,
        "topology": primary_data.get("topology", []) if primary_data else [],
        "primary_data": primary_data,
    }
