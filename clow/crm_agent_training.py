"""CRM Agent Training — treina o agente por correcoes nas conversas.

O usuario corrige respostas do agente. As correcoes sao consolidadas
em regras injetadas no system prompt para melhorar respostas futuras.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from . import config
from .logging import log_action

_TRAINING_DIR = config.CLOW_HOME / "crm_training"
_TRAINING_DIR.mkdir(parents=True, exist_ok=True)


def _corrections_path(tenant_id: str, instance_id: str) -> Path:
    d = _TRAINING_DIR / tenant_id / instance_id
    d.mkdir(parents=True, exist_ok=True)
    return d / "corrections.json"


def _load_corrections(tenant_id: str, instance_id: str) -> list[dict]:
    path = _corrections_path(tenant_id, instance_id)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_corrections(tenant_id: str, instance_id: str, corrections: list[dict]) -> None:
    path = _corrections_path(tenant_id, instance_id)
    path.write_text(json.dumps(corrections, ensure_ascii=False, indent=2), encoding="utf-8")


def record_correction(tenant_id: str, instance_id: str,
                      client_message: str, original_response: str,
                      corrected_response: str, context: list[str] | None = None) -> str:
    """Registra uma correcao feita pelo usuario. Retorna ID da correcao."""
    corrections = _load_corrections(tenant_id, instance_id)
    correction_id = uuid.uuid4().hex[:8]
    corrections.append({
        "id": correction_id,
        "timestamp": time.time(),
        "client_message": client_message,
        "original_response": original_response,
        "corrected_response": corrected_response,
        "context": context or [],
        "applied": True,
    })
    _save_corrections(tenant_id, instance_id, corrections)
    log_action("agent_correction", f"inst={instance_id} id={correction_id}")
    return correction_id


def get_corrections(tenant_id: str, instance_id: str) -> list[dict]:
    """Lista todas as correcoes."""
    return _load_corrections(tenant_id, instance_id)


def delete_correction(tenant_id: str, instance_id: str, correction_id: str) -> bool:
    """Remove uma correcao."""
    corrections = _load_corrections(tenant_id, instance_id)
    new = [c for c in corrections if c.get("id") != correction_id]
    if len(new) == len(corrections):
        return False
    _save_corrections(tenant_id, instance_id, new)
    return True


def get_training_context(tenant_id: str, instance_id: str) -> str:
    """Gera contexto de treinamento para injetar no system prompt.

    Transforma correcoes em regras claras que o agente segue.
    """
    # Tenta usar regras consolidadas primeiro
    rules_path = _TRAINING_DIR / tenant_id / instance_id / "consolidated_rules.txt"
    if rules_path.exists():
        try:
            rules = rules_path.read_text(encoding="utf-8").strip()
            if rules:
                return f"\n## Regras aprendidas (IMPORTANTE — siga estas regras)\n{rules}\n"
        except Exception:
            pass

    # Senao, gera a partir das correcoes individuais
    corrections = _load_corrections(tenant_id, instance_id)
    if not corrections:
        return ""

    rules = "\n## Correcoes aprendidas (IMPORTANTE — siga estas regras)\n"
    for c in corrections[-20:]:  # Max 20 para nao inflar o prompt
        rules += f"- Quando perguntarem sobre '{c['client_message'][:80]}': "
        rules += f"NAO responda '{c['original_response'][:60]}...'. "
        rules += f"Responda: '{c['corrected_response'][:100]}'\n"

    return rules


def consolidate_corrections(tenant_id: str, instance_id: str) -> str:
    """Usa IA para consolidar correcoes em regras claras e concisas."""
    corrections = _load_corrections(tenant_id, instance_id)
    if not corrections:
        return ""

    corrections_text = ""
    for c in corrections:
        corrections_text += f"Pergunta: {c['client_message']}\n"
        corrections_text += f"Resposta errada: {c['original_response']}\n"
        corrections_text += f"Resposta correta: {c['corrected_response']}\n\n"

    prompt = f"""Consolide estas correcoes de atendimento em regras claras e concisas.
Cada regra deve ser 1 linha. Use formato de lista.
Agrupe correcoes semelhantes em uma unica regra.
Maximo 10 regras.

Correcoes:
{corrections_text}

Responda APENAS com as regras, sem introducao nem conclusao."""

    try:
        from openai import OpenAI
        client = OpenAI(**config.get_deepseek_client_kwargs())
        response = client.chat.completions.create(
            model=config.CLOW_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
        )
        rules = response.choices[0].message.content.strip() if response.choices else ""
        if rules:
            rules_path = _TRAINING_DIR / tenant_id / instance_id / "consolidated_rules.txt"
            rules_path.parent.mkdir(parents=True, exist_ok=True)
            rules_path.write_text(rules, encoding="utf-8")
            log_action("corrections_consolidated", f"inst={instance_id} rules={len(rules.splitlines())}")
        return rules
    except Exception as e:
        log_action("consolidate_error", str(e)[:200], level="error")
        return ""
