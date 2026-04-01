"""Agent Loop — o coração do Batmam.

Orquestra o ciclo: prompt → modelo → tool calls → execução → resultado → modelo...
Suporta streaming em tempo real e sub-agents.
"""

from __future__ import annotations
import json
import os
import sys
from typing import Any, Callable

from openai import OpenAI
from .models import Session, ToolCall, ToolResult, ToolResultStatus, Turn
from .tools.base import ToolRegistry, create_default_registry
from .permissions import needs_confirmation, format_confirmation_prompt
from .prompts import get_system_prompt
from .session import save_session
from .memory import load_memory_context
from .context import load_project_context
from .hooks import HookRunner
from .mcp import MCPManager
from .plugins import PluginManager
from . import config


class Agent:
    """Agente principal do Batmam."""

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
        # Configura agent_tool com referência ao agente pai
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
            raise RuntimeError("OPENAI_API_KEY não configurada.")
        self._client = OpenAI(api_key=config.OPENAI_API_KEY)

        # Hooks
        self.hooks = HookRunner()

        # MCP - carrega servidores e registra tools
        self.mcp = MCPManager()
        if not is_subagent:
            self.mcp.load_from_settings()
            mcp_tools = self.mcp.register_tools(self.registry)

        # Plugins - carrega e registra tools/hooks
        self.plugins = PluginManager()
        if not is_subagent:
            self.plugins.load_all(self.registry, self.hooks)

        # Hook on_start
        if not is_subagent:
            self.hooks.run_hooks("on_start", {"cwd": self.cwd}, self.cwd)

        # Sessão
        self.session = session or Session(cwd=self.cwd, model=self.model)
        if not self.session.messages:
            self._build_system_messages()

    def _build_system_messages(self) -> None:
        """Constrói system prompt com contexto de projeto e memória."""
        system_parts = [get_system_prompt(self.cwd)]

        # BATMAM.md do projeto
        project_ctx = load_project_context(self.cwd)
        if project_ctx:
            system_parts.append(f"\n# Contexto do Projeto (BATMAM.md)\n{project_ctx}")

        # Memória persistente
        if not self.is_subagent:
            memory_ctx = load_memory_context()
            if memory_ctx:
                system_parts.append(f"\n# Memória\n{memory_ctx}")

        self.session.messages = [
            {"role": "system", "content": "\n\n".join(system_parts)}
        ]

    def run_turn(self, user_message: str) -> str:
        """Executa um turno completo com streaming."""

        # Hook pre_turn
        pre_results = self.hooks.run_hooks(
            "pre_turn", {"user_message": user_message}, self.cwd
        )
        for hr in pre_results:
            if hr.blocked:
                return f"[Hook bloqueou execução] {hr.feedback}"

        self.session.messages.append({"role": "user", "content": user_message})

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

                # Monta mensagem do assistente para histórico
                assistant_msg = self._build_assistant_message(text_content, tool_calls_data)
                self.session.messages.append(assistant_msg)

                # Se não tem tool calls, acabou
                if not tool_calls_data:
                    break

                # Executa tool calls
                tool_results = self._execute_tool_calls(tool_calls_data, turn)

                # Adiciona resultados ao histórico
                for tr in tool_results:
                    self.session.messages.append(tr.to_message())

        except Exception as e:
            # Hook on_error
            self.hooks.run_hooks("on_error", {"error": str(e)}, self.cwd)
            raise

        # Finaliza turno
        turn.assistant_message = "\n".join(full_response_text)
        self.session.add_tokens(turn.tokens_in, turn.tokens_out)
        self.session.turns.append(turn)

        # Hook post_turn
        self.hooks.run_hooks(
            "post_turn",
            {"user_message": user_message, "assistant_message": turn.assistant_message},
            self.cwd,
        )

        # Auto-save (não salva sub-agents)
        if not self.is_subagent:
            save_session(self.session)
            self._maybe_compact()

        return turn.assistant_message

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

    def _execute_tool_calls(self, tool_calls_data: list[dict], turn: Turn) -> list[ToolResult]:
        """Executa tool calls com hooks pre/post."""
        results = []

        for tc_data in tool_calls_data:
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
            blocked = False
            hook_feedback = ""
            for hr in pre_results:
                if hr.feedback:
                    hook_feedback += hr.feedback + "\n"
                if hr.blocked:
                    blocked = True
                    break

            if blocked:
                tr = ToolResult(
                    tool_call_id=tool_call.id,
                    status=ToolResultStatus.DENIED,
                    output=f"Hook bloqueou: {hook_feedback.strip()}",
                )
                results.append(tr)
                turn.tool_results.append(tr)
                self.on_tool_result(tool_call.name, "denied", tr.output)
                continue

            self.on_tool_call(tool_call.name, tool_call.arguments)

            # Busca ferramenta
            tool = self.registry.get(tool_call.name)
            if tool is None:
                tr = ToolResult(
                    tool_call_id=tool_call.id,
                    status=ToolResultStatus.ERROR,
                    output=f"Ferramenta '{tool_call.name}' não encontrada.",
                )
                results.append(tr)
                turn.tool_results.append(tr)
                self.on_tool_result(tool_call.name, "error", tr.output)
                continue

            # Permissão
            if not self.auto_approve and needs_confirmation(tool_call.name, tool_call.arguments):
                prompt = format_confirmation_prompt(tool_call.name, tool_call.arguments)
                if not self.ask_confirmation(prompt):
                    tr = ToolResult(
                        tool_call_id=tool_call.id,
                        status=ToolResultStatus.DENIED,
                        output="Usuário negou a execução desta ferramenta.",
                    )
                    results.append(tr)
                    turn.tool_results.append(tr)
                    self.on_tool_result(tool_call.name, "denied", tr.output)
                    continue

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

            results.append(tr)
            turn.tool_results.append(tr)
            self.on_tool_result(tool_call.name, tr.status.value, tr.output)

        return results

    def _get_messages(self) -> list[dict]:
        """Retorna mensagens respeitando limites de contexto."""
        msgs = self.session.messages
        if len(msgs) > config.MAX_CONTEXT_MESSAGES:
            return [msgs[0]] + msgs[-(config.MAX_CONTEXT_MESSAGES - 1):]
        return msgs

    def _maybe_compact(self) -> None:
        """Compacta contexto se muito grande."""
        if len(self.session.messages) > config.MAX_CONTEXT_MESSAGES + 50:
            system = self.session.messages[0]
            recent = self.session.messages[-(config.MAX_CONTEXT_MESSAGES):]
            self.session.messages = [system] + recent

    def _build_assistant_message(self, text: str, tool_calls_data: list[dict]) -> dict:
        """Constrói dict de mensagem do assistente."""
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
