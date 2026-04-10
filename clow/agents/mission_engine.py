"""Mission Engine — planeja e orquestra missoes autonomas."""
from __future__ import annotations
import json
import time
import asyncio
from typing import Callable
from pathlib import Path

from ..generators.base import ask_ai, STATIC_DIR, file_url, slugify
from ..database import (
    create_mission, get_mission, update_mission, update_mission_step,
)

STEP_TIMEOUT = 300  # 5 min por etapa
MAX_RETRIES = 3

# Modelos por complexidade
MODELS = {
    "plan": "deepseek-chat",
    "simple": "deepseek-chat",
    "medium": "deepseek-chat",
    "complex": "deepseek-reasoner",
}


def plan_mission(description: str) -> dict:
    """Analisa descricao e gera plano com etapas."""
    system = """Voce e um gerente de projetos AI. Analise o pedido e crie um plano de execucao.

Retorne APENAS JSON valido neste formato:
{
  "title": "Titulo curto da missao",
  "steps": [
    {
      "title": "Nome da etapa",
      "description": "O que fazer nesta etapa em detalhe",
      "type": "generate_html|generate_file|generate_text|api_call|deploy|analyze",
      "model": "simple|medium|complex",
      "outputs": ["descricao do que esta etapa produz"]
    }
  ],
  "estimated_minutes": 5
}

Regras:
- Minimo 3 etapas, maximo 12
- Cada etapa deve ser autocontida e executavel
- type define o que a etapa faz
- model: simple=texto/copy, medium=codigo/landing, complex=sistema/analise
- Etapas devem ser em ordem logica de dependencia
- Sempre incluir etapa final de entrega/resumo
- Sempre em portugues brasileiro"""

    raw = ask_ai(description, system=system, model=MODELS["plan"], max_tokens=2048)
    text = raw.strip()
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:])
    if text.endswith("```"):
        text = text[:-3]

    data = json.loads(text.strip())
    return data


async def execute_mission(
    mission_id: str,
    user_id: str,
    on_progress: Callable | None = None,
):
    """Executa missao etapa por etapa. Roda em background."""
    mission = get_mission(mission_id)
    if not mission:
        return

    update_mission(mission_id, status="running", current_step=0)
    if on_progress:
        await on_progress(mission_id, "started", {"title": mission["title"], "total": mission["total_steps"]})

    context = {}  # Contexto compartilhado entre etapas
    plan = mission["plan"]

    for i, step_plan in enumerate(plan):
        step_title = step_plan.get("title", f"Etapa {i+1}")
        step_type = step_plan.get("type", "generate_text")
        step_model_level = step_plan.get("model", "simple")
        model = MODELS.get(step_model_level, MODELS["simple"])

        update_mission(mission_id, current_step=i)
        update_mission_step(mission_id, i, status="running", started_at=time.time())

        if on_progress:
            await on_progress(mission_id, "step_start", {"step": i, "title": step_title, "total": len(plan)})

        success = False
        for attempt in range(MAX_RETRIES):
            try:
                result = await asyncio.get_event_loop().run_in_executor(
                    None, _execute_step, step_plan, context, model, mission["description"]
                )
                context.update(result.get("context_updates", {}))
                context[f"step_{i}_result"] = result.get("output", "")

                update_mission_step(mission_id, i,
                    status="completed",
                    result_json=json.dumps(result, default=str),
                    completed_at=time.time(),
                    attempts=attempt + 1,
                )
                update_mission(mission_id, context_json=json.dumps(context, default=str))

                if on_progress:
                    await on_progress(mission_id, "step_done", {
                        "step": i, "title": step_title, "total": len(plan),
                        "output": result.get("output", ""),
                        "file": result.get("file"),
                    })

                success = True
                break

            except Exception as e:
                update_mission_step(mission_id, i,
                    error=str(e)[:500],
                    attempts=attempt + 1,
                )
                if on_progress:
                    await on_progress(mission_id, "step_retry", {
                        "step": i, "title": step_title, "attempt": attempt + 1,
                        "error": str(e)[:200],
                    })

                if attempt >= MAX_RETRIES - 1:
                    update_mission_step(mission_id, i, status="failed")
                    update_mission(mission_id, status="failed", error_count=mission.get("error_count", 0) + 1)

                    if on_progress:
                        await on_progress(mission_id, "step_failed", {
                            "step": i, "title": step_title, "error": str(e)[:200],
                        })
                    return

        if not success:
            return

    # Missao concluida
    update_mission(mission_id, status="completed", completed_at=time.time())

    # Gerar resumo final
    summary = _generate_summary(mission["description"], context, plan)

    if on_progress:
        await on_progress(mission_id, "completed", {
            "title": mission["title"],
            "summary": summary,
            "context": context,
        })


def _execute_step(step: dict, context: dict, model: str, mission_desc: str) -> dict:
    """Executa uma etapa individual."""
    step_type = step.get("type", "generate_text")
    step_desc = step.get("description", "")
    step_title = step.get("title", "")

    # Constroi contexto para a AI
    ctx_summary = ""
    for k, v in context.items():
        if k.startswith("step_") and isinstance(v, str):
            ctx_summary += f"- {k}: {v[:200]}\n"
        elif k.startswith("file_"):
            ctx_summary += f"- Arquivo criado: {v}\n"
        elif k.startswith("url_"):
            ctx_summary += f"- URL: {v}\n"

    if step_type == "generate_html":
        return _step_generate_html(step, context, model, mission_desc, ctx_summary)
    elif step_type == "generate_file":
        return _step_generate_file(step, context, model, mission_desc, ctx_summary)
    elif step_type == "analyze":
        return _step_analyze(step, context, model, mission_desc, ctx_summary)
    else:
        return _step_generate_text(step, context, model, mission_desc, ctx_summary)


def _step_generate_html(step: dict, context: dict, model: str, mission_desc: str, ctx: str) -> dict:
    """Gera uma pagina HTML."""
    system = f"""Voce e um web developer expert. Gere HTML completo e funcional.
Missao completa: {mission_desc}
Etapa atual: {step.get('title')} — {step.get('description')}
Contexto das etapas anteriores:
{ctx}

Regras:
- HTML unico arquivo completo com <!DOCTYPE html>
- Use Tailwind CSS via CDN
- Responsivo, mobile-first, design profissional
- Textos em portugues brasileiro
- Se houver navegacao entre paginas, use anchors ou links relativos
- Retorne APENAS o HTML, sem markdown, sem explicacoes"""

    html = ask_ai(step.get("description", ""), system=system, model=model, max_tokens=4096)
    if html.startswith("```"):
        html = "\n".join(html.split("\n")[1:])
    if html.endswith("```"):
        html = html[:-3]
    html = html.strip()

    # Salva arquivo
    slug = slugify(step.get("title", "page")[:30])
    ts = int(time.time())
    folder = context.get("mission_folder", f"mission-{ts}")
    context["mission_folder"] = folder

    out_dir = STATIC_DIR / "pages" / folder
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{slug}.html"
    filepath = out_dir / filename
    filepath.write_text(html, encoding="utf-8")

    url = file_url(f"static/pages/{folder}/{filename}")
    context[f"url_{slug}"] = url
    context[f"file_{slug}"] = str(filepath)

    return {
        "output": f"Pagina '{step.get('title')}' criada: {url}",
        "file": {"type": "landing_page", "name": filename, "url": url, "size": f"{filepath.stat().st_size / 1024:.1f} KB"},
        "context_updates": {f"url_{slug}": url, f"file_{slug}": str(filepath), "mission_folder": folder},
    }


def _step_generate_file(step: dict, context: dict, model: str, mission_desc: str, ctx: str) -> dict:
    """Gera arquivo (docx, xlsx, etc) — delega para generators."""
    desc = step.get("description", "")

    # Detecta tipo pelo conteudo
    from ..generators.dispatcher import detect, run_generator
    gen_module, gen_type = detect(desc)

    if gen_module:
        result = run_generator(gen_module, desc)
        if result.get("type") == "text":
            return {"output": result["content"], "context_updates": {}}
        return {
            "output": f"Arquivo criado: {result.get('name')} ({result.get('size', 0)} bytes)",
            "file": result,
            "context_updates": {f"file_{gen_type}": result.get("url", "")},
        }

    # Fallback: gera texto
    return _step_generate_text(step, context, model, mission_desc, ctx)


def _step_generate_text(step: dict, context: dict, model: str, mission_desc: str, ctx: str) -> dict:
    """Gera texto/analise/copy."""
    system = f"""Voce e um especialista executando uma etapa de uma missao.
Missao: {mission_desc}
Etapa: {step.get('title')} — {step.get('description')}
Contexto anterior:
{ctx}

Execute esta etapa com qualidade profissional. Portugues brasileiro."""

    text = ask_ai(step.get("description", ""), system=system, model=model, max_tokens=2048)
    return {"output": text, "context_updates": {}}


def _step_analyze(step: dict, context: dict, model: str, mission_desc: str, ctx: str) -> dict:
    """Analise e recomendacoes."""
    system = f"""Voce e um analista de negocios digitais e trafego pago.
Missao: {mission_desc}
Etapa: {step.get('title')} — {step.get('description')}
Contexto e dados anteriores:
{ctx}

Faca uma analise profunda e pratica. Inclua metricas, recomendacoes e proximos passos.
Use tabelas markdown quando apropriado. Portugues brasileiro."""

    text = ask_ai(step.get("description", ""), system=system, model=model, max_tokens=2048)
    return {"output": text, "context_updates": {}}


def _generate_summary(description: str, context: dict, plan: list) -> str:
    """Gera resumo final da missao."""
    urls = [v for k, v in context.items() if k.startswith("url_")]
    files = [v for k, v in context.items() if k.startswith("file_") and v.startswith("http")]

    lines = ["## Missao Concluida\n"]
    lines.append(f"**{description[:100]}**\n")
    lines.append(f"**{len(plan)} etapas executadas com sucesso.**\n")

    if urls:
        lines.append("### Links criados:")
        for u in urls:
            lines.append(f"- {u}")

    if files:
        lines.append("\n### Arquivos gerados:")
        for f in files:
            lines.append(f"- {f}")

    return "\n".join(lines)
