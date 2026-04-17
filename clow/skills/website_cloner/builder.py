"""Fase 4 — Builder: gera React/TSX por spec, valida tsc, monta page.tsx."""
from __future__ import annotations

import logging
import re
from pathlib import Path

from ... import config as config_module
from .nextjs_utils import has_node, run_typecheck

logger = logging.getLogger(__name__)


def _strip_code_fences(text: str) -> str:
    """Remove ```tsx / ```typescript / ``` wrappers se presentes."""
    text = text.strip()
    if text.startswith("```"):
        # tira primeira linha
        text = text.split("\n", 1)[1] if "\n" in text else ""
        # tira ultima ``` se houver
        if text.rstrip().endswith("```"):
            text = text.rsplit("```", 1)[0]
    return text.strip()


def _call_reasoner(system: str, user_text: str, image_path: str | None = None, max_tokens: int = 5000) -> str:
    try:
        from openai import OpenAI
        import base64
    except ImportError:
        return ""
    cfg = config_module
    if not cfg.DEEPSEEK_API_KEY:
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
        logger.error("builder reasoner call falhou: %s", e)
        return ""


def _build_one(spec_info: dict, output_dir: Path, max_retries: int) -> dict:
    """Gera um componente .tsx a partir de um spec. Retorna dict com status/path."""
    from .prompts import BUILDER_SYSTEM, BUILDER_RETRY_SYSTEM

    name = spec_info["name"]
    spec_file = output_dir / spec_info["spec_file"]
    spec_md = spec_file.read_text(encoding="utf-8")
    screenshot = output_dir / spec_info["screenshot"] if spec_info.get("screenshot") else None

    base_user = (
        f"## Spec do componente `{name}`\n\n{spec_md}\n\n"
        f"Gere o arquivo `src/components/{name}.tsx` exportando `{name}` como named export.\n"
        f"Lembre-se: APENAS o codigo, sem markdown fences."
    )

    code = _call_reasoner(
        BUILDER_SYSTEM,
        base_user,
        image_path=str(screenshot) if screenshot and screenshot.exists() else None,
        max_tokens=5000,
    )
    code = _strip_code_fences(code)

    if not code:
        # fallback minimo
        code = (
            f"export function {name}() {{\n"
            f'  return <section className="py-16 text-center"><p>{{"{name}"}}</p></section>;\n'
            f"}}\n"
        )

    component_path = output_dir / "src" / "components" / f"{name}.tsx"
    component_path.parent.mkdir(parents=True, exist_ok=True)
    component_path.write_text(code, encoding="utf-8")

    # Validar com tsc se Node disponivel
    attempts = [{"attempt": 1, "tsc_status": "skipped"}]
    if has_node():
        for attempt in range(1, max_retries + 1):
            check = run_typecheck(output_dir, timeout=90)
            attempts[-1] = {"attempt": attempt, "tsc_status": check["status"]}
            if check["status"] == "ok":
                break
            if attempt >= max_retries:
                attempts[-1]["errors"] = check.get("errors", "")[:1500]
                break
            # Retry com erro inline
            retry_user = (
                base_user
                + "\n\n## Erro do tsc na tentativa anterior:\n```\n"
                + (check.get("errors", "")[:2000])
                + "\n```\n\nCorrija e devolva o componente completo."
            )
            code = _call_reasoner(
                BUILDER_RETRY_SYSTEM,
                retry_user,
                image_path=str(screenshot) if screenshot and screenshot.exists() else None,
                max_tokens=5000,
            )
            code = _strip_code_fences(code) or code
            component_path.write_text(code, encoding="utf-8")
            attempts.append({"attempt": attempt + 1, "tsc_status": "pending"})

    return {
        "name": name,
        "component_file": str(component_path.relative_to(output_dir)),
        "chars": len(code),
        "tsc_attempts": attempts,
    }


def _assemble_page(output_dir: Path, components: list[dict]) -> str:
    """Monta src/app/page.tsx importando todos os componentes em ordem."""
    imports = "\n".join(f'import {{ {c["name"]} }} from "@/components/{c["name"]}";' for c in components)
    renders = "\n      ".join(f"<{c['name']} />" for c in components)
    code = f'''{imports}

export default function Home() {{
  return (
    <main>
      {renders}
    </main>
  );
}}
'''
    page_path = output_dir / "src" / "app" / "page.tsx"
    page_path.write_text(code, encoding="utf-8")
    return str(page_path.relative_to(output_dir))


def run_builder(output_dir: str | Path, specs_result: dict) -> dict:
    """Para cada spec gera componente, valida, e monta page.tsx."""
    output_dir = Path(output_dir)
    specs = specs_result.get("specs", [])
    if not specs:
        return {"status": "error", "error": "nenhum spec disponivel"}

    max_retries = config_module.CLOW_CLONE_BUILDER_RETRIES

    built: list[dict] = []
    for spec_info in specs:
        try:
            r = _build_one(spec_info, output_dir, max_retries)
            built.append(r)
        except Exception as e:
            logger.error("builder falhou pra %s: %s", spec_info.get("name"), e)
            built.append({"name": spec_info["name"], "error": str(e)})

    page_path = _assemble_page(output_dir, [b for b in built if "error" not in b])

    return {
        "status": "ok",
        "components_built": len([b for b in built if "error" not in b]),
        "components_failed": len([b for b in built if "error" in b]),
        "components": built,
        "page_path": page_path,
    }
