"""Onboarding — wizard de primeiro acesso do usuario.

Guia o usuario em 5 passos: boas-vindas, negocio, WhatsApp, conhecimento, teste.
Gera prompt do agente com IA baseado nos dados do negocio.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import config
from .logging import log_action

_ONB_DIR = config.CLOW_HOME / "onboarding"
_ONB_DIR.mkdir(parents=True, exist_ok=True)

STEPS = [
    {"id": "welcome", "title": "Bem-vindo ao Clow", "required": False},
    {"id": "business", "title": "Sobre seu negocio", "required": True},
    {"id": "whatsapp", "title": "Conectar WhatsApp", "required": False},
    {"id": "knowledge", "title": "Base de conhecimento", "required": False},
    {"id": "first_test", "title": "Primeiro teste", "required": False},
]


def _data_path(tenant_id: str) -> Path:
    d = _ONB_DIR / tenant_id
    d.mkdir(parents=True, exist_ok=True)
    return d / "progress.json"


def _load(tenant_id: str) -> dict:
    path = _data_path(tenant_id)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"completed_steps": [], "data": {}, "completed": False}


def _save(tenant_id: str, data: dict) -> None:
    _data_path(tenant_id).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def is_onboarding_complete(tenant_id: str) -> bool:
    """Verifica se o tenant completou o onboarding."""
    return _load(tenant_id).get("completed", False)


def get_progress(tenant_id: str) -> dict:
    """Retorna progresso do onboarding."""
    state = _load(tenant_id)
    completed = state.get("completed_steps", [])
    total = len(STEPS)
    return {
        "current_step": len(completed),
        "total_steps": total,
        "completed_steps": completed,
        "percent": int(len(completed) / total * 100) if total else 0,
        "completed": state.get("completed", False),
        "data": state.get("data", {}),
    }


def complete_step(tenant_id: str, step_id: str, step_data: dict | None = None) -> dict:
    """Marca step como completo e salva dados."""
    state = _load(tenant_id)
    if step_id not in state.get("completed_steps", []):
        state.setdefault("completed_steps", []).append(step_id)
    if step_data:
        state.setdefault("data", {}).update({step_id: step_data})
    _save(tenant_id, state)
    return get_progress(tenant_id)


def skip_step(tenant_id: str, step_id: str) -> dict:
    """Pula um step nao obrigatorio."""
    step = next((s for s in STEPS if s["id"] == step_id), None)
    if step and step.get("required"):
        return get_progress(tenant_id)  # Nao pode pular obrigatorio
    return complete_step(tenant_id, step_id)


def finish_onboarding(tenant_id: str) -> dict:
    """Marca onboarding como completo."""
    state = _load(tenant_id)
    state["completed"] = True
    state["completed_at"] = time.time()
    _save(tenant_id, state)
    log_action("onboarding_completed", f"tenant={tenant_id}")
    return {"completed": True}


def generate_agent_prompt(business_data: dict) -> str:
    """Gera prompt do agente com IA baseado nos dados do negocio."""
    btype = business_data.get("business_type", "servicos")
    bname = business_data.get("business_name", "Meu Negocio")
    products = business_data.get("products", "")
    hours = business_data.get("hours", "")
    rules = business_data.get("rules", "")
    tone = business_data.get("tone", "amigavel")

    tone_desc = {
        "formal": "formal e profissional",
        "amigavel": "amigavel e acolhedor",
        "descontraido": "descontraido e divertido",
    }.get(tone, "amigavel e acolhedor")

    prompt_request = f"""Crie um prompt de system para um agente de WhatsApp.

Negocio: {bname}
Tipo: {btype}
Produtos/servicos: {products}
Horario: {hours}
Regras: {rules}
Tom: {tone_desc}

O prompt deve:
- Ter 5-10 regras claras
- Ser em portugues brasileiro
- Incluir o tom especificado
- Mencionar que deve consultar a base de conhecimento
- Ter maximo 300 palavras
- Ser direto, sem introducao

Responda APENAS com o prompt, sem aspas nem explicacao."""

    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            messages=[{"role": "user", "content": prompt_request}],
            max_tokens=500,
        )
        return response.content[0].text.strip() if response.content else _fallback_prompt(bname, products, hours, rules, tone_desc)
    except Exception:
        return _fallback_prompt(bname, products, hours, rules, tone_desc)


def _fallback_prompt(name: str, products: str, hours: str, rules: str, tone: str) -> str:
    """Prompt fallback caso a IA falhe."""
    return f"""Voce e o atendente virtual da {name}. Seja {tone}.

Sobre nos: {products}
Horario: {hours}

Regras:
- Consulte a base de conhecimento para informacoes sobre produtos e precos
- Seja conciso e objetivo nas respostas
- Se nao souber a resposta, diga que vai verificar e retornar
- {rules if rules else 'Nunca invente informacoes'}
- Para reclamacoes, peca desculpas e diga que o responsavel vai entrar em contato
- Sempre cumprimente o cliente de forma cordial"""
