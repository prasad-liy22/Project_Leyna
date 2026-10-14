"""Thin async client for the Ollama chat API.

Works against Ollama Cloud (``https://ollama.com``) or a local Ollama server
(``http://localhost:11434``) — only the base URL and API key change.

See https://docs.ollama.com/cloud for the API reference.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from .config import Settings
from .schemas import ChatMessage, ChatRequest, ChatResponse


class OllamaError(RuntimeError):
    """Raised when the upstream Ollama API returns an error."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def _error_message(response: httpx.Response) -> str:
    """Best-effort extraction of a human-readable error from a response."""
    try:
        body = response.json()
    except ValueError:
        return response.text.strip() or f"Upstream returned HTTP {response.status_code}"
    if isinstance(body, dict):
        for key in ("error", "message", "detail"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value
    return json.dumps(body)


def sse_frame(payload: dict) -> str:
    """Encode a dict as a single Server-Sent Events ``data:`` frame."""
    return f"data: {json.dumps(payload)}\n\n"


class OllamaClient:
    """Minimal wrapper around ``POST /api/chat``.

    A single instance is shared for the lifetime of the app so that HTTP
    connections are pooled and reused.
    """

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client or httpx.AsyncClient(timeout=settings.request_timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- helpers -------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._settings.ollama_api_key}",
            "Content-Type": "application/json",
        }

    def _build_payload(self, request: ChatRequest, *, stream: bool) -> dict:
        system_prompt = request.system if request.system is not None else self._settings.system_prompt
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.extend({"role": m.role, "content": m.content} for m in request.messages)

        payload: dict = {
            "model": request.model or self._settings.ollama_model,
            "messages": messages,
            "stream": stream,
        }
        if request.temperature is not None:
            payload["options"] = {"temperature": request.temperature}
        return payload

    def ensure_configured(self) -> None:
        """Raise a clear error when no API key is available."""
        if not self._settings.is_configured:
            raise OllamaError(
                500,
                "OLLAMA_API_KEY is not set. Copy .env.example to .env and add your "
                "key from https://ollama.com/settings/keys.",
            )

    # -- public API ----------------------------------------------------------
    async def chat(self, request: ChatRequest) -> ChatResponse:
        """Send a conversation and return the full assistant reply."""
        self.ensure_configured()
        payload = self._build_payload(request, stream=False)

        try:
            response = await self._client.post(
                self._settings.chat_url, headers=self._headers(), json=payload
            )
        except httpx.RequestError as exc:
            raise OllamaError(502, f"Could not reach Ollama at {self._settings.chat_url}: {exc}") from exc

        if response.status_code != httpx.codes.OK:
            raise OllamaError(response.status_code, _error_message(response))

        data = response.json()
        message = data.get("message") or {}
        return ChatResponse(
            model=data.get("model", payload["model"]),
            message=ChatMessage(
                role=message.get("role", "assistant"),
                content=message.get("content", ""),
            ),
            done=bool(data.get("done", True)),
            prompt_tokens=data.get("prompt_eval_count"),
            completion_tokens=data.get("eval_count"),
        )

    async def chat_stream(self, request: ChatRequest) -> AsyncIterator[str]:
        """Stream the assistant reply as Server-Sent Events.

        Yields ``data:`` frames of :class:`~app.schemas.StreamEvent` JSON.
        """
        self.ensure_configured()
        payload = self._build_payload(request, stream=True)

        try:
            async with self._client.stream(
                "POST", self._settings.chat_url, headers=self._headers(), json=payload
            ) as response:
                if response.status_code != httpx.codes.OK:
                    await response.aread()
                    raise OllamaError(response.status_code, _error_message(response))

                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    delta = (chunk.get("message") or {}).get("content")
                    if delta:
                        yield sse_frame({"delta": delta, "done": False})

                    if chunk.get("done"):
                        yield sse_frame(
                            {
                                "done": True,
                                "model": chunk.get("model", payload["model"]),
                                "completion_tokens": chunk.get("eval_count"),
                            }
                        )
                        return
        except httpx.RequestError as exc:
            raise OllamaError(502, f"Could not reach Ollama at {self._settings.chat_url}: {exc}") from exc
