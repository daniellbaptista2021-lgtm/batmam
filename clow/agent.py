"""Agent Loop — o coracao do Clow v0.2.0.

Orquestra o ciclo: prompt -> modelo -> tool calls -> execucao -> resultado -> modelo...
Suporta streaming, sub-agents, execucao paralela, background agents,
plan mode, context inteligente e auto-memory.
"""

from __future__ import annotations
import base64
import json
import os
import sys
import re
import time
import threading
import uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Any, Callable

from .models import Session, ToolCall, ToolResult, ToolResultStatus, Turn
from .tools.base import ToolRegistry, create_default_registry
from .permissions import needs_confirmation, format_confirmation_prompt
from .prompts import get_system_prompt
from .session import save_session
from .memory import load_memory_context, save_memory
from .context import load_project_context
from .hooks import HookRunner
from .mcp import MCPManager
from .plugins import PluginManager
from .logging import log_action
from .checkpoints import save_checkpoint, extract_target_files, is_write_tool_call
from .learner import load_learned_context
from .orchestrator import (
    orchestrate, MASTER_SYSTEM_PROMPT, FallbackTracker, should_compress,
)
from . import config

# Tools que sao read-only e podem rodar em paralelo
READ_ONLY_TOOLS = {"read", "glob", "grep", "web_search", "web_fetch", "task_list", "task_get"}

# Padroes para auto-memory
CORRECTION_PATTERNS = [
    r"(?:nao|n\u00e3o)\s+(?:fa\u00e7a|faz|faca)\s+(?:isso|isto)",
    r"(?:pare|para)\s+de\s+",
    r"(?:nunca|jamais)\s+",
    r"(?:nao|n\u00e3o)\s+(?:quero|preciso|gosto)",
    r"(?:errado|incorreto|wrong)",
    r"(?:nao|n\u00e3o)\s+(?:\u00e9|era)\s+(?:isso|isto|assim)",
    r"(?:prefiro|prefer[eo])\s+",
]

CONFIRMATION_PATTERNS = [
    r"(?:isso\s+mesmo|exatamente|perfeito|\u00f3timo|otimo)",
    r"(?:muito\s+bem|excelente|correto|certo)",
    r"(?:\u00e9\s+isso|era\s+isso|isso\s+a\u00ed|isso\s+ai)",
    r"(?:continue\s+assim|keep\s+doing)",
    r"(?:gostei|adorei|loved|great|perfect)",
]


def sanitize_messages(msgs: list[dict], session_id: str = "") -> list[dict]:
    """Sanitiza historico de mensagens para compatibilidade com DeepSeek API.

    Garante que NUNCA exista:
    - role='tool' sem um role='assistant' com tool_calls correspondente ANTES
    - role='assistant' com tool_calls sem TODOS os tool results correspondentes DEPOIS

    Opera em 2 passadas:
    1. Forward pass: rastreia tool_call IDs pendentes, descarta tool results orfaos
    2. Backward pass: remove/limpa assistant com tool_calls cujos results sumiram

    Retorna lista limpa. Nunca modifica a lista original.
    """
    if not msgs:
        return []

    # ── Passada 1 (forward): valida cada mensagem na ordem ──
    # Rastreia quais tool_call IDs foram emitidos e ainda nao respondidos
    result: list[dict] = []
    pending_tc_ids: set[str] = set()  # IDs de tool_calls aguardando results
    removed_count = 0

    for msg in msgs:
        role = msg.get("role", "")

        if role == "assistant":
            result.append(msg)
            # Registra tool_call IDs deste assistant
            for tc in msg.get("tool_calls", []):
                tc_id = tc.get("id", "")
                if tc_id:
                    pending_tc_ids.add(tc_id)

        elif role == "tool":
            tc_id = msg.get("tool_call_id", "")
            if tc_id in pending_tc_ids:
                # Valido: tem par
                result.append(msg)
                pending_tc_ids.discard(tc_id)
            else:
                # Orfao: sem assistant com esse tool_call_id antes
                removed_count += 1

        else:
            # system, user — passa direto
            result.append(msg)

    # ── Passada 2 (backward): limpa assistants com tool_calls sem results ──
    # Qualquer assistant com tool_calls cujos IDs nunca receberam results
    # precisa ser limpo (remove tool_calls, mantem texto)
    if pending_tc_ids:
        cleaned: list[dict] = []
        for msg in result:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                msg_tc_ids = {tc.get("id", "") for tc in msg["tool_calls"]}
                orphan_ids = msg_tc_ids & pending_tc_ids
                if orphan_ids:
                    surviving = [tc for tc in msg["tool_calls"]
                                 if tc.get("id", "") not in orphan_ids]
                    if surviving:
                        # Mantem assistant com tool_calls que TEM results
                        new_msg = {"role": "assistant", "tool_calls": surviving}
                        if msg.get("content"):
                            new_msg["content"] = msg["content"]
                        cleaned.append(new_msg)
                    elif msg.get("content"):
                        # Sem tool_calls sobreviventes mas tem texto
                        cleaned.append({"role": "assistant", "content": msg["content"]})
                    else:
                        # Assistant vazio (so tinha tool_calls orfaos) — remove
                        removed_count += 1
                    # Remove tool results orfaos que sobraram
                    continue
                else:
                    cleaned.append(msg)
            elif msg.get("role") == "tool":
                tc_id = msg.get("tool_call_id", "")
                if tc_id in pending_tc_ids:
                    removed_count += 1
                    continue
                cleaned.append(msg)
            else:
                cleaned.append(msg)
        result = cleaned

    # ── Passada 3: validacao final — garante ordem estrita ──
    # Cada tool result DEVE ter assistant com tool_calls imediatamente antes
    # (possivelmente com outros tool results do mesmo bloco entre eles)
    final: list[dict] = []
    # Set de tool_call IDs do assistant mais recente que ainda aceita results
    active_tc_ids: set[str] = set()

    for msg in result:
        role = msg.get("role", "")

        if role == "tool":
            tc_id = msg.get("tool_call_id", "")
            if tc_id in active_tc_ids:
                final.append(msg)
                active_tc_ids.discard(tc_id)
            else:
                # Tool result fora de posicao — descarta
                removed_count += 1
        elif role == "assistant":
            # Novo assistant: fecha qualquer bloco anterior de tool_calls pendentes
            if active_tc_ids:
                # Tinha tool_calls sem results — limpa o assistant anterior
                for k in range(len(final) - 1, -1, -1):
                    prev = final[k]
                    if prev.get("role") == "assistant" and prev.get("tool_calls"):
                        prev_ids = {tc.get("id", "") for tc in prev["tool_calls"]}
                        if prev_ids & active_tc_ids:
                            surviving = [tc for tc in prev["tool_calls"]
                                         if tc.get("id", "") not in active_tc_ids]
                            if surviving:
                                final[k] = {"role": "assistant", "tool_calls": surviving}
                                if prev.get("content"):
                                    final[k]["content"] = prev["content"]
                            elif prev.get("content"):
                                final[k] = {"role": "assistant", "content": prev["content"]}
                            else:
                                final.pop(k)
                            break
                active_tc_ids.clear()

            final.append(msg)
            for tc in msg.get("tool_calls", []):
                tc_id = tc.get("id", "")
                if tc_id:
                    active_tc_ids.add(tc_id)
        else:
            # user/system fecha bloco de tool_calls pendentes
            if active_tc_ids:
                for k in range(len(final) - 1, -1, -1):
                    prev = final[k]
                    if prev.get("role") == "assistant" and prev.get("tool_calls"):
                        prev_ids = {tc.get("id", "") for tc in prev["tool_calls"]}
                        if prev_ids & active_tc_ids:
                            surviving = [tc for tc in prev["tool_calls"]
                                         if tc.get("id", "") not in active_tc_ids]
                            if surviving:
                                final[k] = {"role": "assistant", "tool_calls": surviving}
                                if prev.get("content"):
                                    final[k]["content"] = prev["content"]
                            elif prev.get("content"):
                                final[k] = {"role": "assistant", "content": prev["content"]}
                            else:
                                final.pop(k)
                            break
                active_tc_ids.clear()
            final.append(msg)

    # Limpa pendentes no final
    if active_tc_ids:
        for k in range(len(final) - 1, -1, -1):
            prev = final[k]
            if prev.get("role") == "assistant" and prev.get("tool_calls"):
                prev_ids = {tc.get("id", "") for tc in prev["tool_calls"]}
                if prev_ids & active_tc_ids:
                    surviving = [tc for tc in prev["tool_calls"]
                                 if tc.get("id", "") not in active_tc_ids]
                    if surviving:
                        final[k] = {"role": "assistant", "tool_calls": surviving}
                        if prev.get("content"):
                            final[k]["content"] = prev["content"]
                    elif prev.get("content"):
                        final[k] = {"role": "assistant", "content": prev["content"]}
                    else:
                        final.pop(k)
                    break

    if removed_count > 0:
        log_action(
            "sanitize_messages",
            f"removidas {removed_count} mensagens orfas do historico",
            level="warning",
            session_id=session_id,
        )

    return final


def _slice_at_safe_boundary(msgs: list[dict], keep_last_n: int) -> list[dict]:
    """Corta historico mantendo os ultimos N msgs, mas ajustando o ponto
    de corte para nunca partir um bloco assistant(tool_calls)+tool(results).

    Retorna: [system] + mensagens recentes com corte seguro.
    """
    if len(msgs) <= keep_last_n + 1:
        return list(msgs)

    system = msgs[0] if msgs and msgs[0].get("role") == "system" else None
    start_from = len(msgs) - keep_last_n

    # Avanca o ponto de corte para frente ate encontrar um limite seguro:
    # Nao pode comecar com role='tool' (orfao)
    # Nao pode comecar logo apos um assistant com tool_calls (cortaria os results)
    while start_from < len(msgs):
        msg = msgs[start_from]
        if msg.get("role") == "tool":
            # Orfao — pula
            start_from += 1
            continue
        # Verifica se a mensagem anterior era assistant com tool_calls
        # cujos results estao apos o ponto de corte
        if start_from > 0:
            prev = msgs[start_from - 1]
            if (prev.get("role") == "assistant" and prev.get("tool_calls")
                    and msg.get("role") == "tool"):
                start_from += 1
                continue
        break

    recent = msgs[start_from:]
    if system:
        return [system] + recent
    return recent


def _repair_tool_json(raw: str) -> dict | None:
    """Tenta reparar JSON malformado de tool calls do DeepSeek.

    Problemas comuns:
    1. String truncada: {"command": "echo hello  (falta fechar)
    2. Aspas internas nao escapadas: {"command": "echo "hello""}
    3. Trailing comma: {"command": "ls",}
    """
    s = raw.strip()

    # Remove trailing commas antes de }
    s = re.sub(r',\s*}', '}', s)
    s = re.sub(r',\s*$', '', s)

    # Tenta fechar JSON truncado
    if not s.endswith('}'):
        # Conta chaves abertas
        depth = 0
        in_string = False
        escape = False
        for ch in s:
            if escape:
                escape = False
                continue
            if ch == '\\':
                escape = True
                continue
            if ch == '"' and not escape:
                in_string = not in_string
                continue
            if not in_string:
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1

        # Fecha string aberta + chaves
        if in_string:
            s += '"'
        for _ in range(depth):
            s += '}'

    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        pass

    # Ultimo recurso: regex para extrair pares key:value
    pairs = re.findall(r'"(\w+)"\s*:\s*"((?:[^"\\]|\\.)*)(?:")?', raw)
    if pairs:
        return {k: v.replace('\\"', '"') for k, v in pairs}

    return None


class Agent:
    """Agente principal do Clow v0.2.0."""

    def __init__(
        self,
        cwd: str | None = None,
        session: Session | None = None,
        model: str | None = None,
        api_key: str | None = None,
        on_text_delta: Callable[[str], None] | None = None,
        on_text_done: Callable[[str], None] | None = None,
        on_tool_call: Callable[[str, dict], None] | None = None,
        on_tool_result: Callable[[str, str, str], None] | None = None,
        ask_confirmation: Callable[[str], bool] | None = None,
        on_rate_limit: Callable[[int, int, int], None] | None = None,
        auto_approve: bool = False,
        is_subagent: bool = False,
    ):
        self.cwd = cwd or os.getcwd()
        self.model = model or config.CLOW_MODEL
        self.registry: ToolRegistry = create_default_registry()

        # Configura agent_tool com referencia ao agente pai
        agent_tool = self.registry.get("agent")
        if agent_tool:
            agent_tool._parent_agent = self

        self.on_text_delta = on_text_delta or (lambda t: None)
        self.on_text_done = on_text_done or (lambda t: None)
        self.on_tool_call = on_tool_call or (lambda n, a: None)
        self.on_tool_result = on_tool_result or (lambda n, s, o: None)
        self.ask_confirmation = ask_confirmation or (lambda m: True)
        self.on_rate_limit = on_rate_limit or (lambda w, a, m: time.sleep(w))
        self.auto_approve = auto_approve
        self.is_subagent = is_subagent

        # Client — DeepSeek via OpenAI SDK
        if not config.DEEPSEEK_API_KEY:
            raise RuntimeError("DEEPSEEK_API_KEY nao configurada.")
        from openai import OpenAI
        self._client = OpenAI(**config.get_deepseek_client_kwargs())

        # Orchestrator: fallback tracker
        self._fallback = FallbackTracker()

        # Plan mode — bloqueia ferramentas de escrita quando ativo
        self.plan_mode = False

        # Background agents — resultados e lock para thread safety
        self._background_results: dict[str, dict] = {}
        self._background_lock = threading.Lock()

        # Thread pool para execucao paralela de read-only tools
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="clow-tool")

        # Hooks
        self.hooks = HookRunner()

        # MCP — carrega servidores e registra tools
        self.mcp = MCPManager()
        if not is_subagent:
            self.mcp.load_from_settings()
            self.mcp.register_tools(self.registry)

        # Plugins — carrega e registra tools/hooks
        self.plugins = PluginManager()
        if not is_subagent:
            self.plugins.load_all(self.registry, self.hooks)

        # Hook on_start
        if not is_subagent:
            self.hooks.run_hooks("on_start", {"cwd": self.cwd}, self.cwd)

        # Sessao
        self.session = session or Session(cwd=self.cwd, model=self.model)
        if not self.session.messages:
            self._build_system_messages()

    # ── System Messages ────────────────────────────────────────

    def _build_system_messages(self) -> None:
        """System prompt com prompt mestre do orquestrador + contexto dinamico."""
        business_prompt = get_system_prompt(self.cwd)
        self._system_base = f"{MASTER_SYSTEM_PROMPT}\n\n{business_prompt}"

        # Contexto dinamico
        dynamic_parts = []

        # CLOW.md do projeto
        project_ctx = load_project_context(self.cwd)
        if project_ctx:
            dynamic_parts.append(f"\n# Contexto do Projeto (CLOW.md)\n{project_ctx}")

        # Project DNA: INSTRUCTIONS.md com heranca de diretorios pai
        instructions = self._load_project_instructions()
        if instructions:
            dynamic_parts.append(f"\n# [Instrucoes do Projeto]\n{instructions}")

        # Memoria persistente
        if not self.is_subagent:
            memory_ctx = load_memory_context()
            if memory_ctx:
                dynamic_parts.append(f"\n# Memoria\n{memory_ctx}")

        self._system_dynamic = "\n".join(dynamic_parts) if dynamic_parts else ""

        full_system = self._system_base
        if self._system_dynamic:
            full_system += "\n\n" + self._system_dynamic
        self.session.messages = [
            {"role": "system", "content": full_system}
        ]

    def _load_project_instructions(self) -> str:
        """Carrega .clow/INSTRUCTIONS.md do cwd e diretorios pai (heranca).

        Busca de baixo pra cima ate a raiz. Combina todos encontrados,
        com o mais proximo (cwd) tendo maior prioridade (aparece por ultimo).
        """
        instructions_parts: list[str] = []
        current = Path(self.cwd).resolve()

        # Sobe ate a raiz coletando INSTRUCTIONS.md
        visited: set[str] = set()
        while True:
            dir_str = str(current)
            if dir_str in visited:
                break
            visited.add(dir_str)

            instructions_file = current / ".clow" / "INSTRUCTIONS.md"
            if instructions_file.exists():
                try:
                    content = instructions_file.read_text(encoding="utf-8").strip()
                    if content:
                        instructions_parts.append(content)
                except Exception:
                    pass

            parent = current.parent
            if parent == current:
                break  # Chegou na raiz
            current = parent

        if not instructions_parts:
            return ""

        # Inverte: raiz primeiro, cwd por ultimo (override natural)
        instructions_parts.reverse()
        combined = "\n\n---\n\n".join(instructions_parts)
        log_action(
            "project_dna",
            f"carregado {len(instructions_parts)} INSTRUCTIONS.md",
            session_id=self.session.id,
        )
        return combined

    # ── Main Turn Loop ─────────────────────────────────────────

    def run_turn(self, user_message) -> str:
        """Executa um turno completo com streaming.

        user_message pode ser str (texto) ou list (content blocks multimodais).
        """

        # Hook pre_turn
        msg_text = user_message if isinstance(user_message, str) else "[multimodal message]"
        pre_results = self.hooks.run_hooks(
            "pre_turn", {"user_message": msg_text}, self.cwd
        )
        for hr in pre_results:
            if hr.blocked:
                return f"[Hook bloqueou execucao] {hr.feedback}"

        # Orquestrador: roteamento inteligente de modelo, agente e tools
        self._orchestration = None
        self._original_model = None
        if not self.is_subagent and isinstance(user_message, str):
            self._orchestration = orchestrate(
                user_message,
                context_messages=self.session.messages,
                has_error_context=self._has_recent_errors(),
                session_id=self.session.id,
            )
            chosen_model = self._orchestration["model"]
            if chosen_model != self.model:
                self._original_model = self.model
                self.model = chosen_model

            # Comprime contexto se necessario (>80K tokens)
            if self._orchestration["needs_compression"]:
                self._maybe_compact()

            # Contexto do agente especializado: embute no system prompt (nao como msg separada)
            agent_ctx = self._orchestration.get("agent_context", "")
            if agent_ctx and self.session.messages and self.session.messages[0].get("role") == "system":
                sys_content = self.session.messages[0].get("content", "")
                if agent_ctx not in sys_content:
                    self.session.messages[0] = {
                        "role": "system",
                        "content": sys_content + agent_ctx,
                    }

        self.session.messages.append({"role": "user", "content": user_message})
        log_action("turn_start", msg_text[:80], session_id=self.session.id)

        # Auto-memory: detecta correcoes e confirmacoes
        if not self.is_subagent and isinstance(user_message, str):
            self._check_auto_memory(user_message)

        turn = Turn(user_message=user_message)
        full_response_text = []
        max_iterations = 8
        iteration = 0
        auto_correct_attempts = 0
        cache_hit_total = 0
        cache_miss_total = 0
        prev_tool_calls: list[dict] | None = None

        _last_tool_calls: list[str] = []  # Loop detection
        try:
            while iteration < max_iterations:
                iteration += 1

                # ── Roteamento hibrido por etapa ──
                # Reasoner: planejamento (iter 1), debug (apos erro), verificacao final
                # Chat: execucao de tools (read, write, bash, glob — rapido e barato)
                self._select_model_for_iteration(
                    iteration, auto_correct_attempts, prev_tool_calls
                )

                # Chama modelo com streaming
                text_content, tool_calls_data, usage = self._stream_call()
                prev_tool_calls = tool_calls_data  # tracking para roteamento hibrido

                turn.tokens_in += usage.get("prompt_tokens", 0)
                turn.tokens_out += usage.get("completion_tokens", 0)
                cache_hit_total += usage.get("cache_hit_tokens", 0)
                cache_miss_total += usage.get("cache_miss_tokens", 0)

                # Budget check: if this turn consumed too many tokens, stop
                if turn.tokens_in + turn.tokens_out > 50000:
                    log_action("budget_exceeded", f"Turn tokens: {turn.tokens_in + turn.tokens_out}", session_id=self.session.id)
                    if text_content:
                        full_response_text.append(text_content)
                    break

                if text_content:
                    full_response_text.append(text_content)
                    self.on_text_done(text_content)

                # Monta mensagem do assistente para historico
                assistant_msg = self._build_assistant_message(text_content, tool_calls_data)
                self.session.messages.append(assistant_msg)

                # Se nao tem tool calls, verifica se precisa fallback
                if not tool_calls_data:
                    # Fallback: se resposta insuficiente com chat, tenta reasoner
                    if (
                        self._orchestration
                        and self.model != config.DEEPSEEK_REASONER_MODEL
                        and self._fallback.should_fallback(
                            text_content,
                            self.model,
                            had_tool_errors=auto_correct_attempts > 0,
                            was_conversational=self._orchestration.get("is_conversational", False),
                        )
                    ):
                        self._fallback.log_fallback(
                            "insufficient-response", self.model, self.session.id
                        )
                        self.model = config.DEEPSEEK_REASONER_MODEL
                        # Remove resposta insuficiente e tenta de novo
                        self.session.messages.pop()  # remove assistant msg
                        log_action(
                            "fallback_retry",
                            f"promovendo para {self.model}",
                            session_id=self.session.id,
                        )
                        full_response_text.pop() if full_response_text else None
                        continue
                    break

                # ── Time Travel: checkpoint antes de tools de escrita ──
                if config.CLOW_CHECKPOINTS and not self.is_subagent:
                    has_write = any(
                        is_write_tool_call(
                            tc["name"],
                            json.loads(tc["arguments"]) if isinstance(tc["arguments"], str) else tc["arguments"],
                        )
                        for tc in tool_calls_data
                    )
                    if has_write:
                        target_files = extract_target_files(tool_calls_data)
                        if target_files:
                            save_checkpoint(
                                self.session.id, iteration, target_files,
                                summary=msg_text[:80] if isinstance(user_message, str) else "",
                            )

                # Loop detection: same tool + same args = stop
                tool_signatures = []
                for tc in tool_calls_data:
                    sig = f"{tc['name']}:{tc.get('arguments', '')[:100]}"
                    tool_signatures.append(sig)

                repeated = [s for s in tool_signatures if s in _last_tool_calls]
                if repeated:
                    log_action("loop_detected", f"Repeated tool call: {repeated[0][:60]}", level="warning", session_id=self.session.id)
                    # Force final response instead of looping
                    self.session.messages.append({
                        "role": "user",
                        "content": "[Sistema] Ferramenta repetida detectada. Pare e de a resposta final ao usuario.",
                    })
                    break
                _last_tool_calls = tool_signatures

                # Executa tool calls (com paralelismo para read-only)
                tool_results = self._execute_tool_calls(tool_calls_data, turn)

                # Adiciona resultados ao historico
                for tr in tool_results:
                    self.session.messages.append(tr.to_message())

                # ── Auto-correction: detecta erros e injeta correcao ──
                if config.CLOW_AUTO_CORRECT and auto_correct_attempts < config.CLOW_AUTO_CORRECT_MAX:
                    has_error = self._detect_tool_errors(tool_results)
                    if has_error:
                        auto_correct_attempts += 1
                        auto_msg = (
                            "O comando anterior falhou. Analise o erro e "
                            "corrija automaticamente."
                        )
                        self.session.messages.append({
                            "role": "user",
                            "content": auto_msg,
                        })
                        log_action(
                            "auto_correct",
                            f"tentativa {auto_correct_attempts}/{config.CLOW_AUTO_CORRECT_MAX}",
                            session_id=self.session.id,
                        )
                        continue  # Volta pro while sem esperar input

        except Exception as e:
            # Hook on_error
            self.hooks.run_hooks("on_error", {"error": str(e)}, self.cwd)
            log_action("turn_error", str(e), level="error", session_id=self.session.id)
            raise

        # ── Forca resposta final se houve tool calls sem texto conclusivo ──
        had_tool_calls = any(
            msg.get("role") == "assistant" and msg.get("tool_calls")
            for msg in self.session.messages
        )
        last_text = full_response_text[-1].strip() if full_response_text else ""
        # Se houve tools mas a ultima resposta e vazia/curta, forca sintese
        if had_tool_calls and len(last_text) < 30 and iteration < max_iterations:
            try:
                self.session.messages.append({
                    "role": "user",
                    "content": "[Sistema] As ferramentas terminaram. Faca um resumo claro do que foi feito, resultados obtidos e proximos passos para o usuario.",
                })
                # Usa chat model para sintese (rapido e barato)
                saved_model = self.model
                self.model = config.CLOW_MODEL
                synth_text, synth_tools, synth_usage = self._stream_call()
                self.model = saved_model
                if synth_text:
                    full_response_text.append(synth_text)
                    self.on_text_done(synth_text)
                    synth_msg = self._build_assistant_message(synth_text, synth_tools)
                    self.session.messages.append(synth_msg)
                    turn.tokens_in += synth_usage.get("prompt_tokens", 0)
                    turn.tokens_out += synth_usage.get("completion_tokens", 0)
                log_action("forced_synthesis", "gerou resposta final apos tools", session_id=self.session.id)
            except Exception as e:
                log_action("forced_synthesis_error", str(e)[:100], level="warning", session_id=self.session.id)

        # Finaliza turno
        turn.assistant_message = "\n".join(full_response_text)
        self.session.add_tokens(turn.tokens_in, turn.tokens_out)
        cache_info = ""
        if cache_hit_total:
            cache_info = f" cache_hit={cache_hit_total} cache_miss={cache_miss_total}"
        log_action(
            "turn_done",
            f"tokens_in={turn.tokens_in} tokens_out={turn.tokens_out}{cache_info}",
            session_id=self.session.id,
            tokens=turn.tokens_in + turn.tokens_out,
        )
        self.session.turns.append(turn)

        # Hook post_turn
        self.hooks.run_hooks(
            "post_turn",
            {"user_message": user_message, "assistant_message": turn.assistant_message},
            self.cwd,
        )

        # Auto-save (nao salva sub-agents)
        if not self.is_subagent:
            save_session(self.session)
            self._maybe_compact()

        # Notifica background agents completados
        self._check_background_notifications()

        # Restaura modelo leve apos turno pesado
        if hasattr(self, "_original_model") and self._original_model:
            self.model = self._original_model
            self._original_model = None

        return turn.assistant_message


    # ── Helpers ──────────────────────────────────────────

    def _has_recent_errors(self) -> bool:
        """Verifica se ha erros nas ultimas mensagens do contexto."""
        for msg in self.session.messages[-5:]:
            if msg.get("role") == "tool":
                content = msg.get("content", "")
                if isinstance(content, str) and any(
                    kw in content.lower()
                    for kw in ("error", "traceback", "failed", "errno")
                ):
                    return True
        return False

    # ── Roteamento Hibrido por Etapa ──────────────────────

    def _select_model_for_iteration(
        self,
        iteration: int,
        error_count: int,
        prev_tool_calls: list[dict] | None,
    ) -> None:
        """Mantem o modelo escolhido pelo orquestrador durante todo o turno.

        Trocar de modelo mid-loop causa perda de contexto e respostas
        incompletas. O orquestrador ja escolheu o modelo certo no inicio.
        Unica excecao: promove para reasoner se houve erros repetidos.
        """
        if not self._orchestration or self.is_subagent:
            return

        # Unico caso de troca: erros repetidos precisam de raciocinio profundo
        if (error_count >= 2 and self._has_recent_errors()
                and self.model != config.DEEPSEEK_REASONER_MODEL):
            log_action(
                "model_promotion",
                f"iter={iteration} {self.model}->{config.DEEPSEEK_REASONER_MODEL} reason=repeated-errors",
                session_id=self.session.id,
            )
            self.model = config.DEEPSEEK_REASONER_MODEL

    # ── Streaming Call ─────────────────────────────────────────

    def _stream_call(self) -> tuple[str, list[dict], dict]:
        """Faz chamada streaming com retry para rate limit (429) e erro de historico (400)."""
        max_retries = config.MAX_RETRY_ATTEMPTS
        history_retried = False

        for attempt in range(max_retries):
            try:
                return self._stream_call_openai()
            except Exception as e:
                err_str = str(e).lower()

                # ── Erro 400: historico de mensagens invalido ──
                is_history_error = (
                    "400" in err_str
                    and ("tool" in err_str or "tool_calls" in err_str
                         or "preceding" in err_str or "message" in err_str)
                )
                if is_history_error and not history_retried:
                    history_retried = True
                    log_action(
                        "history_error_recovery",
                        f"erro 400 detectado, sanitizando historico: {str(e)[:200]}",
                        level="error",
                        session_id=self.session.id,
                    )
                    # Sanitiza o historico real
                    before = len(self.session.messages)
                    self.session.messages = sanitize_messages(
                        self.session.messages, self.session.id
                    )
                    after = len(self.session.messages)
                    log_action(
                        "history_error_recovery",
                        f"sanitizado: {before} -> {after} msgs, retentando",
                        level="warning",
                        session_id=self.session.id,
                    )

                    # Se sanitizar nao mudou nada, o problema e mais grave — reseta
                    if before == after:
                        log_action(
                            "history_reset",
                            "sanitizacao nao resolveu, resetando historico",
                            level="error",
                            session_id=self.session.id,
                        )
                        self._reset_to_system_prompt()

                    continue

                # ── Rate limit 429 ──
                is_rate_limit = (
                    "429" in err_str
                    or "rate_limit" in err_str
                    or "rate limit" in err_str
                    or "overloaded" in err_str
                )
                if is_rate_limit and attempt < max_retries - 1:
                    wait = min(30 * (attempt + 1), 90)
                    import re as _re_retry
                    retry_match = _re_retry.search(r"retry.after[:\s]*(\d+)", err_str)
                    if retry_match:
                        wait = int(retry_match.group(1))
                    self.on_rate_limit(wait, attempt + 1, max_retries)
                    continue
                raise

        raise RuntimeError(
            "Rate limit excedido apos todas as tentativas. "
            "Tente novamente em alguns minutos."
        )

    def _reset_to_system_prompt(self) -> None:
        """Reset de emergencia: mantem apenas system prompt + ultima mensagem do usuario."""
        system = None
        last_user = None

        for msg in self.session.messages:
            if msg.get("role") == "system" and system is None:
                system = msg
        for msg in reversed(self.session.messages):
            if msg.get("role") == "user":
                last_user = msg
                break

        new_msgs = []
        if system:
            new_msgs.append(system)
        if last_user:
            new_msgs.append(last_user)

        self.session.messages = new_msgs
        log_action(
            "history_reset",
            f"historico resetado para {len(new_msgs)} msgs (system + last user)",
            level="warning",
            session_id=self.session.id,
        )

    def _stream_call_openai(self) -> tuple[str, list[dict], dict]:
        """Streaming via DeepSeek (OpenAI-compatible API) com context caching."""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": self._get_messages(),
            "temperature": config.TEMPERATURE,
            "stream": True,
        }

        kwargs["max_tokens"] = config.MAX_TOKENS
        kwargs["stream_options"] = {"include_usage": True}

        tools = self._get_active_tools()
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        # DeepSeek Context Caching: extra_headers para ativar cache de prefixo
        kwargs["extra_headers"] = {"cache-control": "ephemeral"}

        stream = self._client.chat.completions.create(**kwargs)

        collected_text = []
        collected_tool_calls: dict[int, dict] = {}
        usage_data = {"prompt_tokens": 0, "completion_tokens": 0, "cache_hit_tokens": 0, "cache_miss_tokens": 0}

        for chunk in stream:
            if hasattr(chunk, "usage") and chunk.usage:
                usage_data["prompt_tokens"] = chunk.usage.prompt_tokens or 0
                usage_data["completion_tokens"] = chunk.usage.completion_tokens or 0
                # DeepSeek cache metrics (prompt_cache_hit_tokens / prompt_cache_miss_tokens)
                if hasattr(chunk.usage, "prompt_cache_hit_tokens"):
                    usage_data["cache_hit_tokens"] = chunk.usage.prompt_cache_hit_tokens or 0
                if hasattr(chunk.usage, "prompt_cache_miss_tokens"):
                    usage_data["cache_miss_tokens"] = chunk.usage.prompt_cache_miss_tokens or 0

            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            if delta.content:
                collected_text.append(delta.content)
                self.on_text_delta(delta.content)

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in collected_tool_calls:
                        collected_tool_calls[idx] = {
                            "id": tc.id or "",
                            "name": "",
                            "arguments": "",
                        }
                    if tc.id:
                        collected_tool_calls[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            collected_tool_calls[idx]["name"] = tc.function.name
                        if tc.function.arguments:
                            collected_tool_calls[idx]["arguments"] += tc.function.arguments

        text = "".join(collected_text)
        tool_calls = [collected_tool_calls[k] for k in sorted(collected_tool_calls)]
        return text, tool_calls, usage_data

    # ── Tool Loading Dinâmico (Lazy) ─────────────────────────────

    # Tools sempre disponiveis em qualquer contexto
    # Claude Code Architecture: 9 core tools always available
    # All others loaded ONLY when orchestrator detects explicit need
    CORE_TOOLS = {"read", "write", "edit", "glob", "grep", "bash", "agent",
                  "web_search", "web_fetch"}

    def _get_active_tools(self) -> list[dict]:
        """Claude Code tool filtering pipeline:
        1. Core tools (always available)
        2. Orchestrator-detected tools (by keyword)
        3. Previously-used tools (continuity)
        4. Sort for cache stability
        5. Never send >20 tools total
        """
        # If conversational — NO tools
        if self._orchestration and not self._orchestration.get("needs_tools", True):
            log_action("tool_loading", "conversational=True, no tools sent", session_id=self.session.id)
            return []

        if not config.CLOW_TOOL_PRUNING:
            return self.registry.openai_tools()

        # Step 1: Core tools (9 — always available)
        allowed = set(self.CORE_TOOLS)

        # Step 2: Orchestrator-detected tools
        if self._orchestration:
            allowed.update(self._orchestration.get("relevant_tools", set()))

        # Step 3: Previously-used tools (continuity in this turn)
        for msg in self.session.messages[-10:]:  # Only recent messages
            if msg.get("role") == "assistant":
                for tc in msg.get("tool_calls", []):
                    fn = tc.get("function", {})
                    name = fn.get("name", tc.get("name", ""))
                    if name:
                        allowed.add(name)

        # Step 4: Cap at 20 tools max (Claude Code never sends >42, we cap at 20)
        available = set(self.registry.names())
        final = allowed & available
        if len(final) > 20:
            # Prioritize core tools + most recently used
            core = final & set(self.CORE_TOOLS)
            extra = list(final - core)[:20 - len(core)]
            final = core | set(extra)

        # Step 5: Sort for cache stability (built-in first)
        tools = self.registry.openai_tools_filtered(final)

        log_action(
            "tool_loading",
            f"sent={len(tools)}/{len(available)} tools={sorted(final)}",
            session_id=self.session.id,
        )

        return tools

    # ── Tool Execution (parallel + sequential) ─────────────────

    def _execute_tool_calls(self, tool_calls_data: list[dict], turn: Turn) -> list[ToolResult]:
        """Executa tool calls — paralelo para read-only, sequencial para write."""
        results: list[ToolResult] = []

        # Separa read-only das write tools
        parallel_calls: list[dict] = []
        sequential_calls: list[dict] = []

        for tc_data in tool_calls_data:
            if tc_data["name"] in READ_ONLY_TOOLS:
                parallel_calls.append(tc_data)
            else:
                sequential_calls.append(tc_data)

        # Executa read-only em paralelo quando ha mais de uma
        if parallel_calls and len(parallel_calls) > 1:
            futures: list[tuple[dict, Future]] = []
            for tc_data in parallel_calls:
                future = self._executor.submit(self._execute_single_tool, tc_data, turn)
                futures.append((tc_data, future))

            for tc_data, future in futures:
                try:
                    result = future.result(timeout=120)
                    results.append(result)
                except Exception as e:
                    tr = ToolResult(
                        tool_call_id=tc_data["id"],
                        status=ToolResultStatus.ERROR,
                        output=f"Erro paralelo: {e}",
                    )
                    results.append(tr)
        else:
            # Uma unica read-only ou nenhuma — executa sequencial
            for tc_data in parallel_calls:
                results.append(self._execute_single_tool(tc_data, turn))

        # Executa write tools sequencialmente
        for tc_data in sequential_calls:
            results.append(self._execute_single_tool(tc_data, turn))

        return results

    def _execute_single_tool(self, tc_data: dict, turn: Turn) -> ToolResult:
        """Executa uma unica tool call com hooks e permissoes."""
        tool_call = ToolCall(
            id=tc_data["id"],
            name=tc_data["name"],
            arguments=self._parse_arguments(tc_data["arguments"]),
        )
        turn.tool_calls.append(tool_call)

        # Hook pre_tool_call (protocolo exit-code: 0=allow, 2=deny, outro=warn)
        pre_results = self.hooks.run_hooks(
            "pre_tool_call",
            {"tool_name": tool_call.name, "tool_args": json.dumps(tool_call.arguments)},
            self.cwd,
        )
        hook_warnings = []
        for hr in pre_results:
            if hr.blocked:
                tr = ToolResult(
                    tool_call_id=tool_call.id,
                    status=ToolResultStatus.DENIED,
                    output=f"Hook bloqueou: {hr.feedback}",
                )
                turn.tool_results.append(tr)
                self.on_tool_result(tool_call.name, "denied", tr.output)
                return tr
            if hr.is_warning and hr.feedback:
                hook_warnings.append(hr.feedback)

        # Plan mode: bloqueia ferramentas de escrita
        if self.plan_mode and tool_call.name not in READ_ONLY_TOOLS and tool_call.name not in (
            "task_create", "task_update", "task_list", "task_get",
        ):
            tr = ToolResult(
                tool_call_id=tool_call.id,
                status=ToolResultStatus.DENIED,
                output=(
                    f"[PLAN MODE] Ferramenta '{tool_call.name}' bloqueada no modo plano. "
                    "Apenas leitura permitida. Use /plan off para desativar."
                ),
            )
            turn.tool_results.append(tr)
            self.on_tool_result(tool_call.name, "denied", tr.output)
            return tr

        self.on_tool_call(tool_call.name, tool_call.arguments)

        # Busca ferramenta
        tool = self.registry.get(tool_call.name)
        if tool is None:
            tr = ToolResult(
                tool_call_id=tool_call.id,
                status=ToolResultStatus.ERROR,
                output=f"Ferramenta '{tool_call.name}' nao encontrada.",
            )
            turn.tool_results.append(tr)
            self.on_tool_result(tool_call.name, "error", tr.output)
            return tr

        # Permissao
        if not self.auto_approve and needs_confirmation(tool_call.name, tool_call.arguments):
            prompt = format_confirmation_prompt(tool_call.name, tool_call.arguments)
            if not self.ask_confirmation(prompt):
                tr = ToolResult(
                    tool_call_id=tool_call.id,
                    status=ToolResultStatus.DENIED,
                    output="Usuario negou a execucao desta ferramenta.",
                )
                turn.tool_results.append(tr)
                self.on_tool_result(tool_call.name, "denied", tr.output)
                return tr

        # Executa
        try:
            output = tool.execute(**tool_call.arguments)
            tr = ToolResult(
                tool_call_id=tool_call.id,
                status=ToolResultStatus.SUCCESS,
                output=output,
            )
        except Exception as e:
            tr = ToolResult(
                tool_call_id=tool_call.id,
                status=ToolResultStatus.ERROR,
                output=f"Erro ao executar {tool_call.name}: {e}",
            )
            self.hooks.run_hooks(
                "on_error",
                {"tool_name": tool_call.name, "error": str(e)},
                self.cwd,
            )

        # Injeta warnings dos pre-hooks no output
        if hook_warnings:
            tr.output = "\n".join(hook_warnings) + "\n" + tr.output

        # Hook post_tool_call (exit 2 = marca resultado como erro)
        post_results = self.hooks.run_hooks(
            "post_tool_call",
            {
                "tool_name": tool_call.name,
                "tool_args": json.dumps(tool_call.arguments),
                "tool_output": tr.output[:2000],
                "tool_status": tr.status.value,
            },
            self.cwd,
        )
        for hr in post_results:
            if hr.blocked:
                tr.status = ToolResultStatus.ERROR
                tr.output += f"\n{hr.feedback}"
            elif hr.is_warning and hr.feedback:
                tr.output += f"\n{hr.feedback}"

        log_action("tool_exec", f"{tool_call.name}: {tr.status.value}", tool_name=tool_call.name)

        # ── Vision Feedback Loop: screenshot após write/edit de UI files ──
        if (
            config.CLOW_VISION_FEEDBACK
            and tr.status == ToolResultStatus.SUCCESS
            and tool_call.name in ("write", "edit")
        ):
            filepath = tool_call.arguments.get("file_path", "")
            if filepath and any(filepath.endswith(ext) for ext in (".html", ".jsx", ".tsx", ".css")):
                screenshot_b64 = self._vision_check(filepath)
                if screenshot_b64:
                    # Injeta screenshot como mensagem no historico para avaliacao visual
                    vision_msg = {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": screenshot_b64,
                                },
                            },
                            {
                                "type": "text",
                                "text": (
                                    f"Screenshot do resultado gerado ({os.path.basename(filepath)}). "
                                    "Avalie se ficou correto e corrija se necessario."
                                ),
                            },
                        ],
                    }
                    self.session.messages.append(vision_msg)
                    log_action(
                        "vision_feedback",
                        f"screenshot capturado: {filepath}",
                        session_id=self.session.id,
                    )

        turn.tool_results.append(tr)
        self.on_tool_result(tool_call.name, tr.status.value, tr.output)
        return tr

    # ── Auto-Correction Error Detection ─────────────────────────

    ERROR_PATTERNS = re.compile(
        r"(?:error|traceback|failed|SyntaxError|TypeError|NameError|"
        r"ImportError|FileNotFoundError|KeyError|ValueError|"
        r"IndentationError|AttributeError|ModuleNotFoundError)",
        re.IGNORECASE,
    )

    def _detect_tool_errors(self, tool_results: list[ToolResult]) -> bool:
        """Detecta se algum tool result contém erro que merece auto-correção."""
        for tr in tool_results:
            # Status explícito de erro
            if tr.status == ToolResultStatus.ERROR:
                return True
            # Padrões de erro no output de bash/comandos
            if tr.output and self.ERROR_PATTERNS.search(tr.output):
                # Ignora falsos positivos: menções em texto informativo
                # Só considera se o output começa com indicadores de falha
                output_lower = tr.output.lower()
                # Evita falso positivo quando "error" aparece em contexto informativo
                if any(indicator in output_lower for indicator in (
                    "traceback", "syntaxerror", "nameerror", "typeerror",
                    "importerror", "filenotfounderror", "indentationerror",
                    "exit code", "command failed", "errno",
                    "failed to", "error:",
                )):
                    return True
        return False

    # ── Vision Feedback Loop ──────────────────────────────────

    VISION_EXTENSIONS = {".html", ".jsx", ".tsx", ".css"}

    def _vision_check(self, filepath: str) -> str | None:
        """Renderiza arquivo HTML com Playwright headless e retorna screenshot base64.

        Para .jsx/.tsx/.css, gera wrapper HTML temporario.
        Retorna None se Playwright nao estiver disponivel ou der erro.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            log_action("vision_feedback", "playwright nao instalado, pulando", session_id=self.session.id)
            return None

        try:
            filepath_obj = Path(filepath)
            if not filepath_obj.exists():
                return None

            # Para CSS/JSX/TSX, cria wrapper HTML temporário
            if filepath_obj.suffix in (".css",):
                html_content = (
                    f"<html><head><link rel='stylesheet' href='file:///{filepath_obj.as_posix()}'></head>"
                    "<body><h1>CSS Preview</h1><div class='container'><p>Sample content</p></div></body></html>"
                )
                temp_html = filepath_obj.parent / f"_clow_preview_{filepath_obj.stem}.html"
                temp_html.write_text(html_content, encoding="utf-8")
                render_path = temp_html
            elif filepath_obj.suffix in (".jsx", ".tsx"):
                # JSX/TSX: renderiza o source code como preview
                source = filepath_obj.read_text(encoding="utf-8")[:3000]
                html_content = (
                    "<html><head><style>body{font-family:monospace;padding:20px;background:#1e1e1e;color:#d4d4d4;}"
                    "pre{white-space:pre-wrap;}</style></head>"
                    f"<body><h3 style='color:#7C5CFC;'>{filepath_obj.name}</h3><pre>{source}</pre></body></html>"
                )
                temp_html = filepath_obj.parent / f"_clow_preview_{filepath_obj.stem}.html"
                temp_html.write_text(html_content, encoding="utf-8")
                render_path = temp_html
            else:
                render_path = filepath_obj
                temp_html = None

            # Captura screenshot com Playwright
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                page.goto(f"file:///{render_path.as_posix()}", wait_until="networkidle", timeout=15000)
                # Espera renderizar
                page.wait_for_timeout(500)
                screenshot_bytes = page.screenshot(type="png", full_page=True)
                browser.close()

            # Limpa arquivo temporário
            if temp_html and temp_html.exists():
                temp_html.unlink()

            return base64.b64encode(screenshot_bytes).decode("utf-8")

        except Exception as e:
            log_action("vision_feedback", f"erro: {e}", level="warning", session_id=self.session.id)
            return None

    # ── Context Management ─────────────────────────────────────

    def _get_messages(self) -> list[dict]:
        """5-stage preprocessing pipeline (Claude Code architecture).

        Before every API call, messages pass through:
        1. Tool result budget -- cap old tool results to save tokens
        2. Snip -- remove flagged/deleted messages
        3. MicroCompact -- clear old tool result content (keep last 3)
        4. Context collapse -- merge adjacent same-role messages
        5. AutoCompact -- LLM summarize if over threshold
        """
        msgs = list(self.session.messages)

        # Stage 1: Tool result budget -- cap old tool results to save tokens
        msgs = self._stage_tool_result_budget(msgs)

        # Stage 2: Snip -- remove any flagged/deleted messages
        msgs = self._stage_snip(msgs)

        # Stage 3: MicroCompact -- clear old tool result content (keep last 3)
        msgs = self._stage_microcompact(msgs)

        # Stage 4: Context collapse -- merge adjacent same-role messages
        msgs = self._stage_context_collapse(msgs)

        # Stage 5: AutoCompact -- summarize if over threshold
        if self._should_autocompact(msgs):
            self._maybe_compact()
            msgs = list(self.session.messages)

        # Sanitize and truncate
        msgs = sanitize_messages(msgs, self.session.id)
        msgs = _slice_at_safe_boundary(msgs, config.MAX_CONTEXT_MESSAGES)
        msgs = sanitize_messages(msgs, self.session.id)

        # Truncate large tool results
        max_chars = config.MAX_TOOL_RESULT_CHARS
        truncated = []
        for msg in msgs:
            if msg.get("role") == "tool":
                content = msg.get("content", "")
                if isinstance(content, str) and len(content) > max_chars:
                    msg = dict(msg)
                    msg["content"] = content[:max_chars] + "\n... (truncado)"
            truncated.append(msg)

        # DeepSeek cache control on system prompt
        if truncated and truncated[0].get("role") == "system":
            truncated[0] = dict(truncated[0])
            truncated[0]["cache_control"] = {"type": "ephemeral"}

        return truncated

    # -- 5-Stage Preprocessing Methods (Claude Code Architecture) --

    def _stage_tool_result_budget(self, msgs: list[dict]) -> list[dict]:
        """Stage 1: Cap tool results to max 500 chars each, except last 3."""
        tool_indices = [i for i, m in enumerate(msgs) if m.get("role") == "tool"]
        if len(tool_indices) <= 3:
            return msgs
        # Keep last 3 full, truncate older ones more aggressively
        old_indices = set(tool_indices[:-3])
        result = []
        for i, msg in enumerate(msgs):
            if i in old_indices:
                msg = dict(msg)
                content = msg.get("content", "")
                if isinstance(content, str) and len(content) > 500:
                    msg["content"] = content[:500] + "\n[... resultado antigo truncado]"
            result.append(msg)
        return result

    def _stage_snip(self, msgs: list[dict]) -> list[dict]:
        """Stage 2: Remove messages flagged for deletion."""
        return [m for m in msgs if not m.get("_snipped")]

    def _stage_microcompact(self, msgs: list[dict]) -> list[dict]:
        """Stage 3: MicroCompact via compaction module (Tier 1)."""
        from .compaction import microcompact
        return microcompact(msgs)

    def _stage_context_collapse(self, msgs: list[dict]) -> list[dict]:
        """Stage 4: Merge adjacent messages with same role."""
        if not msgs:
            return msgs
        result = [msgs[0]]
        for msg in msgs[1:]:
            prev = result[-1]
            # Merge adjacent user messages
            if msg.get("role") == prev.get("role") == "user":
                if isinstance(prev.get("content"), str) and isinstance(msg.get("content"), str):
                    merged = dict(prev)
                    merged["content"] = prev["content"] + "\n\n" + msg["content"]
                    result[-1] = merged
                    continue
            result.append(msg)
        return result

    def _should_autocompact(self, msgs: list[dict]) -> bool:
        """Check if context exceeds autocompact threshold."""
        total_chars = sum(
            len(m.get("content", "")) if isinstance(m.get("content"), str) else 0
            for m in msgs
        )
        # Threshold: ~80K tokens estimated (320K chars)
        return total_chars > 320_000

    def _maybe_compact(self) -> None:
        """3-tier compaction system (Claude Code architecture).

        Tier 1: MicroCompact — runs automatically in _get_messages preprocessing
        Tier 2: Session Memory — tries pre-built summary first (no LLM)
        Tier 3: Full Compact — LLM summarization as last resort
        """
        from .compaction import auto_compact_if_needed

        # Build session memory from _summarize_messages (existing method)
        session_memory = ""
        try:
            old_msgs = self.session.messages[1:-5] if len(self.session.messages) > 6 else []
            if old_msgs:
                session_memory = self._summarize_messages(old_msgs) or ""
        except Exception:
            pass

        result = auto_compact_if_needed(
            self.session.messages,
            session_memory=session_memory,
            llm_client=self._client,
            query_source="chat",
        )

        if result:
            self.session.messages = result
            # Re-sanitize after compaction
            self.session.messages = sanitize_messages(self.session.messages, self.session.id)
            log_action("compaction_applied", f"messages: {len(result)}", session_id=self.session.id)

    def _summarize_messages(self, messages: list[dict]) -> str:
        """Resume mensagens antigas com extracao semantica estruturada.

        Extrai antes de resumir:
        - Arquivos mencionados/modificados
        - Itens de trabalho pendentes
        - Decisoes tomadas
        - Padroes de uso de ferramentas
        - Erros encontrados e suas solucoes
        """
        if not messages:
            return ""

        try:
            # Fase 1: Extracao semantica local (sem LLM)
            files_mentioned: set[str] = set()
            tools_used: dict[str, int] = {}
            errors_found: list[str] = []
            decisions: list[str] = []

            for msg in messages:
                role = msg.get("role", "")
                content = msg.get("content", "")

                if isinstance(content, str):
                    # Extrai caminhos de arquivo
                    import re as _re
                    file_matches = _re.findall(
                        r'(?:^|\s|[`"\'])([a-zA-Z_./\\][\w./\\-]*\.\w{1,10})(?:\s|$|[`"\'])',
                        content,
                    )
                    for fm in file_matches:
                        if not fm.startswith("http") and len(fm) < 200:
                            files_mentioned.add(fm)

                    # Extrai decisoes (frases com "vamos", "decidi", "escolhi", etc)
                    for pattern in [
                        r"(?:vamos|decidi|escolhi|optei|melhor)\s+.{10,80}",
                        r"(?:decided|chose|will use|going with)\s+.{10,80}",
                    ]:
                        for match in _re.findall(pattern, content, _re.IGNORECASE):
                            if len(decisions) < 5:
                                decisions.append(match.strip())

                # Conta ferramentas usadas
                if role == "assistant":
                    for tc in msg.get("tool_calls", []):
                        name = tc.get("function", {}).get("name", tc.get("name", ""))
                        if name:
                            tools_used[name] = tools_used.get(name, 0) + 1

                # Coleta erros
                if role == "tool":
                    if isinstance(content, str) and ("erro" in content.lower() or "error" in content.lower()):
                        errors_found.append(content[:100])

            # Fase 2: Resumo via LLM com contexto estruturado
            text_parts = []
            for msg in messages[:50]:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if isinstance(content, str) and content:
                    text_parts.append(f"[{role}] {content[:200]}")

            if not text_parts:
                return ""

            conversation_text = "\n".join(text_parts)
            summary_prompt = (
                "Resuma a conversa abaixo em 3-5 frases curtas, mantendo "
                "informacoes tecnicas importantes (arquivos, decisoes, erros encontrados).\n\n"
                "Foque em: o que foi feito, o que ficou pendente, e decisoes tecnicas."
            )

            response = self._client.chat.completions.create(
                model=config.CLOW_MODEL,
                messages=[
                    {"role": "system", "content": summary_prompt},
                    {"role": "user", "content": conversation_text[:4000]},
                ],
                max_tokens=600,
                temperature=0.1,
            )
            llm_summary = response.choices[0].message.content or ""

            # Fase 3: Monta resumo estruturado
            parts = []
            if llm_summary:
                parts.append(f"Resumo: {llm_summary}")
            if files_mentioned:
                sorted_files = sorted(files_mentioned)[:20]
                parts.append(f"Arquivos referenciados: {', '.join(sorted_files)}")
            if tools_used:
                top_tools = sorted(tools_used.items(), key=lambda x: -x[1])[:10]
                tools_str = ", ".join(f"{n}({c}x)" for n, c in top_tools)
                parts.append(f"Ferramentas usadas: {tools_str}")
            if decisions:
                parts.append("Decisoes: " + "; ".join(decisions[:5]))
            if errors_found:
                parts.append("Erros encontrados: " + "; ".join(errors_found[:3]))

            return "\n".join(parts)

        except Exception:
            return ""

    # ── Auto-Memory ────────────────────────────────────────────

    def _check_auto_memory(self, user_message: str) -> None:
        """Detecta correcoes/confirmacoes e salva na memoria automaticamente."""
        msg_lower = user_message.lower()

        # Verifica correcoes
        for pattern in CORRECTION_PATTERNS:
            if re.search(pattern, msg_lower):
                try:
                    save_memory(
                        f"feedback_{int(time.time())}",
                        f"Correcao do usuario: {user_message[:200]}",
                        memory_type="feedback",
                    )
                except Exception:
                    pass
                return

        # Verifica confirmacoes — salva contexto da ultima resposta
        for pattern in CONFIRMATION_PATTERNS:
            if re.search(pattern, msg_lower):
                last_assistant = ""
                for msg in reversed(self.session.messages):
                    if msg.get("role") == "assistant" and msg.get("content"):
                        last_assistant = msg["content"][:200]
                        break

                if last_assistant:
                    try:
                        save_memory(
                            f"confirmed_{int(time.time())}",
                            f"Abordagem confirmada pelo usuario.\nContexto: {last_assistant}",
                            memory_type="feedback",
                        )
                    except Exception:
                        pass
                return

    # ── Background Agents ──────────────────────────────────────

    def run_background(self, task: str, description: str = "") -> str:
        """Executa um sub-agente em background. Retorna ID do job."""
        job_id = uuid.uuid4().hex[:8]

        with self._background_lock:
            self._background_results[job_id] = {
                "id": job_id,
                "description": description or task[:50],
                "status": "running",
                "output": "",
                "started_at": time.time(),
            }

        def _run():
            try:
                sub = SubAgent(parent=self, task=task)
                result = sub.run()
                with self._background_lock:
                    self._background_results[job_id]["status"] = "completed"
                    self._background_results[job_id]["output"] = result or ""
                    self._background_results[job_id]["completed_at"] = time.time()
            except Exception as e:
                with self._background_lock:
                    self._background_results[job_id]["status"] = "error"
                    self._background_results[job_id]["output"] = str(e)
                    self._background_results[job_id]["completed_at"] = time.time()

        thread = threading.Thread(target=_run, daemon=True, name=f"bg-agent-{job_id}")
        thread.start()

        return job_id

    def _check_background_notifications(self) -> None:
        """Verifica e notifica sobre background agents completados."""
        with self._background_lock:
            for job_id, info in list(self._background_results.items()):
                if info.get("status") in ("completed", "error") and not info.get("notified"):
                    info["notified"] = True
                    status = info["status"]
                    desc = info["description"]
                    # Injeta notificacao no contexto
                    notification = (
                        f"[Background Agent Completado] ID: {job_id}, "
                        f"Descricao: {desc}, Status: {status}"
                    )
                    if info.get("output"):
                        notification += f"\nResultado: {info['output'][:500]}"
                    self.session.messages.append({
                        "role": "system",
                        "content": notification,
                    })

    def get_background_status(self) -> list[dict]:
        """Retorna status de todos os background agents."""
        with self._background_lock:
            return list(self._background_results.values())

    # ── Message Building ───────────────────────────────────────

    def _build_assistant_message(self, text: str, tool_calls_data: list[dict]) -> dict:
        """Constroi dict de mensagem do assistente."""
        msg: dict[str, Any] = {"role": "assistant"}

        if text:
            msg["content"] = text

        if tool_calls_data:
            msg["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": tc["arguments"],
                    },
                }
                for tc in tool_calls_data
            ]

        return msg

    @staticmethod
    def _parse_arguments(arguments: str | dict) -> dict:
        """Parseia arguments de tool call com reparo de JSON malformado.

        DeepSeek as vezes gera JSON com aspas nao escapadas dentro de strings,
        especialmente no campo 'command' do bash tool. Ex:
          {"command": "echo "hello""}  -> invalido
        """
        if isinstance(arguments, dict):
            return arguments
        if not arguments or not isinstance(arguments, str):
            return {"raw": arguments}

        # Tentativa 1: parse direto
        try:
            return json.loads(arguments)
        except (json.JSONDecodeError, TypeError):
            pass

        # Tentativa 2: repara JSON truncado/malformado
        repaired = _repair_tool_json(arguments)
        if repaired is not None:
            return repaired

        # Tentativa 3: extrai campo command de bash tool calls quebrados
        # Padrao comum: {"command": "...conteudo com aspas..."}
        cmd_match = re.search(r'"command"\s*:\s*"', arguments)
        if cmd_match:
            start = cmd_match.end()
            # Pega tudo ate o final, remove trailing "} se existir
            raw_cmd = arguments[start:].rstrip()
            for suffix in ('"}', '"}', '"', '}'):
                if raw_cmd.endswith(suffix):
                    raw_cmd = raw_cmd[:-len(suffix)]
                    break
            return {"command": raw_cmd}

        return {"raw": arguments}


class SubAgent:
    """Sub-agente para executar tarefas em paralelo/isoladas."""

    def __init__(self, parent: Agent, task: str):
        self.parent = parent
        self.task = task

    def run(self) -> str:
        """Executa sub-agente com contexto limitado."""
        agent = Agent(
            cwd=self.parent.cwd,
            model=self.parent.model,
            on_text_delta=lambda t: None,  # Silencioso
            on_text_done=lambda t: None,
            on_tool_call=self.parent.on_tool_call,
            on_tool_result=self.parent.on_tool_result,
            ask_confirmation=self.parent.ask_confirmation,
            auto_approve=self.parent.auto_approve,
            is_subagent=True,
        )
        return agent.run_turn(self.task)
