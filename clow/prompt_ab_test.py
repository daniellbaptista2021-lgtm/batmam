"""A/B Testing de Prompts — testa 2 versoes e descobre qual performa melhor.

Cada telefone e fixado em uma variante (hash do phone).
Registra metricas por variante e calcula vencedor.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path

from . import config
from .logging import log_action

_AB_DIR = config.CLOW_HOME / "ab_tests"
_AB_DIR.mkdir(parents=True, exist_ok=True)


def _test_path(instance_id: str) -> Path:
    d = _AB_DIR / instance_id
    d.mkdir(parents=True, exist_ok=True)
    return d / "test.json"


def create_test(tenant_id: str, instance_id: str,
                prompt_a: str, prompt_b: str, sample_size: int = 100) -> dict:
    """Cria um teste A/B. So pode ter 1 por instancia."""
    existing = get_active_test(instance_id)
    if existing and existing.get("status") == "running":
        return {"error": "Ja existe um teste ativo para esta instancia"}

    test = {
        "id": uuid.uuid4().hex[:10],
        "tenant_id": tenant_id,
        "instance_id": instance_id,
        "prompt_a": prompt_a,
        "prompt_b": prompt_b,
        "sample_size": sample_size,
        "status": "running",
        "created_at": time.time(),
        "metrics_a": {"conversations": 0, "messages": 0, "conversions": 0, "revenue": 0},
        "metrics_b": {"conversations": 0, "messages": 0, "conversions": 0, "revenue": 0},
        "phones": {},  # phone -> "A" ou "B"
    }
    _test_path(instance_id).write_text(json.dumps(test, ensure_ascii=False, indent=2), encoding="utf-8")
    log_action("ab_test_created", f"inst={instance_id} sample={sample_size}")
    return test


def get_active_test(instance_id: str) -> dict | None:
    path = _test_path(instance_id)
    if not path.exists():
        return None
    try:
        test = json.loads(path.read_text(encoding="utf-8"))
        if test.get("status") == "running":
            return test
        return test  # Retorna mesmo encerrado para ver resultados
    except Exception:
        return None


def get_variant(instance_id: str, phone: str) -> str:
    """Retorna 'A' ou 'B' para um telefone. Consistente (mesmo phone = mesma variante)."""
    test = get_active_test(instance_id)
    if not test or test.get("status") != "running":
        return "A"  # Sem teste ativo = usa prompt padrao

    # Verifica se phone ja esta assignado
    phones = test.get("phones", {})
    if phone in phones:
        return phones[phone]

    # Hash do phone determina variante
    h = hashlib.md5(phone.encode()).hexdigest()
    variant = "A" if int(h, 16) % 2 == 0 else "B"

    # Salva assignment
    phones[phone] = variant
    test["phones"] = phones
    _test_path(instance_id).write_text(json.dumps(test, ensure_ascii=False), encoding="utf-8")
    return variant


def get_prompt_for_variant(instance_id: str, phone: str) -> str | None:
    """Retorna o prompt da variante. None se sem teste ativo."""
    test = get_active_test(instance_id)
    if not test or test.get("status") != "running":
        return None
    variant = get_variant(instance_id, phone)
    return test.get(f"prompt_{variant.lower()}", "")


def record_interaction(instance_id: str, phone: str, messages_count: int = 1) -> None:
    """Registra interacao na variante do phone."""
    test = get_active_test(instance_id)
    if not test or test.get("status") != "running":
        return
    variant = get_variant(instance_id, phone)
    key = f"metrics_{variant.lower()}"
    test[key]["conversations"] = len(set(test.get("phones", {}).values()))
    test[key]["messages"] += messages_count
    _test_path(instance_id).write_text(json.dumps(test, ensure_ascii=False), encoding="utf-8")

    # Verifica se atingiu sample size
    total = test["metrics_a"]["conversations"] + test["metrics_b"]["conversations"]
    if total >= test.get("sample_size", 100):
        test["status"] = "completed"
        _test_path(instance_id).write_text(json.dumps(test, ensure_ascii=False), encoding="utf-8")


def record_conversion(instance_id: str, phone: str, deal_value: float = 0) -> None:
    """Registra conversao (lead fechou)."""
    test = get_active_test(instance_id)
    if not test:
        return
    variant = get_variant(instance_id, phone)
    key = f"metrics_{variant.lower()}"
    test[key]["conversions"] += 1
    test[key]["revenue"] += deal_value
    _test_path(instance_id).write_text(json.dumps(test, ensure_ascii=False), encoding="utf-8")


def get_results(instance_id: str) -> dict | None:
    """Retorna resultados do teste."""
    test = get_active_test(instance_id)
    if not test:
        return None

    ma = test.get("metrics_a", {})
    mb = test.get("metrics_b", {})
    ca = ma.get("conversations", 0) or 1
    cb = mb.get("conversations", 0) or 1

    conv_a = ma.get("conversions", 0) / ca if ca else 0
    conv_b = mb.get("conversions", 0) / cb if cb else 0

    winner = "B" if conv_b > conv_a else "A" if conv_a > conv_b else "tie"

    return {
        "test_id": test.get("id"),
        "status": test.get("status"),
        "sample_size": test.get("sample_size"),
        "variant_a": {
            "conversations": ma.get("conversations", 0),
            "messages": ma.get("messages", 0),
            "conversions": ma.get("conversions", 0),
            "conversion_rate": round(conv_a * 100, 1),
            "revenue": ma.get("revenue", 0),
        },
        "variant_b": {
            "conversations": mb.get("conversations", 0),
            "messages": mb.get("messages", 0),
            "conversions": mb.get("conversions", 0),
            "conversion_rate": round(conv_b * 100, 1),
            "revenue": mb.get("revenue", 0),
        },
        "winner": winner,
    }


def end_test(instance_id: str, apply_winner: bool = True) -> dict:
    """Finaliza teste. Se apply_winner, atualiza prompt da instancia."""
    test = get_active_test(instance_id)
    if not test:
        return {"error": "Sem teste ativo"}

    results = get_results(instance_id)
    test["status"] = "ended"
    test["ended_at"] = time.time()
    _test_path(instance_id).write_text(json.dumps(test, ensure_ascii=False), encoding="utf-8")

    if apply_winner and results:
        winner = results.get("winner", "A")
        if winner in ("A", "B"):
            prompt = test.get(f"prompt_{winner.lower()}", "")
            if prompt:
                from .whatsapp_agent import get_wa_manager
                manager = get_wa_manager()
                manager.update_instance(instance_id, test["tenant_id"], system_prompt=prompt)
                log_action("ab_test_winner_applied", f"inst={instance_id} winner={winner}")

    return results or {}
