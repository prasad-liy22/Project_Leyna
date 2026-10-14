"""Request and response models for the chat API."""

from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["system", "user", "assistant"]


class ChatMessage(BaseModel):
    """A single message in a conversation."""

    role: Role
    content: str


class ChatRequest(BaseModel):
    """Body for ``POST /chat`` and ``POST /chat/stream``."""

    messages: list[ChatMessage] = Field(
        ...,
        min_length=1,
        description="Conversation so far. Include at least one message.",
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


class StreamEvent(BaseModel):
    """Shape of each JSON object sent over ``/chat/stream`` (SSE)."""

    delta: str | None = None
    done: bool = False
    model: str | None = None
    error: str | None = None
