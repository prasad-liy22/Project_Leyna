"""Request and response models for the chat API."""

from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["system", "user", "assistant"]


class ChatMessage(BaseModel):
    """A single message in a conversation."""

    role: Role
    content: str


class MemoryInfo(BaseModel):
    """How the server chose the transcript it sent to the model.

    Present only when a request opted into server-side memory by sending a
    ``conversation_id``.
    """

    enabled: bool = False
    stored_messages: int = Field(
        default=0, description="Messages held for the conversation before trimming."
    )
    window_messages: int = Field(
        default=0, description="Messages actually sent to the model."
    )
    estimated_tokens: int = Field(
        default=0, description="Approximate size of the transcript sent."
    )
    trimmed: bool = Field(
        default=False, description="Whether older messages were dropped."
    )
    keep_first: bool = Field(
        default=False,
        description="Whether the opening user message was pinned to the front.",
    )


class ChatRequest(BaseModel):
    """Body for ``POST /chat`` and ``POST /chat/stream``."""

    messages: list[ChatMessage] = Field(
        ...,
        min_length=1,
        description="Conversation so far. Include at least one message.",
    )
    conversation_id: str | None = Field(
        default=None,
        description="Server-side conversation to continue. When omitted the "
        "request is stateless and 'messages' is used verbatim. When set, the "
        "server owns the transcript and only the trailing user message is read "
        "from 'messages'.",
    )
    model: str | None = Field(
        default=None,
        description="Override the configured model for this request.",
    )
    temperature: float | None = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description="Sampling temperature. Uses the model default when omitted.",
    )
    system: str | None = Field(
        default=None,
        description="Override the default system prompt for this request.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "messages": [
                        {"role": "user", "content": "What should I have for dinner?"}
                    ]
                }
            ]
        }
    }


class ChatResponse(BaseModel):
    """Non-streaming reply from the assistant."""

    model: str
    message: ChatMessage
    done: bool = True
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    conversation_id: str | None = Field(
        default=None, description="Set when the request used server-side memory."
    )
    memory: MemoryInfo | None = Field(
        default=None, description="Transcript windowing details, when memory was used."
    )


class StreamEvent(BaseModel):
    """Shape of each JSON object sent over ``/chat/stream`` (SSE)."""

    delta: str | None = None
    done: bool = False
    model: str | None = None
    error: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    conversation_id: str | None = None
    memory: MemoryInfo | None = None


class OkResponse(BaseModel):
    """Generic acknowledgement."""

    ok: bool = True


class ConversationCreated(BaseModel):
    """Returned by ``POST /conversations``."""

    conversation_id: str
    created_at: str


class ConversationDetail(BaseModel):
    """Returned by ``GET /conversations/{id}``."""

    conversation_id: str
    created_at: str
    updated_at: str
    message_count: int
    messages: list[ChatMessage]


class MemorySettings(BaseModel):
    """The active memory configuration."""

    enabled: bool
    token_budget: int
    max_messages: int
    max_conversations: int
    ttl_minutes: float
    keep_first: bool


class ConversationSummary(BaseModel):
    """One row in the debug memory report."""

    conversation_id: str
    messages: int
    created_at: str
    updated_at: str


class MemoryReport(BaseModel):
    """Returned by ``GET /debug/memory``."""

    settings: MemorySettings
    conversations: int
    messages: int
    items: list[ConversationSummary]
