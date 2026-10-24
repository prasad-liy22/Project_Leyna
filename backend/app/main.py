"""FastAPI application entry point.

Run locally with::

    uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import Settings, get_settings
try:
    from .conversations import Conversation, MemoryConfig, conversations, iso, window
except Exception:  # pragma: no cover
    from .db_conversations import Conversation, MemoryConfig, conversations, iso, window
from .debug import require_admin
from .debug import router as debug_router
from .ollama import OllamaClient, OllamaError, sse_frame
from .runtime import runtime
from .schemas import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ConversationCreated,
    ConversationDetail,
    MemoryInfo,
    OkResponse,
)

logger = logging.getLogger("leyna")
# Memory bookkeeping gets its own logger so it can be filtered in the console.
memory_logger = logging.getLogger("leyna.memory")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = get_settings()
    app.state.settings = settings
    app.state.ollama = OllamaClient(settings)
    conversations.configure(settings)
    runtime.attach_log_handler()

    if settings.is_configured:
        logger.info("Nimna ready — model=%s endpoint=%s", settings.ollama_model, settings.chat_url)
    else:
        logger.warning("OLLAMA_API_KEY is not set; /chat will return an error until you add it.")

    if settings.memory_enabled:
        logger.info(
            "Short-term memory: on — budget≈%d tokens, ≤%d messages, "
            "≤%d conversations, ttl=%g min",
            settings.memory_token_budget,
            settings.memory_max_messages,
            settings.memory_max_conversations,
            settings.memory_ttl_minutes,
        )
    else:
        logger.info("Short-term memory: off — every request is stateless.")

    yield

    runtime.detach_log_handler()
    await app.state.ollama.aclose()


app = FastAPI(
    title="Nimna — Personal Assistant API",
    description="A small chat API backed by Ollama Cloud.",
    version=__version__,
    lifespan=lifespan,
)

# Allow the browser-based frontend to call this API from another origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Debug routes are opt-in via DEBUG_ENABLED, and can be locked down with ADMIN_TOKEN.
if get_settings().debug_enabled:
    app.include_router(debug_router, dependencies=[Depends(require_admin)])


def _to_http_error(exc: OllamaError) -> HTTPException:
    """Map an upstream error onto a valid HTTP status code."""
    status = exc.status_code if 400 <= exc.status_code < 600 else 502
    return HTTPException(status_code=status, detail=exc.detail)


def _ollama(request: Request) -> OllamaClient:
    return request.app.state.ollama


# --------------------------------------------------------------------------- #
# Short-term memory
# --------------------------------------------------------------------------- #
@dataclass
class _Prepared:
    """The transcript to send upstream, plus what to remember afterwards."""

    messages: list[ChatMessage]
    conversation_id: str | None = None
    memory: MemoryInfo | None = None
    pending: list[ChatMessage] = field(default_factory=list)
    seed: bool = False


def _latest_user_message(messages: list[ChatMessage]) -> ChatMessage | None:
    """The trailing message, when it is a user turn."""
    if messages and messages[-1].role == "user":
        return messages[-1]
    return None


def _prepare(payload: ChatRequest) -> _Prepared:
    """Resolve server-side memory into the messages actually sent upstream.

    A request is stateless unless it carries a ``conversation_id``. With one the
    server owns the transcript: only the trailing user message is read from the
    request, and the stored history supplies everything before it.
    """
    config: MemoryConfig = conversations.config
    if not config.enabled:
        return _Prepared(messages=list(payload.messages))

    conversation_id = (payload.conversation_id or "").strip()
    if not conversation_id:
        return _Prepared(messages=list(payload.messages))

    history = conversations.load(conversation_id)
    new_turn = _latest_user_message(payload.messages)

    if history is None:
        # Unknown or expired. Adopt whatever the client sent as the history so a
        # restarted (or freshly scaled) server does not lose the thread.
        transcript = list(payload.messages)
        pending = list(payload.messages)
        seed = True
    else:
        transcript = [*history, *([new_turn] if new_turn is not None else [])]
        pending = [new_turn] if new_turn is not None else []
        seed = False
        if len(payload.messages) > 1 and new_turn is not None:
            memory_logger.debug(
                "conversation %s is server-side; ignoring %d client-supplied "
                "history message(s)",
                conversation_id,
                len(payload.messages) - 1,
            )

    result = window(
        transcript,
        token_budget=config.token_budget,
        keep_first=config.keep_first,
    )
    if result.trimmed:
        memory_logger.debug(
            "conversation %s trimmed %d -> %d message(s) (~%d tokens)",
            conversation_id,
            result.stored_messages,
            len(result.messages),
            result.estimated_tokens,
        )

    return _Prepared(
        messages=result.messages,
        conversation_id=conversation_id,
        memory=MemoryInfo(
            enabled=True,
            stored_messages=result.stored_messages,
            window_messages=len(result.messages),
            estimated_tokens=result.estimated_tokens,
            trimmed=result.trimmed,
            keep_first=config.keep_first,
        ),
        pending=pending,
        seed=seed,
    )


def _remember(prepared: _Prepared, reply: str) -> None:
    """Persist a completed exchange — and only a completed one."""
    if not prepared.conversation_id or not prepared.pending:
        return
    if prepared.seed:
        conversations.ensure(prepared.conversation_id)
        memory_logger.info(
            "seeded conversation %s from the client (%d message(s))",
            prepared.conversation_id,
            len(prepared.pending),
        )
    conversations.append(
        prepared.conversation_id,
        [*prepared.pending, ChatMessage(role="assistant", content=reply)],
    )


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.get("/health", tags=["meta"])
async def health(request: Request) -> dict:
    """Liveness probe plus a hint about configuration state."""
    settings: Settings = request.app.state.settings
    return {
        "status": "ok",
        "version": __version__,
        "model": settings.ollama_model,
        "configured": runtime.is_configured(settings),
        "memory_enabled": conversations.enabled,
    }


@app.post("/chat", response_model=ChatResponse, tags=["chat"])
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    """Return a single, complete assistant reply."""
    prepared = _prepare(payload)
    upstream = payload.model_copy(update={"messages": prepared.messages})
    try:
        result = await _ollama(request).chat(upstream)
    except OllamaError as exc:
        raise _to_http_error(exc) from exc

    _remember(prepared, result.message.content)
    result.conversation_id = prepared.conversation_id
    result.memory = prepared.memory
    return result


@app.post("/chat/stream", tags=["chat"])
async def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
    """Stream the assistant reply token-by-token as Server-Sent Events.

    Each event is ``data: {"delta": "..."}``; the final event is
    ``data: {"done": true, ...}``.
    """
    client = _ollama(request)
    try:
        client.ensure_configured()
    except OllamaError as exc:
        raise _to_http_error(exc) from exc

    prepared = _prepare(payload)
    upstream = payload.model_copy(update={"messages": prepared.messages})

    extra: dict = {}
    if prepared.conversation_id:
        extra["conversation_id"] = prepared.conversation_id
    if prepared.memory is not None:
        extra["memory"] = prepared.memory.model_dump()

    async def event_source() -> AsyncIterator[str]:
        chunks: list[str] = []
        try:
            async for frame in client.chat_stream(
                upstream,
                done_extra=extra or None,
                collected=chunks,
            ):
                yield frame
        except OllamaError as exc:
            # Headers are already sent, so surface the failure as an SSE event.
            # Nothing is remembered: only completed exchanges are persisted.
            yield sse_frame({"done": True, "error": exc.detail})
            return
        _remember(prepared, "".join(chunks))

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _detail(conversation: Conversation) -> ConversationDetail:
    return ConversationDetail(
        conversation_id=conversation.id,
        created_at=iso(conversation.created_at),
        updated_at=iso(conversation.updated_at),
        message_count=len(conversation.messages),
        messages=conversation.messages,
    )


@app.post("/conversations", response_model=ConversationCreated, tags=["memory"])
async def create_conversation() -> ConversationCreated:
    """Start a new server-side conversation and return its id."""
    if not conversations.enabled:
        raise HTTPException(
            status_code=409,
            detail="Short-term memory is disabled (MEMORY_ENABLED=false).",
        )
    conversation = conversations.create()
    return ConversationCreated(
        conversation_id=conversation.id,
        created_at=iso(conversation.created_at),
    )


@app.get("/conversations/{conversation_id}", response_model=ConversationDetail, tags=["memory"])
async def get_conversation(conversation_id: str) -> ConversationDetail:
    """The stored transcript for a conversation."""
    conversation = conversations.get(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail=f"No conversation {conversation_id!r}.")
    return _detail(conversation)


@app.delete("/conversations/{conversation_id}", response_model=OkResponse, tags=["memory"])
async def delete_conversation(conversation_id: str) -> OkResponse:
    """Forget a conversation."""
    if not conversations.delete(conversation_id):
        raise HTTPException(status_code=404, detail=f"No conversation {conversation_id!r}.")
    return OkResponse()


# Serve the built Tailwind web UI at the root. Mounted last so the API routes
# defined above always win; anything unmatched falls through to the static app.
_web_dir = Path(get_settings().web_dir)
if _web_dir.is_dir():
    app.mount("/", StaticFiles(directory=_web_dir, html=True), name="web")
else:
    logger.warning(
        "Web UI not found at %s — build it with 'cd web && npm run build'.",
        _web_dir,
    )
