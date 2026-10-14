"""FastAPI application entry point.

Run locally with::

    uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from . import __version__
from .config import Settings, get_settings
from .ollama import OllamaClient, OllamaError, sse_frame
from .schemas import ChatRequest, ChatResponse

logger = logging.getLogger("leyna")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = get_settings()
    app.state.settings = settings
    app.state.ollama = OllamaClient(settings)

    if settings.is_configured:
        logger.info("Leyna ready — model=%s endpoint=%s", settings.ollama_model, settings.chat_url)
    else:
        logger.warning("OLLAMA_API_KEY is not set; /chat will return an error until you add it.")

    yield

    await app.state.ollama.aclose()


app = FastAPI(
    title="Leyna — Personal Assistant API",
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


def _to_http_error(exc: OllamaError) -> HTTPException:
    """Map an upstream error onto a valid HTTP status code."""
    status = exc.status_code if 400 <= exc.status_code < 600 else 502
    return HTTPException(status_code=status, detail=exc.detail)


def _ollama(request: Request) -> OllamaClient:
    return request.app.state.ollama


@app.get("/health", tags=["meta"])
async def health(request: Request) -> dict:
    """Liveness probe plus a hint about configuration state."""
    settings: Settings = request.app.state.settings
    return {
        "status": "ok",
        "version": __version__,
        "model": settings.ollama_model,
        "configured": settings.is_configured,
    }


@app.post("/chat", response_model=ChatResponse, tags=["chat"])
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    """Return a single, complete assistant reply."""
    try:
        return await _ollama(request).chat(payload)
    except OllamaError as exc:
        raise _to_http_error(exc) from exc


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

    async def event_source() -> AsyncIterator[str]:
        try:
            async for frame in client.chat_stream(payload):
                yield frame
        except OllamaError as exc:
            # Headers are already sent, so surface the failure as an SSE event.
            yield sse_frame({"done": True, "error": exc.detail})

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
