"""Pipeline orquestrador das 5 fases do website cloner."""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from ... import config as config_module

logger = logging.getLogger(__name__)


def _slug_domain(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "site").replace(".", "-")
    return re.sub(r"[^a-zA-Z0-9-]", "", host) or "site"


def clone_site(
    url: str,
    output_dir: str = "",
    skip_qa: bool = False,
    skip_build: bool = False,
    progress_cb=None,
) -> dict:
    """Clone completo: 5 fases. Retorna dict serializavel com status e paths.

    Args:
        url: URL alvo (com http/https)
        output_dir: diretorio de output. Vazio => ~/.clow/clones/<slug>
        skip_qa: pula fase 5
        skip_build: pula `npm install` na foundation e `npm run build` no QA
        progress_cb: callable(phase: str, status: str, info: dict) -> None
    """
    from ...tools.browser import Browser, is_available  # type: ignore

    def emit(phase: str, status: str, info: dict | None = None):
        if progress_cb:
            try:
                progress_cb(phase, status, info or {})
            except Exception:
                pass

    if not url.startswith(("http://", "https://")):
        return {"status": "error", "error": "URL deve iniciar com http:// ou https://"}

    if not is_available():
        return {
            "status": "error",
            "error": "Playwright nao instalado. pip install playwright && python -m playwright install chromium",
        }

    cfg = config_module
    if not cfg.DEEPSEEK_API_KEY:
        return {"status": "error", "error": "DEEPSEEK_API_KEY nao configurada (.env)"}

    if not output_dir:
        output_dir = str(Path(cfg.CLOW_CLONE_OUTPUT_DIR) / _slug_domain(url))
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    started = time.time()
    result: dict = {
        "url": url,
        "output_dir": output_dir,
        "phases": {},
        "started_at": started,
    }

    browser = Browser(headless=True)
    try:
        # ── Fase 0: abrir pagina ──
        emit("open", "running", {"url": url})
        r = browser.open(url, wait="networkidle")
        if "error" in r:
            return {**result, "status": "error", "error": f"falha ao abrir {url}: {r['error']}"}
        result["title"] = r.get("title", "")
        emit("open", "ok", {"title": result["title"]})

        # Dismiss cookie banners (best-effort)
        for sel in [
            "button:has-text('Aceitar')", "button:has-text('Accept')",
            "button:has-text('OK')", "button:has-text('Concordo')",
            "[id*='cookie'] button", "[class*='cookie'] button",
        ]:
            try: browser.click(sel)
            except Exception: pass

        # ── Fase 1: Reconnaissance ──
        emit("recon", "running", {})
        from .recon import run_recon
        recon = run_recon(browser, url, output_dir)
        result["phases"]["recon"] = recon
        emit("recon", recon.get("status", "ok"), {
            "viewports": recon.get("viewports_count"),
            "sections": recon.get("sections_detected"),
        })

        # ── Fase 2: Foundation ──
        emit("foundation", "running", {})
        from .foundation import run_foundation
        foundation = run_foundation(
            template_dir=cfg.CLOW_CLONE_TEMPLATE_DIR,
            output_dir=output_dir,
            recon_result=recon,
            browser=browser,
            do_npm_install=(not skip_build),
        )
        result["phases"]["foundation"] = foundation
        emit("foundation", foundation.get("status", "ok"), {
            "assets": foundation.get("assets", {}).get("downloaded"),
            "npm": foundation.get("npm_install", {}).get("status"),
        })

        # ── Fase 3: Specs ──
        emit("specs", "running", {})
        from .specs import run_specs
        specs = run_specs(browser, output_dir, recon)
        result["phases"]["specs"] = specs
        emit("specs", specs.get("status", "ok"), {"count": specs.get("specs_count")})

        if specs.get("status") != "ok":
            result["status"] = "partial"
            result["error"] = specs.get("error", "specs falhou")
            return result

        # ── Fase 4: Builder ──
        emit("builder", "running", {})
        from .builder import run_builder
        builder = run_builder(output_dir, specs)
        result["phases"]["builder"] = builder
        emit("builder", builder.get("status", "ok"), {
            "built": builder.get("components_built"),
            "failed": builder.get("components_failed"),
        })

        # ── Fase 5: QA ──
        if not skip_qa:
            emit("qa", "running", {})
            from .qa import run_qa
            qa = run_qa(Browser, output_dir, builder)
            result["phases"]["qa"] = qa
            emit("qa", qa.get("status", "ok"), {"build": qa.get("build", {}).get("status")})
        else:
            result["phases"]["qa"] = {"status": "skipped"}

        result["status"] = "ok"
    except Exception as e:
        logger.exception("pipeline crashed")
        result["status"] = "error"
        result["error"] = str(e)
    finally:
        try: browser.close()
        except Exception: pass
        result["duration_seconds"] = round(time.time() - started, 1)

    return result


def format_result(result: dict) -> str:
    """Formata o dict de clone_site() pra texto bonito (CLI/log)."""
    if result.get("status") == "error" and not result.get("phases"):
        return f"[ERRO] {result.get('error', 'desconhecido')}"

    out = []
    out.append(f"Clone: {result['url']}")
    out.append(f"Output: {result['output_dir']}")
    if result.get("title"):
        out.append(f"Title: {result['title']}")
    out.append(f"Duracao: {result.get('duration_seconds', 0)}s")
    out.append(f"Status: {result.get('status', 'unknown')}")
    out.append("")

    phases = result.get("phases", {})
    order = ["recon", "foundation", "specs", "builder", "qa"]
    for name in order:
        ph = phases.get(name)
        if not ph:
            continue
        st = ph.get("status", "?")
        line = f"  [{st:>7}] {name}"
        if name == "recon":
            line += f"  viewports={ph.get('viewports_count')} sections={ph.get('sections_detected')}"
        elif name == "foundation":
            ai = ph.get("assets", {}) or {}
            line += f"  assets={ai.get('downloaded', 0)} npm={ph.get('npm_install', {}).get('status')}"
        elif name == "specs":
            line += f"  count={ph.get('specs_count')}"
        elif name == "builder":
            line += f"  built={ph.get('components_built')} failed={ph.get('components_failed')}"
        elif name == "qa":
            line += f"  build={ph.get('build', {}).get('status')}"
        out.append(line)

    if result.get("error"):
        out.append("")
        out.append(f"[erro] {result['error']}")

    out.append("")
    out.append(f"-> abra {result['output_dir']} para inspecionar; rode `npm install && npm run dev` se ainda nao foi feito")
    return "\n".join(out)
