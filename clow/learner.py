"""Self-Learning — analisa logs e extrai padroes para aprendizado automatico.

Funcionalidades:
- Detecta correcoes do usuario e gera regras
- Identifica sequencias de tools frequentes
- Detecta erros recorrentes e gera regras preventivas
- Identifica skills mais usados
- Gera ~/.clow/memory/learned.md com insights
"""

from __future__ import annotations
import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

from . import config
from .logging import log_action

LEARNED_FILE = config.MEMORY_DIR / "learned.md"
LOG_FILE = config.CLOW_HOME / "logs" / "clow.jsonl"


def analyze_logs(max_lines: int = 5000) -> dict[str, Any]:
    """Analisa logs e extrai padroes de aprendizado.

    Returns dict com todas as analises:
    - corrections: correcoes do usuario
    - tool_sequences: sequencias frequentes de tools
    - recurring_errors: erros recorrentes
    - skill_usage: skills mais usados
    """
    if not LOG_FILE.exists():
        return {"error": "Arquivo de logs nao encontrado"}

    entries = _load_log_entries(max_lines)
    if not entries:
        return {"error": "Nenhuma entrada de log encontrada"}

    corrections = _extract_corrections(entries)
    tool_sequences = _extract_tool_sequences(entries)
    recurring_errors = _extract_recurring_errors(entries)
    skill_usage = _extract_skill_usage(entries)

    return {
        "total_entries": len(entries),
        "corrections": corrections,
        "tool_sequences": tool_sequences,
        "recurring_errors": recurring_errors,
        "skill_usage": skill_usage,
        "analyzed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def generate_learned_md(analysis: dict[str, Any] | None = None) -> str:
    """Gera ou atualiza learned.md com insights dos logs.

    Returns o conteudo gerado.
    """
    if analysis is None:
        analysis = analyze_logs()

    if "error" in analysis:
        return f"# Sem dados\n{analysis['error']}"

    parts = [
        "# Clow Self-Learning",
        f"Atualizado em: {analysis.get('analyzed_at', 'N/A')}",
        f"Entradas analisadas: {analysis.get('total_entries', 0)}",
        "",
    ]

    # Correcoes do usuario
    corrections = analysis.get("corrections", [])
    if corrections:
        parts.append("## Regras Aprendidas (Correcoes do Usuario)")
        parts.append("")
        for i, c in enumerate(corrections[:20], 1):
            parts.append(f"{i}. {c}")
        parts.append("")

    # Sequencias de tools frequentes
    tool_seqs = analysis.get("tool_sequences", [])
    if tool_seqs:
        parts.append("## Sequencias de Tools Frequentes")
        parts.append("")
        for seq_info in tool_seqs[:10]:
            seq = seq_info["sequence"]
            count = seq_info["count"]
            parts.append(f"- `{' -> '.join(seq)}` ({count}x)")
        parts.append("")

    # Erros recorrentes
    errors = analysis.get("recurring_errors", [])
    if errors:
        parts.append("## Erros Recorrentes (Regras Preventivas)")
        parts.append("")
        for err_info in errors[:10]:
            parts.append(f"- **{err_info['error_type']}** ({err_info['count']}x): {err_info['suggestion']}")
        parts.append("")

    # Skills mais usados
    skills = analysis.get("skill_usage", [])
    if skills:
        parts.append("## Skills Mais Usados")
        parts.append("")
        for skill_info in skills[:10]:
            parts.append(f"- `/{skill_info['name']}` ({skill_info['count']}x)")
        parts.append("")

    content = "\n".join(parts)

    # Salva o arquivo
    LEARNED_FILE.parent.mkdir(parents=True, exist_ok=True)
    LEARNED_FILE.write_text(content, encoding="utf-8")
    log_action("self_learn", f"learned.md gerado ({len(content)} chars)")

    return content


def load_learned_context() -> str:
    """Carrega learned.md para injecao no system prompt."""
    if not LEARNED_FILE.exists():
        return ""
    try:
        content = LEARNED_FILE.read_text(encoding="utf-8").strip()
        return content if content else ""
    except Exception:
        return ""


def generate_report() -> str:
    """Gera relatorio legivel das aprendizagens."""
    analysis = analyze_logs()

    if "error" in analysis:
        return f"Sem dados para analisar: {analysis['error']}"

    lines = [
        "=== Relatorio Self-Learning ===",
        f"Entradas analisadas: {analysis['total_entries']}",
        f"Data: {analysis['analyzed_at']}",
        "",
    ]

    corrections = analysis.get("corrections", [])
    lines.append(f"Correcoes detectadas: {len(corrections)}")
    for c in corrections[:5]:
        lines.append(f"  - {c}")

    tool_seqs = analysis.get("tool_sequences", [])
    lines.append(f"\nSequencias frequentes: {len(tool_seqs)}")
    for s in tool_seqs[:5]:
        lines.append(f"  - {' -> '.join(s['sequence'])} ({s['count']}x)")

    errors = analysis.get("recurring_errors", [])
    lines.append(f"\nErros recorrentes: {len(errors)}")
    for e in errors[:5]:
        lines.append(f"  - {e['error_type']} ({e['count']}x)")

    skills = analysis.get("skill_usage", [])
    lines.append(f"\nSkills mais usados: {len(skills)}")
    for s in skills[:5]:
        lines.append(f"  - /{s['name']} ({s['count']}x)")

    return "\n".join(lines)


# ── Internal Extractors ──────────────────────────────────────

def _load_log_entries(max_lines: int) -> list[dict]:
    """Carrega ultimas N linhas do log como dicts."""
    entries = []
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Pega as ultimas max_lines
        for line in lines[-max_lines:]:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                entries.append(entry)
            except (json.JSONDecodeError, TypeError):
                continue
    except Exception:
        pass
    return entries


def _extract_corrections(entries: list[dict]) -> list[str]:
    """Extrai correcoes do usuario dos logs (auto_memory feedback)."""
    corrections = []
    correction_patterns = [
        r"(?:nao|n[aã]o)\s+(?:fa[cç]a|faz)\s+(.+)",
        r"(?:pare|para)\s+de\s+(.+)",
        r"(?:nunca|jamais)\s+(.+)",
        r"(?:prefiro|prefer[eo])\s+(.+)",
        r"(?:errado|incorreto)[\s:]+(.+)",
    ]

    for entry in entries:
        action = entry.get("action", "")
        message = entry.get("message", "")

        # Logs de auto_memory/feedback
        if action in ("checkpoint_save", "auto_correct"):
            continue

        if "correcao" in message.lower() or "feedback" in action.lower():
            # Extrai a correcao do message
            for pat in correction_patterns:
                match = re.search(pat, message, re.IGNORECASE)
                if match:
                    corrections.append(match.group(0).strip())
                    break
            else:
                if len(message) > 10 and len(message) < 200:
                    corrections.append(message)

    # Deduplica
    seen = set()
    unique = []
    for c in corrections:
        key = c.lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(c)

    return unique


def _extract_tool_sequences(entries: list[dict]) -> list[dict[str, Any]]:
    """Identifica sequencias de tools mais frequentes (bigrams e trigrams)."""
    tool_calls = []
    for entry in entries:
        action = entry.get("action", "")
        if action == "tool_exec":
            tool_name = entry.get("tool_name", "")
            if tool_name:
                tool_calls.append(tool_name)

    if len(tool_calls) < 3:
        return []

    # Bigrams
    bigrams = Counter()
    for i in range(len(tool_calls) - 1):
        pair = (tool_calls[i], tool_calls[i + 1])
        bigrams[pair] += 1

    # Trigrams
    trigrams = Counter()
    for i in range(len(tool_calls) - 2):
        triple = (tool_calls[i], tool_calls[i + 1], tool_calls[i + 2])
        trigrams[triple] += 1

    sequences = []

    # Top trigrams (min 3 ocorrencias)
    for seq, count in trigrams.most_common(10):
        if count >= 3:
            sequences.append({"sequence": list(seq), "count": count, "type": "trigram"})

    # Top bigrams (min 5 ocorrencias)
    for seq, count in bigrams.most_common(10):
        if count >= 5:
            sequences.append({"sequence": list(seq), "count": count, "type": "bigram"})

    # Ordena por count
    sequences.sort(key=lambda x: -x["count"])
    return sequences[:15]


def _extract_recurring_errors(entries: list[dict]) -> list[dict[str, Any]]:
    """Detecta erros recorrentes e gera sugestoes preventivas."""
    error_counter: Counter = Counter()
    error_samples: dict[str, str] = {}

    for entry in entries:
        level = entry.get("level", "")
        message = entry.get("message", "")
        action = entry.get("action", "")

        if level in ("error", "warning") or action in ("turn_error", "on_error"):
            # Classifica o tipo de erro
            error_type = _classify_error(message)
            if error_type:
                error_counter[error_type] += 1
                if error_type not in error_samples:
                    error_samples[error_type] = message[:200]

    # Gera sugestoes para erros recorrentes (min 2 ocorrencias)
    suggestions = {
        "rate_limit": "Adicione delay entre chamadas ou use retry com backoff exponencial",
        "file_not_found": "Verifique o path com glob antes de ler/editar",
        "permission_denied": "Verifique permissoes do arquivo antes de modificar",
        "syntax_error": "Valide a sintaxe antes de executar (python -m py_compile)",
        "import_error": "Verifique se a dependencia esta instalada (pip list | grep)",
        "timeout": "Aumente o timeout ou quebre a operacao em partes menores",
        "connection_error": "Verifique conectividade antes de chamadas de rede",
        "json_decode": "Valide o JSON antes de parsear (try/except com fallback)",
        "type_error": "Verifique tipos dos argumentos antes de chamar funcoes",
        "key_error": "Use .get() com default ao acessar dicts",
        "generic": "Revise o contexto do erro e adicione tratamento especifico",
    }

    result = []
    for error_type, count in error_counter.most_common(15):
        if count >= 2:
            result.append({
                "error_type": error_type,
                "count": count,
                "sample": error_samples.get(error_type, ""),
                "suggestion": suggestions.get(error_type, suggestions["generic"]),
            })

    return result


def _classify_error(message: str) -> str:
    """Classifica uma mensagem de erro em tipo."""
    msg = message.lower()

    patterns = [
        ("rate_limit", ["rate limit", "429", "too many requests"]),
        ("file_not_found", ["filenotfounderror", "no such file", "file not found"]),
        ("permission_denied", ["permission denied", "permissionerror", "access denied"]),
        ("syntax_error", ["syntaxerror", "syntax error"]),
        ("import_error", ["importerror", "modulenotfounderror", "no module named"]),
        ("timeout", ["timeout", "timed out", "deadline exceeded"]),
        ("connection_error", ["connectionerror", "connection refused", "network unreachable"]),
        ("json_decode", ["jsondecodeerror", "json.decoder", "expecting value"]),
        ("type_error", ["typeerror", "type error"]),
        ("key_error", ["keyerror"]),
    ]

    for error_type, keywords in patterns:
        if any(kw in msg for kw in keywords):
            return error_type

    # Generico se tem "error" na mensagem
    if "error" in msg or "exception" in msg:
        return "generic"

    return ""


def _extract_skill_usage(entries: list[dict]) -> list[dict[str, Any]]:
    """Conta uso de skills nos logs."""
    skill_counter: Counter = Counter()

    for entry in entries:
        message = entry.get("message", "")
        action = entry.get("action", "")

        # Detecta skills nos logs de turno
        if action == "turn_start":
            # Mensagens que comecam com /
            if isinstance(message, str) and message.startswith("/"):
                skill_name = message.split()[0].lstrip("/")
                if skill_name:
                    skill_counter[skill_name] += 1

    return [
        {"name": name, "count": count}
        for name, count in skill_counter.most_common(20)
    ]
