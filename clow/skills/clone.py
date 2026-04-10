"""Skill /clone — clona sites e landing pages.

Usage:
    /clone https://site.com
    clow clone https://site.com

Pipeline:
1. Abre site com Playwright, scroll completo, espera lazy loading
2. Screenshot fullpage alta resolucao
3. Baixa assets (imagens, CSS, fontes, SVGs, favicons)
4. Envia screenshot pro Claude Vision pra gerar HTML fiel
5. Salva em workspace/clones/nome-do-site/
"""
import logging
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

CLONES_DIR = Path(os.path.expanduser("~/.clow/clones"))


def clone_site(url: str, output_dir: str = "") -> dict:
    """Clone a website visually.

    Returns dict with paths to generated files.
    """
    from ..tools.browser import Browser, is_available

    if not is_available():
        return {"error": "Playwright nao instalado. Execute: pip install playwright && python -m playwright install chromium"}

    # Parse URL for naming
    parsed = urlparse(url)
    site_name = parsed.hostname.replace(".", "-")
    if not output_dir:
        output_dir = str(CLONES_DIR / site_name)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    result = {"url": url, "output_dir": output_dir, "steps": []}
    browser = Browser(headless=True)

    try:
        # Step 1: Open and scroll
        logger.info("Clone: abrindo %s", url)
        r = browser.open(url, wait="networkidle")
        if "error" in r:
            return {"error": f"Falha ao abrir {url}: {r['error']}"}
        result["steps"].append({"step": "open", "title": r.get("title", ""), "status": "ok"})

        # Scroll to bottom to trigger lazy loading
        browser.scroll_to_bottom(delay=0.3)
        # Dismiss cookie banners
        for sel in [
            "button:has-text('Aceitar')", "button:has-text('Accept')",
            "button:has-text('OK')", "button:has-text('Concordo')",
            "[class*='cookie'] button", "[id*='cookie'] button",
        ]:
            try:
                browser.click(sel)
            except Exception:
                pass
        result["steps"].append({"step": "scroll", "status": "ok"})

        # Step 2: Screenshot fullpage
        screenshot_path = str(Path(output_dir) / "original.png")
        sr = browser.screenshot(screenshot_path, full_page=True)
        if "error" in sr:
            result["steps"].append({"step": "screenshot", "status": "error", "error": sr["error"]})
        else:
            result["screenshot"] = screenshot_path
            result["steps"].append({"step": "screenshot", "path": screenshot_path, "size": sr["size"], "status": "ok"})

        # Step 3: Download assets
        logger.info("Clone: baixando assets")
        assets = browser.download_assets(output_dir)
        result["assets"] = assets
        result["steps"].append({"step": "assets", "downloaded": assets["downloaded"], "status": "ok"})

        # Step 4: Extract HTML for reference
        page_html = browser.html()
        (Path(output_dir) / "original.html").write_text(page_html, encoding="utf-8")

        # Step 5: Generate clone HTML via Claude Vision
        logger.info("Clone: gerando HTML via Claude Vision")
        clone_html = _generate_html_from_screenshot(screenshot_path, url, assets, output_dir)
        if clone_html:
            html_path = str(Path(output_dir) / "index.html")
            Path(html_path).write_text(clone_html, encoding="utf-8")
            result["html"] = html_path
            result["steps"].append({"step": "generate_html", "path": html_path, "chars": len(clone_html), "status": "ok"})
        else:
            result["steps"].append({"step": "generate_html", "status": "error", "error": "Falha na geracao"})

        # Step 6: Screenshot clone for comparison
        if clone_html:
            try:
                browser2 = Browser(headless=True)
                browser2.open(f"file://{html_path}")
                clone_screenshot = str(Path(output_dir) / "clone.png")
                browser2.screenshot(clone_screenshot, full_page=True)
                result["clone_screenshot"] = clone_screenshot
                result["steps"].append({"step": "compare_screenshot", "path": clone_screenshot, "status": "ok"})
                browser2.close()
            except Exception as e:
                result["steps"].append({"step": "compare_screenshot", "status": "error", "error": str(e)})

        result["status"] = "ok"

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        logger.error("Clone error: %s", e)
    finally:
        browser.close()

    return result


def _generate_html_from_screenshot(screenshot_path: str, url: str, assets: dict, output_dir: str) -> str:
    """Use DeepSeek Vision to generate HTML from screenshot."""
    import base64

    try:
        from openai import OpenAI
        from .. import config
    except ImportError:
        logger.error("openai package not installed")
        return ""

    if not config.DEEPSEEK_API_KEY:
        logger.error("No DEEPSEEK_API_KEY configured")
        return ""

    # Read screenshot
    with open(screenshot_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    # Build asset list for reference
    asset_files = []
    for a in assets.get("files", []):
        asset_files.append(a["file"])

    asset_list = "\n".join(f"- {f}" for f in asset_files[:20]) if asset_files else "Nenhum asset baixado"

    prompt = f"""Analise este screenshot de {url} e gere um HTML completo que reproduza fielmente o layout, cores, tipografia e espacamento.

Requisitos:
- HTML unico com CSS inline (tag <style>)
- Responsivo mobile-first
- Use as imagens baixadas com paths relativos: {asset_list}
- Reproduza fielmente: cores, fontes, espacamentos, layout
- Inclua todas as secoes visiveis no screenshot
- Use Google Fonts se necessario
- Nao use frameworks CSS externos, apenas CSS puro
- O HTML deve ser completo e funcional
- Inclua meta viewport, charset utf-8, lang pt-BR

Retorne APENAS o HTML completo, sem explicacoes."""

    client = OpenAI(**config.get_deepseek_client_kwargs())
    try:
        response = client.chat.completions.create(
            model=config.CLOW_MODEL,
            max_tokens=16000,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        html = response.choices[0].message.content or ""

        # Clean — extract HTML if wrapped in code block
        if "```html" in html:
            html = html.split("```html", 1)[1].split("```", 1)[0]
        elif "```" in html:
            html = html.split("```", 1)[1].split("```", 1)[0]

        return html.strip()
    except Exception as e:
        logger.error("Claude Vision error: %s", e)
        return ""


def format_result(result: dict) -> str:
    """Format clone result for display."""
    if result.get("status") == "error":
        return f"Erro ao clonar: {result.get('error', 'desconhecido')}"

    lines = [f"Site clonado: {result['url']}", f"Output: {result['output_dir']}", ""]
    for step in result.get("steps", []):
        status = "ok" if step["status"] == "ok" else "erro"
        line = f"  [{status}] {step['step']}"
        if "path" in step:
            line += f" -> {step['path']}"
        if "downloaded" in step:
            line += f" ({step['downloaded']} arquivos)"
        if "chars" in step:
            line += f" ({step['chars']} chars)"
        if "error" in step:
            line += f" ({step['error']})"
        lines.append(line)

    if result.get("html"):
        lines.append(f"\nHTML gerado: {result['html']}")
    if result.get("screenshot"):
        lines.append(f"Screenshot original: {result['screenshot']}")
    if result.get("clone_screenshot"):
        lines.append(f"Screenshot clone: {result['clone_screenshot']}")

    return "\n".join(lines)
