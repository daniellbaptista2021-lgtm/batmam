"""Agent Loop — o coracao do Batmam v0.2.0.

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

from openai import OpenAI
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
    """Agente principal do Batmam v0.2.0."""

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
        auto_approve: bool = False,
        is_subagent: bool = False,
    ):
        self.cwd = cwd or os.getcwd()
        self.model = model or config.BATMAM_MODEL
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
        self.auto_approve = auto_approve
        self.is_subagent = is_subagent

        # Client OpenAI
        if not config.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY nao configurada.")
        self._client = OpenAI(api_key=config.OPENAI_API_KEY)

        # Plan mode — bloqueia ferramentas de escrita quando ativo
        self.plan_mode = False

        # Background agents — resultados e lock para thread safety
        self._background_results: dict[str, dict] = {}
        self._background_lock = threading.Lock()

        # Thread pool para execucao paralela de read-only tools
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="batmam-tool")

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

        # BATMAM.md do projeto
        project_ctx = load_project_context(self.cwd)
        if project_ctx:
            system_parts.append(f"\n# Contexto do Projeto (BATMAM.md)\n{project_ctx}")

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
        """Faz chamada streaming e retorna (text, tool_calls, usage)."""

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
            # Usage no final
            if hasattr(chunk, "usage") and chunk.usage:
                usage_data["prompt_tokens"] = chunk.usage.prompt_tokens or 0
                usage_data["completion_tokens"] = chunk.usage.completion_tokens or 0

            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            # Streaming de texto — emite para a UI em tempo real
            if delta.content:
                collected_text.append(delta.content)
                self.on_text_delta(delta.content)

            # Tool calls acumulados
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

        # Hook pre_tool_call
        pre_results = self.hooks.run_hooks(
            "pre_tool_call",
            {"tool_name": tool_call.name, "tool_args": json.dumps(tool_call.arguments)},
            self.cwd,
        )
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

        # Hook post_tool_call
        self.hooks.run_hooks(
            "post_tool_call",
            {
                "tool_name": tool_call.name,
                "tool_args": json.dumps(tool_call.arguments),
                "tool_output": tr.output[:2000],
                "tool_status": tr.status.value,
            },
            self.cwd,
        )
        log_action("tool_exec", f"{tool_call.name}: {tr.status.value}", tool_name=tool_call.name)

        turn.tool_results.append(tr)
        self.on_tool_result(tool_call.name, tr.status.value, tr.output)
        return tr

    # ── Context Management ─────────────────────────────────────

    def _get_messages(self) -> list[dict]:
        """Retorna mensagens respeitando limites de contexto."""
        msgs = self.session.messages
        if len(msgs) > config.MAX_CONTEXT_MESSAGES:
            return [msgs[0]] + msgs[-(config.MAX_CONTEXT_MESSAGES - 1):]
        return msgs

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
        """Resume mensagens antigas via LLM (gpt-4.1-mini) para smart context."""
        if not messages:
            return ""

        try:
            # Monta texto da conversa para resumo (limita para nao estourar contexto)
            text_parts = []
            for msg in messages[:50]:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if isinstance(content, str) and content:
                    text_parts.append(f"[{role}] {content[:200]}")

            if not text_parts:
                return ""

            conversation_text = "\n".join(text_parts)

            response = self._client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Resuma a conversa abaixo em 3-5 frases curtas, mantendo "
                            "informacoes tecnicas importantes (arquivos, decisoes, erros encontrados)."
                        ),
                    },
                    {"role": "user", "content": conversation_text[:4000]},
                ],
                max_tokens=500,
                temperature=0.1,
            )
            return response.choices[0].message.content or ""
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
