"""Pydantic models for API documentation (FastAPI auto-generates Swagger from these)."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ── Health / Status ────────────────────────────────────────────────

class HealthResponse(BaseModel):
    """Response from GET /health."""

    status: str = Field(example="healthy")
    version: str = Field(example="0.2.0")
    uptime_info: str = Field(example="2026-04-03 12:00:00 UTC")
    components: dict = Field(description="Status of subsystems (agent, database, ...)")
    recent_actions: list = Field(default_factory=list, description="Last tracked actions")


class StatusResponse(BaseModel):
    """Response from GET /api/v1/status."""

    version: str = Field(example="0.2.0")
    status: str = Field(example="ok")
    components: dict = Field(default_factory=dict)
    recent_actions: list = Field(default_factory=list)


# ── Chat ───────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    """Body for POST /api/v1/chat."""

    content: str = Field(description="Message content", example="Crie uma landing page")
    conversation_id: str = Field(default="", description="Conversation ID for context continuity")
    session_id: str = Field(default="", description="Session tracking ID (server generates one if empty)")
    model: str = Field(default="deepseek-chat", description="Model selector: deepseek-chat or deepseek-reasoner")
    file_data: Optional[dict] = Field(default=None, description="Attached file data from /api/v1/upload")


class FileInfo(BaseModel):
    """Generated file metadata returned inside ChatResponse."""

    type: str = Field(description="File type: landing_page, app, xlsx, docx, pptx")
    name: str = Field(example="site_pizzaria.html")
    url: str = Field(example="/static/files/site_pizzaria.html")
    size: str = Field(example="12.3 KB")


class ChatResponse(BaseModel):
    """Response from POST /api/v1/chat."""

    session_id: str = Field(description="Session ID for follow-up requests")
    response: str = Field(description="Assistant reply (Markdown)")
    tools: list = Field(default_factory=list, description="Tool calls executed during the turn")
    file: Optional[FileInfo] = Field(default=None, description="Generated file, if any")


# ── Conversations ──────────────────────────────────────────────────

class ConversationResponse(BaseModel):
    """Single conversation item from GET /api/v1/conversations."""

    id: str
    title: str
    created_at: float
    updated_at: float


class ConversationListResponse(BaseModel):
    """Response from GET /api/v1/conversations."""

    conversations: list[ConversationResponse]


class MessageResponse(BaseModel):
    """Single message inside a conversation."""

    role: str = Field(description="user or assistant")
    content: str
    timestamp: float


class MessageListResponse(BaseModel):
    """Response from GET /api/v1/conversations/{conv_id}/messages."""

    messages: list[MessageResponse]


# ── User / Auth ────────────────────────────────────────────────────

class UserResponse(BaseModel):
    """Response from GET /api/v1/me."""

    email: str = Field(example="user@example.com")
    user_id: str = Field(example="abc123")
    is_admin: bool = Field(default=False)
    plan: str = Field(example="free", description="Current plan: free, basic, pro, unlimited")
    available_models: list[str] = Field(default_factory=lambda: ["deepseek-chat"])


# ── Usage ──────────────────────────────────────────────────────────

class UsageDetail(BaseModel):
    """Raw usage counters for the current day."""

    total_tokens: int = Field(default=0, example=12400)
    requests: int = Field(default=0, example=23)
    total_cost: float = Field(default=0.0, example=0.0031)


class UsageResponse(BaseModel):
    """Response from GET /api/v1/usage."""

    usage: UsageDetail
    plan: str = Field(example="free")
    plan_label: str = Field(example="Free")
    daily_limit: int = Field(example=50000)


# ── Upload ─────────────────────────────────────────────────────────

class UploadResponse(BaseModel):
    """Response from POST /api/v1/upload."""

    ok: bool = Field(default=True)
    file_name: str = Field(example="relatorio.pdf")
    file_url: str = Field(example="/static/uploads/abc123/1680000000_relatorio.pdf")
    file_size: str = Field(example="1.2 MB")
    file_ext: str = Field(example=".pdf")
    type: str = Field(
        description="Detected file type: image, pdf, spreadsheet, document, code, audio, file"
    )
    # Fields present for specific types
    media_type: Optional[str] = Field(default=None, description="MIME type (images, PDFs)")
    base64: Optional[str] = Field(default=None, description="Base64 payload (images, PDFs)")
    extracted_text: Optional[str] = Field(default=None, description="Extracted text (docs, sheets, code)")
    transcription: Optional[str] = Field(default=None, description="Audio transcription text")
    has_transcription: Optional[bool] = Field(default=None, description="Whether audio transcription succeeded")
    language: Optional[str] = Field(default=None, description="Detected programming language (code files)")
    pages: Optional[int] = Field(default=None, description="Page count (PDFs)")
    rows: Optional[int] = Field(default=None, description="Row count (spreadsheets)")
    words: Optional[int] = Field(default=None, description="Word count (documents)")
    warning: Optional[str] = Field(default=None, description="Processing warnings")


# ── Errors ─────────────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    """Standard error envelope."""

    error: str = Field(description="Human-readable error message")


# ── WebSocket protocol (documentation reference, not used by endpoints) ──

class WSClientMessage(BaseModel):
    """Client-to-server WebSocket message."""

    type: str = Field(description="Message type: 'message'", example="message")
    content: str = Field(default="", description="User message text")
    model: str = Field(default="deepseek-chat", description="Model selector")
    conversation_id: str = Field(default="", description="Conversation ID")
    file_data: Optional[dict] = Field(default=None, description="Attached file data")


class WSServerEvent(BaseModel):
    """Server-to-client WebSocket event (union of all event shapes)."""

    type: str = Field(
        description=(
            "Event type: text_delta, text_done, tool_call, tool_result, "
            "error, thinking_start, thinking_end, turn_complete"
        )
    )
    content: Optional[str] = Field(default=None, description="Text content (text_delta, error)")
    name: Optional[str] = Field(default=None, description="Tool name (tool_call, tool_result)")
    args: Optional[dict] = Field(default=None, description="Tool arguments (tool_call)")
    status: Optional[str] = Field(default=None, description="Execution status (tool_result)")
    output: Optional[str] = Field(default=None, description="Truncated output (tool_result, max 2000 chars)")
