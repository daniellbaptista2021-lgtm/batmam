"""Agent Loop — o coracao do Clow v0.2.0.

Orquestra o ciclo: prompt -> modelo -> tool calls -> execucao -> resultado -> modelo...
Suporta streaming, sub-agents, execucao paralela, background agents,
plan mode, context inteligente e auto-memory.
"""

from __future__ import annotations
import json
import os
import sys
import re
import time
import threading
import uuid
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


class Agent:
    """Agente principal do Clow v0.2.0."""

    def __init__(
        self,
        cwd: str | None = None,
        session: Session | None = None,
        model: str | None = None,
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

        # Client — suporta Anthropic e OpenAI
        self._provider = config.CLOW_PROVIDER
        if self._provider == "anthropic":
            if not config.ANTHROPIC_API_KEY:
                raise RuntimeError("ANTHROPIC_API_KEY nao configurada.")
            from anthropic import Anthropic
            self._anthropic = Anthropic(api_key=config.ANTHROPIC_API_KEY)
            self._client = None
        else:
            if not config.OPENAI_API_KEY:
                raise RuntimeError("OPENAI_API_KEY nao configurada.")
            from openai import OpenAI
            self._anthropic = None
            self._client = OpenAI(api_key=config.OPENAI_API_KEY)

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
        """Constroi system prompt com contexto de projeto e memoria."""
        system_parts = [get_system_prompt(self.cwd)]

        # CLOW.md do projeto
        project_ctx = load_project_context(self.cwd)
        if project_ctx:
            system_parts.append(f"\n# Contexto do Projeto (CLOW.md)\n{project_ctx}")

        # Memoria persistente
        if not self.is_subagent:
            memory_ctx = load_memory_context()
            if memory_ctx:
                system_parts.append(f"\n# Memoria\n{memory_ctx}")

        self.session.messages = [
            {"role": "system", "content": "\n\n".join(system_parts)}
        ]

    # ── Main Turn Loop ─────────────────────────────────────────

    def run_turn(self, user_message: str) -> str:
        """Executa um turno completo com streaming."""

        # Hook pre_turn
        pre_results = self.hooks.run_hooks(
            "pre_turn", {"user_message": user_message}, self.cwd
        )
        for hr in pre_results:
            if hr.blocked:
                return f"[Hook bloqueou execucao] {hr.feedback}"

        self.session.messages.append({"role": "user", "content": user_message})
        log_action("turn_start", user_message[:80], session_id=self.session.id)

        # Auto-memory: detecta correcoes e confirmacoes
        if not self.is_subagent:
            self._check_auto_memory(user_message)

        turn = Turn(user_message=user_message)
        full_response_text = []
        max_iterations = 30
        iteration = 0

        try:
            while iteration < max_iterations:
                iteration += 1

                # Chama modelo com streaming
                text_content, tool_calls_data, usage = self._stream_call()

                turn.tokens_in += usage.get("prompt_tokens", 0)
                turn.tokens_out += usage.get("completion_tokens", 0)

                if text_content:
                    full_response_text.append(text_content)
                    self.on_text_done(text_content)

                # Monta mensagem do assistente para historico
                assistant_msg = self._build_assistant_message(text_content, tool_calls_data)
                self.session.messages.append(assistant_msg)

                # Se nao tem tool calls, acabou
                if not tool_calls_data:
                    break

                # Executa tool calls (com paralelismo para read-only)
                tool_results = self._execute_tool_calls(tool_calls_data, turn)

                # Adiciona resultados ao historico
                for tr in tool_results:
                    self.session.messages.append(tr.to_message())

        except Exception as e:
            # Hook on_error
            self.hooks.run_hooks("on_error", {"error": str(e)}, self.cwd)
            log_action("turn_error", str(e), level="error", session_id=self.session.id)
            raise

        # Finaliza turno
        turn.assistant_message = "\n".join(full_response_text)
        self.session.add_tokens(turn.tokens_in, turn.tokens_out)
        log_action(
            "turn_done",
            f"tokens_in={turn.tokens_in} tokens_out={turn.tokens_out}",
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

        return turn.assistant_message

    # ── Streaming Call ─────────────────────────────────────────

    def _stream_call(self) -> tuple[str, list[dict], dict]:
        """Faz chamada streaming com retry automatico para rate limit (429)."""
        max_retries = config.MAX_RETRY_ATTEMPTS

        for attempt in range(max_retries):
            try:
                if self._provider == "anthropic":
                    return self._stream_call_anthropic()
                return self._stream_call_openai()
            except Exception as e:
                err_str = str(e).lower()
                is_rate_limit = (
                    "429" in err_str
                    or "rate_limit" in err_str
                    or "rate limit" in err_str
                    or "overloaded" in err_str
                )
                if is_rate_limit and attempt < max_retries - 1:
                    # Tenta extrair retry-after do erro
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

    def _stream_call_anthropic(self) -> tuple[str, list[dict], dict]:
        """Streaming via Anthropic Messages API."""
        messages = self._get_messages()

        # Separa system prompt das mensagens (Anthropic usa param separado)
        system_prompt = ""
        chat_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_prompt += msg.get("content", "") + "\n"
            else:
                chat_messages.append(msg)

        # Converte tool_results do formato OpenAI para Anthropic
        chat_messages = self._convert_messages_to_anthropic(chat_messages)

        # Tools no formato Anthropic
        tools = self._get_anthropic_tools()

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": chat_messages,
            "max_tokens": config.MAX_TOKENS,
        }
        if system_prompt.strip():
            kwargs["system"] = system_prompt.strip()
        if tools:
            kwargs["tools"] = tools

        collected_text = []
        collected_tool_calls: dict[int, dict] = {}
        usage_data = {"prompt_tokens": 0, "completion_tokens": 0}
        current_tool_idx = -1

        with self._anthropic.messages.stream(**kwargs) as stream:
            for event in stream:
                event_type = event.type

                if event_type == "message_start":
                    if hasattr(event, "message") and hasattr(event.message, "usage"):
                        usage_data["prompt_tokens"] = event.message.usage.input_tokens or 0

                elif event_type == "message_delta":
                    if hasattr(event, "usage") and event.usage:
                        usage_data["completion_tokens"] = event.usage.output_tokens or 0

                elif event_type == "content_block_start":
                    block = event.content_block
                    if block.type == "tool_use":
                        current_tool_idx += 1
                        collected_tool_calls[current_tool_idx] = {
                            "id": block.id,
                            "name": block.name,
                            "arguments": "",
                        }

                elif event_type == "content_block_delta":
                    delta = event.delta
                    if delta.type == "text_delta":
                        collected_text.append(delta.text)
                        self.on_text_delta(delta.text)
                    elif delta.type == "input_json_delta":
                        if current_tool_idx in collected_tool_calls:
                            collected_tool_calls[current_tool_idx]["arguments"] += delta.partial_json

        text = "".join(collected_text)
        tool_calls = [collected_tool_calls[k] for k in sorted(collected_tool_calls)]
        return text, tool_calls, usage_data

    def _stream_call_openai(self) -> tuple[str, list[dict], dict]:
        """Streaming via OpenAI API."""
        from openai import OpenAI

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": self._get_messages(),
            "temperature": config.TEMPERATURE,
            "max_tokens": config.MAX_TOKENS,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        tools = self.registry.openai_tools()
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        stream = self._client.chat.completions.create(**kwargs)

        collected_text = []
        collected_tool_calls: dict[int, dict] = {}
        usage_data = {"prompt_tokens": 0, "completion_tokens": 0}

        for chunk in stream:
            if hasattr(chunk, "usage") and chunk.usage:
                usage_data["prompt_tokens"] = chunk.usage.prompt_tokens or 0
                usage_data["completion_tokens"] = chunk.usage.completion_tokens or 0

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

    # ── Anthropic Helpers ─────────────────────────────────────

    def _get_anthropic_tools(self) -> list[dict]:
        """Converte tools para formato Anthropic."""
        tools = []
        for tool in self.registry.all_tools():
            tools.append({
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.get_schema(),
            })
        return tools

    def _convert_messages_to_anthropic(self, messages: list[dict]) -> list[dict]:
        """Converte mensagens do formato OpenAI para formato Anthropic."""
        result = []
        for msg in messages:
            role = msg.get("role", "")

            # tool results -> user message com tool_result content
            if role == "tool":
                # Agrupa tool results consecutivos
                if result and result[-1]["role"] == "user" and isinstance(result[-1]["content"], list):
                    result[-1]["content"].append({
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id", ""),
                        "content": msg.get("content", ""),
                    })
                else:
                    result.append({
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": msg.get("tool_call_id", ""),
                            "content": msg.get("content", ""),
                        }],
                    })
                continue

            # assistant message com tool_calls -> content blocks
            if role == "assistant":
                content_blocks = []
                text = msg.get("content", "")
                if text:
                    content_blocks.append({"type": "text", "text": text})

                for tc in msg.get("tool_calls", []):
                    func = tc.get("function", {})
                    args_str = func.get("arguments", "{}")
                    try:
                        args = json.loads(args_str) if isinstance(args_str, str) else args_str
                    except (json.JSONDecodeError, TypeError):
                        args = {"raw": args_str}
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": func.get("name", ""),
                        "input": args,
                    })

                if content_blocks:
                    result.append({"role": "assistant", "content": content_blocks})
                continue

            # user e system messages normais
            if role == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    result.append({"role": "user", "content": content})
                else:
                    result.append({"role": "user", "content": content})
                continue

        # Garante alternância user/assistant (Anthropic exige)
        cleaned = []
        for msg in result:
            if cleaned and cleaned[-1]["role"] == msg["role"]:
                # Merge mensagens do mesmo role
                if msg["role"] == "user":
                    prev = cleaned[-1]["content"]
                    curr = msg["content"]
                    if isinstance(prev, str) and isinstance(curr, str):
                        cleaned[-1]["content"] = prev + "\n" + curr
                    elif isinstance(prev, list) and isinstance(curr, list):
                        cleaned[-1]["content"] = prev + curr
                    elif isinstance(prev, str) and isinstance(curr, list):
                        cleaned[-1]["content"] = [{"type": "text", "text": prev}] + curr
                    elif isinstance(prev, list) and isinstance(curr, str):
                        cleaned[-1]["content"] = prev + [{"type": "text", "text": curr}]
                else:
                    # assistant: merge content blocks
                    prev = cleaned[-1].get("content", [])
                    curr = msg.get("content", [])
                    if isinstance(prev, list) and isinstance(curr, list):
                        cleaned[-1]["content"] = prev + curr
            else:
                cleaned.append(msg)

        return cleaned

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

        turn.tool_results.append(tr)
        self.on_tool_result(tool_call.name, tr.status.value, tr.output)
        return tr

    # ── Context Management ─────────────────────────────────────

    def _get_messages(self) -> list[dict]:
        """Retorna mensagens respeitando limites de contexto e truncando tool results grandes."""
        msgs = self.session.messages
        if len(msgs) > config.MAX_CONTEXT_MESSAGES:
            msgs = [msgs[0]] + msgs[-(config.MAX_CONTEXT_MESSAGES - 1):]

        # Trunca tool results muito grandes para reduzir consumo de tokens
        max_chars = config.MAX_TOOL_RESULT_CHARS
        truncated = []
        for msg in msgs:
            if msg.get("role") == "tool":
                content = msg.get("content", "")
                if isinstance(content, str) and len(content) > max_chars:
                    msg = dict(msg)
                    msg["content"] = content[:max_chars] + "\n... (truncado)"
            truncated.append(msg)

        return truncated

    def _maybe_compact(self) -> None:
        """Compacta contexto com resumo LLM se muito grande."""
        if len(self.session.messages) <= config.MAX_CONTEXT_MESSAGES + 30:
            return

        system = self.session.messages[0]
        half = config.MAX_CONTEXT_MESSAGES // 2
        old_messages = self.session.messages[1:-half]
        recent = self.session.messages[-half:]

        # Tenta resumir via LLM (gpt-4.1-mini)
        summary = self._summarize_messages(old_messages)
        if summary:
            summary_msg = {
                "role": "system",
                "content": f"[Resumo do contexto anterior]\n{summary}",
            }
            self.session.messages = [system, summary_msg] + recent
        else:
            # Fallback: descarta mensagens antigas sem resumo
            self.session.messages = [system] + recent

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

            if self._provider == "anthropic":
                response = self._anthropic.messages.create(
                    model="claude-haiku-4-5-20251001",
                    system=summary_prompt,
                    messages=[{"role": "user", "content": conversation_text[:4000]}],
                    max_tokens=600,
                )
                llm_summary = response.content[0].text if response.content else ""
            else:
                response = self._client.chat.completions.create(
                    model="gpt-4.1-mini",
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
        if isinstance(arguments, dict):
            return arguments
        try:
            return json.loads(arguments)
        except (json.JSONDecodeError, TypeError):
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
