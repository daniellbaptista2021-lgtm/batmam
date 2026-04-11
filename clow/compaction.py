"""Compaction System \u2014 3-Tier Memory Management (Claude Code Architecture).

Tier 1: MicroCompact \u2014 surgical tool result clearing (per-turn)
Tier 2: Session Memory \u2014 pre-built summary replacement (no LLM call)
Tier 3: Full Compact \u2014 LLM-powered conversation summarization

Designed to maintain the illusion of infinite context.
"""

import json
import time
import re
import logging
from typing import Any
from . import config
from .logging import log_action

logger = logging.getLogger("clow.compaction")

# \u2550\u2550 Configuration \u2550\u2550

COMPACTABLE_TOOLS = {
    "read", "bash", "grep", "glob", "web_search", "web_fetch",
    "write", "edit", "ssh_connect",
}

MICROCOMPACT_KEEP_LAST = 3        # Keep last N tool results full
MICROCOMPACT_TRUNCATE_TO = 500    # Chars for old tool results

SESSION_COMPACT_MIN_TOKENS = 10_000   # Keep at least this many tokens
SESSION_COMPACT_MIN_TEXT_MSGS = 5     # Keep at least N text messages
SESSION_COMPACT_MAX_TOKENS = 40_000   # Hard cap

AUTOCOMPACT_BUFFER_TOKENS = 13_000    # Buffer below context window
AUTOCOMPACT_THRESHOLD_CHARS = 320_000 # ~80K tokens
MAX_CONSECUTIVE_FAILURES = 3

# Post-compact restoration limits
POST_COMPACT_MAX_FILES = 5
POST_COMPACT_TOKEN_BUDGET = 50_000
POST_COMPACT_MAX_PER_FILE = 5_000

# Compaction summary prompt (9 sections)
COMPACT_SUMMARY_PROMPT = """Resuma a conversa abaixo de forma estruturada.
Mantenha TODAS as informacoes tecnicas relevantes.

Estruture o resumo em 9 secoes:

1. PEDIDO PRINCIPAL - O que o usuario quer alcancar
2. CONCEITOS TECNICOS - Tecnologias, padroes, arquitetura mencionados
3. ARQUIVOS E CODIGO - Arquivos modificados/lidos com trechos importantes
4. ERROS E CORRECOES - Bugs encontrados e como foram corrigidos
5. RESOLUCAO DE PROBLEMAS - Tentativas e abordagens usadas
6. MENSAGENS DO USUARIO - Todas as instrucoes do usuario (critico)
7. TAREFAS PENDENTES - O que ainda falta fazer
8. TRABALHO ATUAL - O que estava sendo feito antes da compactacao
9. PROXIMO PASSO - O que fazer em seguida (cite literalmente)

<analysis>
[Use este espaco para organizar seus pensamentos antes de resumir]
</analysis>

<summary>
[Coloque o resumo final aqui \u2014 apenas isto sera preservado]
</summary>"""


# \u2550\u2550 Tier 1: MicroCompact \u2550\u2550

def microcompact(messages: list[dict], keep_last: int = MICROCOMPACT_KEEP_LAST) -> list[dict]:
    """Tier 1: Clear old tool results, keep last N full.

    Surgical token reclamation without touching conversation structure.
    Only targets high-volume, reproducible tool results.
    """
    # Find tool result indices
    tool_indices = []
    for i, msg in enumerate(messages):
        if msg.get("role") == "tool":
            # Check if it is a compactable tool
            tool_name = ""
            # Look back for the tool_use that triggered this
            for j in range(i - 1, max(0, i - 5), -1):
                prev = messages[j]
                if prev.get("role") == "assistant" and prev.get("tool_calls"):
                    for tc in prev["tool_calls"]:
                        tc_id = tc.get("id", "")
                        if tc_id == msg.get("tool_call_id", ""):
                            fn = tc.get("function", {})
                            tool_name = fn.get("name", tc.get("name", ""))
                            break

            if tool_name in COMPACTABLE_TOOLS or not tool_name:
                tool_indices.append(i)

    if len(tool_indices) <= keep_last:
        return messages

    # Clear old tool results (keep last N full)
    old_indices = set(tool_indices[:-keep_last])
    result = []
    cleared = 0
    for i, msg in enumerate(messages):
        if i in old_indices:
            msg = dict(msg)
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > MICROCOMPACT_TRUNCATE_TO:
                msg["content"] = content[:MICROCOMPACT_TRUNCATE_TO] + "\n[... resultado truncado]"
                cleared += 1
        result.append(msg)

    if cleared > 0:
        log_action("microcompact", f"cleared {cleared} old tool results")

    return result


# \u2550\u2550 Tier 2: Session Memory Compact \u2550\u2550

def session_memory_compact(
    messages: list[dict],
    session_memory: str = "",
    min_tokens: int = SESSION_COMPACT_MIN_TOKENS,
    min_text_msgs: int = SESSION_COMPACT_MIN_TEXT_MSGS,
    max_tokens: int = SESSION_COMPACT_MAX_TOKENS,
) -> list[dict] | None:
    """Tier 2: Replace old messages with pre-built session memory.

    Uses the session memory (continuously maintained background summary)
    instead of making an expensive LLM call.
    Returns None if session memory is not available or too small.
    """
    if not session_memory or len(session_memory) < 100:
        return None  # Fall through to full compact

    # Find system message
    system_msg = None
    other_msgs = []
    for msg in messages:
        if msg.get("role") == "system" and system_msg is None:
            system_msg = msg
        else:
            other_msgs.append(msg)

    if not other_msgs:
        return None

    # Calculate how many recent messages to keep
    # Walk backwards from end, counting tokens and text messages
    kept_tokens = 0
    kept_text_msgs = 0
    cut_index = len(other_msgs)

    for i in range(len(other_msgs) - 1, -1, -1):
        msg = other_msgs[i]
        content = msg.get("content", "")
        tokens = len(content) // 4 if isinstance(content, str) else 0

        if kept_tokens + tokens > max_tokens:
            break

        kept_tokens += tokens
        cut_index = i

        if msg.get("role") in ("user", "assistant") and isinstance(content, str) and len(content) > 10:
            kept_text_msgs += 1

        # Check minimums met
        if kept_tokens >= min_tokens and kept_text_msgs >= min_text_msgs:
            # We have met minimums, but keep going until max
            pass

    if kept_text_msgs < min_text_msgs:
        return None  # Not enough messages to compact meaningfully

    # Build compacted conversation
    recent_msgs = other_msgs[cut_index:]

    # Preserve API invariants: ensure tool pairs are not split
    recent_msgs = _fix_tool_pairs(recent_msgs, other_msgs[:cut_index])

    # Build result
    result = []
    if system_msg:
        result.append(system_msg)

    # Insert session memory as compact boundary
    result.append({
        "role": "system",
        "content": f"[Resumo do contexto anterior]\n{session_memory}",
    })

    result.extend(recent_msgs)

    old_tokens = sum(len(m.get("content", "")) // 4 for m in messages if isinstance(m.get("content"), str))
    new_tokens = sum(len(m.get("content", "")) // 4 for m in result if isinstance(m.get("content"), str))
    compression = round((1 - new_tokens / max(1, old_tokens)) * 100)

    log_action("session_memory_compact", f"compression={compression}% ({old_tokens} -> {new_tokens} est tokens)")

    return result


def _fix_tool_pairs(kept: list[dict], dropped: list[dict]) -> list[dict]:
    """Ensure every tool_result has its matching tool_use in kept messages."""
    # Find orphaned tool_results
    tool_call_ids_in_kept = set()
    for msg in kept:
        if msg.get("role") == "assistant":
            for tc in msg.get("tool_calls", []):
                tool_call_ids_in_kept.add(tc.get("id", ""))

    orphan_ids = set()
    for msg in kept:
        if msg.get("role") == "tool":
            tc_id = msg.get("tool_call_id", "")
            if tc_id and tc_id not in tool_call_ids_in_kept:
                orphan_ids.add(tc_id)

    if not orphan_ids:
        return kept

    # Pull in matching assistant messages from dropped
    extra = []
    for msg in dropped:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                if tc.get("id") in orphan_ids:
                    extra.append(msg)
                    break

    return extra + kept


# \u2550\u2550 Tier 3: Full Compact \u2550\u2550

def full_compact(
    messages: list[dict],
    llm_client: Any = None,
    model: str = "deepseek-chat",
) -> list[dict] | None:
    """Tier 3: LLM-powered conversation summarization.

    The nuclear option. Sends entire conversation to LLM for structured summary.
    Returns compacted messages or None on failure.
    """
    if llm_client is None:
        try:
            from openai import OpenAI
            llm_client = OpenAI(**config.get_deepseek_client_kwargs())
        except Exception as e:
            logger.error(f"Full compact failed: no LLM client: {e}")
            return None

    # Extract system message
    system_msg = None
    conversation = []
    for msg in messages:
        if msg.get("role") == "system" and system_msg is None:
            system_msg = msg
        else:
            conversation.append(msg)

    if not conversation:
        return None

    # Build summary request
    # Flatten conversation to text (cap at 4000 chars per message)
    text_parts = []
    for msg in conversation[:50]:  # Cap at 50 messages
        role = msg.get("role", "")
        content = msg.get("content", "")
        if isinstance(content, str) and content:
            text_parts.append(f"[{role}] {content[:4000]}")

    conversation_text = "\n".join(text_parts)

    try:
        # Use analysis scratchpad pattern
        response = llm_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": COMPACT_SUMMARY_PROMPT},
                {"role": "user", "content": conversation_text[:60000]},  # Cap total
            ],
            max_tokens=2000,
            temperature=0.1,
        )

        raw_summary = response.choices[0].message.content or ""

        # Strip <analysis> block, keep only <summary>
        summary = _extract_summary(raw_summary)

        if not summary or len(summary) < 50:
            logger.warning("Full compact: summary too short")
            return None

        # Build compacted conversation
        result = []
        if system_msg:
            result.append(system_msg)

        # Compact boundary
        result.append({
            "role": "system",
            "content": f"[Conversa compactada \u2014 resumo do contexto anterior]\n{summary}",
        })

        # Keep last 5 messages for continuity
        recent = conversation[-5:] if len(conversation) > 5 else conversation
        recent = _fix_tool_pairs(recent, conversation[:-5])
        result.extend(recent)

        # Post-compact: restore recently-read files (placeholder)
        # In full implementation, this would re-read recent files

        old_tokens = sum(len(m.get("content", "")) // 4 for m in messages if isinstance(m.get("content"), str))
        new_tokens = sum(len(m.get("content", "")) // 4 for m in result if isinstance(m.get("content"), str))
        compression = round((1 - new_tokens / max(1, old_tokens)) * 100)

        log_action("full_compact", f"compression={compression}% ({old_tokens} -> {new_tokens} est tokens)")

        return result

    except Exception as e:
        logger.error(f"Full compact LLM call failed: {e}")
        return None


def _extract_summary(raw: str) -> str:
    """Extract <summary> content, strip <analysis> scratchpad."""
    # Try to extract <summary> block
    match = re.search(r'<summary>(.*?)</summary>', raw, re.DOTALL)
    if match:
        return match.group(1).strip()

    # If no tags, strip <analysis> and return rest
    cleaned = re.sub(r'<analysis>.*?</analysis>', '', raw, flags=re.DOTALL)
    return cleaned.strip()


# \u2550\u2550 Auto-Compact Trigger \u2550\u2550

_consecutive_failures = 0

def auto_compact_if_needed(
    messages: list[dict],
    session_memory: str = "",
    llm_client: Any = None,
    query_source: str = "chat",
) -> list[dict] | None:
    """Auto-compact trigger with circuit breaker.

    Returns compacted messages or None if no compaction needed.
    """
    global _consecutive_failures

    # Recursion guard: do not compact the compactor
    if query_source in ("compact", "session_memory", "summary"):
        return None

    # Circuit breaker
    if _consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
        return None

    # Check threshold
    total_chars = sum(
        len(m.get("content", "")) if isinstance(m.get("content"), str) else 0
        for m in messages
    )

    if total_chars < AUTOCOMPACT_THRESHOLD_CHARS:
        return None

    log_action("autocompact_triggered", f"context={total_chars} chars (~{total_chars // 4} tokens)")

    # Try Tier 2 first (session memory \u2014 no LLM call)
    if session_memory:
        result = session_memory_compact(messages, session_memory)
        if result:
            _consecutive_failures = 0
            return result

    # Fall through to Tier 3 (full compact \u2014 LLM call)
    result = full_compact(messages, llm_client)
    if result:
        _consecutive_failures = 0
        return result

    # Failure
    _consecutive_failures += 1
    log_action("autocompact_failed", f"consecutive failures: {_consecutive_failures}/{MAX_CONSECUTIVE_FAILURES}", level="warning")
    return None


# \u2550\u2550 Warning State \u2550\u2550

def get_context_warning(messages: list[dict]) -> dict:
    """Calculate context warning state for UI display."""
    total_chars = sum(
        len(m.get("content", "")) if isinstance(m.get("content"), str) else 0
        for m in messages
    )
    total_tokens = total_chars // 4

    # DeepSeek context: 128K tokens
    context_window = 128_000
    effective = context_window - 20_000  # Reserved for output

    percent_used = round(total_tokens / effective * 100)
    percent_left = 100 - percent_used

    return {
        "tokens_estimated": total_tokens,
        "context_window": context_window,
        "effective_window": effective,
        "percent_used": percent_used,
        "percent_left": percent_left,
        "warning": percent_left < 20,
        "error": percent_left < 10,
        "blocking": percent_left < 3,
        "autocompact_threshold": percent_left < 12,
    }


# \u2550\u2550 Message Grouping \u2550\u2550

def group_by_api_round(messages: list[dict]) -> list[list[dict]]:
    """Group messages by API round (assistant message boundaries).

    Each group contains one assistant response and its tool results.
    Critical for PTL retry truncation.
    """
    groups = []
    current_group = []
    last_assistant_id = None

    for msg in messages:
        if msg.get("role") == "system" and not current_group:
            current_group.append(msg)
            continue

        if msg.get("role") == "assistant":
            msg_id = id(msg)  # Use object id as proxy for message.id
            if msg_id != last_assistant_id and current_group:
                groups.append(current_group)
                current_group = []
            last_assistant_id = msg_id

        current_group.append(msg)

    if current_group:
        groups.append(current_group)

    return groups
