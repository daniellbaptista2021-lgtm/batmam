"""Client DeepSeek via OpenAI SDK com suporte a tool use / function calling."""

from __future__ import annotations
from typing import Any
from openai import OpenAI
from . import config


_client: OpenAI | None = None


def get_client() -> OpenAI:
    """Retorna singleton do client DeepSeek."""
    global _client
    if _client is None:
        if not config.DEEPSEEK_API_KEY:
            raise RuntimeError(
                "DEEPSEEK_API_KEY nao configurada. "
                "Defina no .env ou exporte a variavel."
            )
        _client = OpenAI(**config.get_deepseek_client_kwargs())
    return _client


def chat_completion(
    messages: list[dict],
    tools: list[dict] | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    stream: bool = False,
) -> dict[str, Any]:
    """Faz uma chamada ao modelo com suporte a tools.

    Retorna dict com keys: message, usage, finish_reason
    """
    client = get_client()
    model = model or config.CLOW_MODEL
    temperature = temperature if temperature is not None else config.TEMPERATURE
    max_tokens = max_tokens or config.MAX_TOKENS

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    if stream:
        return _stream_completion(kwargs)

    response = client.chat.completions.create(**kwargs)
    choice = response.choices[0]
    usage = response.usage

    return {
        "message": choice.message,
        "usage": {
            "prompt_tokens": usage.prompt_tokens if usage else 0,
            "completion_tokens": usage.completion_tokens if usage else 0,
        },
        "finish_reason": choice.finish_reason,
    }


def _stream_completion(kwargs: dict) -> dict[str, Any]:
    """Streaming completion - coleta chunks e retorna resultado completo."""
    client = get_client()
    kwargs["stream"] = True

    collected_content = []
    collected_tool_calls: dict[int, dict] = {}
    finish_reason = None
    usage_data = {"prompt_tokens": 0, "completion_tokens": 0}

    stream = client.chat.completions.create(**kwargs)

    for chunk in stream:
        if not chunk.choices:
            if hasattr(chunk, "usage") and chunk.usage:
                usage_data["prompt_tokens"] = chunk.usage.prompt_tokens or 0
                usage_data["completion_tokens"] = chunk.usage.completion_tokens or 0
            continue

        delta = chunk.choices[0].delta
        if chunk.choices[0].finish_reason:
            finish_reason = chunk.choices[0].finish_reason

        if delta.content:
            collected_content.append(delta.content)

        if delta.tool_calls:
            for tc in delta.tool_calls:
                idx = tc.index
                if idx not in collected_tool_calls:
                    collected_tool_calls[idx] = {
                        "id": tc.id or "",
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    }
                if tc.id:
                    collected_tool_calls[idx]["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        collected_tool_calls[idx]["function"]["name"] = tc.function.name
                    if tc.function.arguments:
                        collected_tool_calls[idx]["function"]["arguments"] += tc.function.arguments

    from types import SimpleNamespace

    tool_calls_list = None
    if collected_tool_calls:
        tool_calls_list = []
        for idx in sorted(collected_tool_calls.keys()):
            tc = collected_tool_calls[idx]
            tool_calls_list.append(SimpleNamespace(
                id=tc["id"],
                type="function",
                function=SimpleNamespace(
                    name=tc["function"]["name"],
                    arguments=tc["function"]["arguments"],
                ),
            ))

    message = SimpleNamespace(
        content="".join(collected_content) if collected_content else None,
        tool_calls=tool_calls_list,
        role="assistant",
    )

    return {
        "message": message,
        "usage": usage_data,
        "finish_reason": finish_reason or "stop",
    }
