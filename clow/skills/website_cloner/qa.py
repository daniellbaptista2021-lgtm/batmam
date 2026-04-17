"""Fase 5 — QA: screenshot do clone, comparacao visual, retry de discrepancias."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from .nextjs_utils import has_node, run_build

logger = logging.getLogger(__name__)


def run_qa(browser_class, output_dir: str | Path, builder_result: dict) -> dict:
    """Constroi clone, abre via file:// (build estatico) ou skipa se Node ausente.

    Estrategia simplificada (MVP):
    - Roda `npm run build`
    - Se OK, faz screenshot da pagina renderizada via file:// nao funciona pra Next standalone
    - Como alternativa: faz screenshot do HTML estatico em out/ se output: 'export', ou skip
    - Retorna status do build + paths
    """
    output_dir = Path(output_dir)
    qa_dir = output_dir / "docs" / "research" / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)

    build = {"status": "skipped", "reason": "node nao instalado"}
    if has_node():
        build = run_build(output_dir, timeout=300)

    return {
        "status": "ok",
        "build": build,
        "qa_dir": str(qa_dir),
        "note": "QA visual side-by-side roda em iteracao 2 (precisa servidor next start em background)",
    }
