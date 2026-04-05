"""CRM Auto Funnel — IA analisa conversas e move leads no pipeline.

Usa Haiku para analisar as ultimas mensagens e decidir se o lead
deve mudar de estagio. Custo minimo (~200 tokens por analise).

Prioridade: arraste manual > movimentacao automatica.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import config
from .logging import log_action

# Diretorio para salvar regras customizadas e sugestoes pendentes
_FUNNEL_DIR = config.CLOW_HOME / "crm_funnel"
_FUNNEL_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_RULES = {
    "novo": {
        "move_to": "contatado",
        "trigger": "quando o agente respondeu a primeira mensagem do cliente",
    },
    "contatado": {
        "move_to": "qualificado",
        "trigger": "quando o cliente demonstrou interesse real perguntando sobre preco, disponibilidade ou detalhes do produto/servico",
    },
    "qualificado": {
        "move_to": "proposta",
        "trigger": "quando o cliente pediu proposta, orcamento ou valores detalhados",
    },
    "proposta": {
        "move_to": "ganho",
        "trigger": "quando o cliente confirmou fechamento, disse sim, aceitou ou confirmou compra",
    },
}


def get_rules(tenant_id: str, instance_id: str) -> dict:
    """Retorna regras customizadas ou padrao."""
    path = _FUNNEL_DIR / tenant_id / instance_id / "rules.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return DEFAULT_RULES


def set_rules(tenant_id: str, instance_id: str, rules: dict) -> None:
    """Salva regras customizadas."""
    d = _FUNNEL_DIR / tenant_id / instance_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "rules.json").write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")


def is_enabled(tenant_id: str, instance_id: str) -> bool:
    """Verifica se o funil automatico esta ativo."""
    path = _FUNNEL_DIR / tenant_id / instance_id / "enabled"
    return path.exists()


def set_enabled(tenant_id: str, instance_id: str, enabled: bool) -> None:
    path = _FUNNEL_DIR / tenant_id / instance_id / "enabled"
    path.parent.mkdir(parents=True, exist_ok=True)
    if enabled:
        path.write_text("1", encoding="utf-8")
    elif path.exists():
        path.unlink()


# ── Sugestoes pendentes ──

def get_pending_suggestions(tenant_id: str, instance_id: str) -> list[dict]:
    """Retorna sugestoes pendentes de movimentacao."""
    path = _FUNNEL_DIR / tenant_id / instance_id / "suggestions.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_suggestions(tenant_id: str, instance_id: str, suggestions: list[dict]) -> None:
    d = _FUNNEL_DIR / tenant_id / instance_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "suggestions.json").write_text(json.dumps(suggestions, ensure_ascii=False), encoding="utf-8")


def add_suggestion(tenant_id: str, instance_id: str, lead_id: str,
                   current_stage: str, suggested_stage: str,
                   reason: str, confidence: float) -> None:
    """Adiciona sugestao pendente."""
    suggestions = get_pending_suggestions(tenant_id, instance_id)
    # Remove sugestao anterior do mesmo lead
    suggestions = [s for s in suggestions if s.get("lead_id") != lead_id]
    suggestions.append({
        "lead_id": lead_id,
        "current_stage": current_stage,
        "suggested_stage": suggested_stage,
        "reason": reason,
        "confidence": confidence,
        "created_at": time.time(),
    })
    _save_suggestions(tenant_id, instance_id, suggestions)


def dismiss_suggestion(tenant_id: str, instance_id: str, lead_id: str) -> None:
    """Remove sugestao pendente."""
    suggestions = get_pending_suggestions(tenant_id, instance_id)
    suggestions = [s for s in suggestions if s.get("lead_id") != lead_id]
    _save_suggestions(tenant_id, instance_id, suggestions)


# ── Analise com IA ──

def analyze_conversation(tenant_id: str, lead_id: str, lead_status: str,
                         last_messages: list[dict], rules: dict) -> dict | None:
    """Analisa a conversa e retorna sugestao de movimentacao.

    Usa Haiku para economia. Prompt curto e focado.

    Returns None se nao ha sugestao, ou dict com:
        {should_move, suggested_stage, reason, confidence}
    """
    # Verifica se ha regra para o status atual
    rule = rules.get(lead_status)
    if not rule:
        return None

    # Monta as ultimas mensagens (max 10 para economia)
    msgs_text = ""
    for m in last_messages[-10:]:
        role = "Cliente" if m.get("role") == "user" else "Agente"
        msgs_text += f"{role}: {m.get('content', '')[:200]}\n"

    if not msgs_text.strip():
        return None

    prompt = f"""Analise esta conversa de WhatsApp e responda APENAS com JSON.

Estagio atual do lead: {lead_status}
Regra para mover para "{rule['move_to']}": {rule['trigger']}

Ultimas mensagens:
{msgs_text}

Responda APENAS com este JSON (sem explicacao, sem markdown):
{{"should_move": true/false, "confidence": 0.0 a 1.0, "reason": "motivo em 1 frase curta"}}"""

    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
        )
        text = response.content[0].text.strip() if response.content else ""

        # Parse JSON (tolerante)
        if "{" in text:
            text = text[text.index("{"):text.rindex("}") + 1]
            result = json.loads(text)
            if result.get("should_move"):
                return {
                    "should_move": True,
                    "suggested_stage": rule["move_to"],
                    "reason": result.get("reason", ""),
                    "confidence": min(1.0, max(0.0, float(result.get("confidence", 0.5)))),
                }
    except Exception as e:
        log_action("auto_funnel_error", str(e)[:200], level="error")

    return None


def process_new_message(tenant_id: str, instance_id: str, lead_id: str,
                        lead_status: str, last_messages: list[dict]) -> None:
    """Chamado apos cada mensagem recebida. Analisa e move/sugere.

    - confidence > 0.8 e auto_move ativo: move automaticamente
    - confidence 0.5-0.8: cria sugestao pendente
    - confidence < 0.5: ignora
    """
    if not is_enabled(tenant_id, instance_id):
        return
    if lead_status in ("ganho", "perdido"):
        return

    rules = get_rules(tenant_id, instance_id)
    result = analyze_conversation(tenant_id, lead_id, lead_status, last_messages, rules)

    if not result or not result.get("should_move"):
        return

    confidence = result["confidence"]
    suggested = result["suggested_stage"]
    reason = result.get("reason", "")

    from .crm_models import get_lead, change_lead_status, add_activity

    lead = get_lead(lead_id, tenant_id)
    if not lead:
        return

    # Verifica se ultimo move foi manual — se sim, nao sobrepoe
    if lead.get("custom_fields"):
        try:
            cf = json.loads(lead["custom_fields"]) if isinstance(lead["custom_fields"], str) else lead["custom_fields"]
            if cf.get("last_move_source") == "manual":
                # Reseta flag para permitir proximo auto-move
                cf["last_move_source"] = ""
                from .crm_models import update_lead
                update_lead(lead_id, tenant_id, custom_fields=cf)
                return
        except Exception:
            pass

    if confidence >= 0.8:
        # Move automaticamente
        change_lead_status(lead_id, tenant_id, suggested)
        add_activity(lead_id, tenant_id, "status_change",
                     f"🤖 IA moveu de {lead_status} → {suggested}: {reason}")
        # Salva que foi auto
        try:
            cf = json.loads(lead.get("custom_fields") or "{}") if isinstance(lead.get("custom_fields"), str) else (lead.get("custom_fields") or {})
            cf["last_move_source"] = "auto"
            from .crm_models import update_lead
            update_lead(lead_id, tenant_id, custom_fields=cf)
        except Exception:
            pass
        log_action("auto_funnel_move", f"lead={lead_id} {lead_status}→{suggested} conf={confidence:.2f}")

    elif confidence >= 0.5:
        # Sugere movimentacao
        add_suggestion(tenant_id, instance_id, lead_id, lead_status, suggested, reason, confidence)
        add_activity(lead_id, tenant_id, "note",
                     f"🤖 IA sugeriu mover para {suggested} (aguardando aprovacao): {reason}")
        log_action("auto_funnel_suggest", f"lead={lead_id} {lead_status}→{suggested} conf={confidence:.2f}")
