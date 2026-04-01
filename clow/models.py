"""Modelos de dados do Clow."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from enum import Enum
import time
import uuid


class ToolResultStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"
    DENIED = "denied"


class PermissionLevel(Enum):
    READ_ONLY = "read-only"
    WORKSPACE_WRITE = "workspace-write"
    FULL_ACCESS = "full-access"


@dataclass
class ToolCall:
    """Representa uma chamada de ferramenta do modelo."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    """Resultado da execução de uma ferramenta."""
    tool_call_id: str
    status: ToolResultStatus
    output: str
    truncated: bool = False

    def to_message(self) -> dict:
        content = self.output
        if self.status == ToolResultStatus.ERROR:
            content = f"[ERROR] {self.output}"
        elif self.status == ToolResultStatus.DENIED:
            content = f"[DENIED] {self.output}"
        return {
            "role": "tool",
            "tool_call_id": self.tool_call_id,
            "content": content,
        }


@dataclass
class Turn:
    """Um turno de conversa (pergunta + resposta + tool calls)."""
    user_message: str
    assistant_message: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    timestamp: float = field(default_factory=time.time)


@dataclass
class Session:
    """Uma sessão de conversa completa."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    messages: list[dict] = field(default_factory=list)
    turns: list[Turn] = field(default_factory=list)
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    created_at: float = field(default_factory=time.time)
    cwd: str = ""
    model: str = ""

    def add_tokens(self, tokens_in: int, tokens_out: int) -> None:
        self.total_tokens_in += tokens_in
        self.total_tokens_out += tokens_out
