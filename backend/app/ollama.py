"""Thin async client for the Ollama chat API.

Works against Ollama Cloud (``https://ollama.com``) or a local Ollama server
(``http://localhost:11434``) — only the base URL and API key change.

See https://docs.ollama.com/cloud for the API reference.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator

import httpx

from .config import Settings
from .runtime import runtime
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
        key = runtime.effective_api_key(self._settings)
        return {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

    def _record(
        self,
        endpoint: str,
        model: str,
        started: float,
        *,
        ok: bool,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        error: str | None = None,
    ) -> None:
        """Store a usage entry for the debug panel."""
        runtime.usage.record(
            endpoint=endpoint,
            model=model,
            ok=ok,
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            error=error,
        )

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
        if not runtime.is_configured(self._settings):
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
        model = payload["model"]
        started = time.perf_counter()

        try:
            response = await self._client.post(
                self._settings.chat_url, headers=self._headers(), json=payload
            )
            if response.status_code != httpx.codes.OK:
                raise OllamaError(response.status_code, _error_message(response))
            try:
                data = response.json()
            except ValueError as exc:
                raise OllamaError(502, "Ollama returned a non-JSON response.") from exc
        except httpx.RequestError as exc:
            error = f"Could not reach Ollama at {self._settings.chat_url}: {exc}"
            self._record("chat", model, started, ok=False, error=error)
            raise OllamaError(502, error) from exc
        except OllamaError as exc:
            self._record("chat", model, started, ok=False, error=exc.detail)
            raise

        message = data.get("message") or {}
        result = ChatResponse(
            model=data.get("model", model),
            message=ChatMessage(
                role=message.get("role", "assistant"),
                content=message.get("content", ""),
            ),
            done=bool(data.get("done", True)),
            prompt_tokens=data.get("prompt_eval_count"),
            completion_tokens=data.get("eval_count"),
        )
        self._record(
            "chat",
            result.model,
            started,
            ok=True,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
        )
        return result

    async def chat_stream(self, request: ChatRequest) -> AsyncIterator[str]:
        """Stream the assistant reply as Server-Sent Events.

        Yields ``data:`` frames of :class:`~app.schemas.StreamEvent` JSON.
        """
        self.ensure_configured()
        payload = self._build_payload(request, stream=True)
        model = payload["model"]
        started = time.perf_counter()
        ok = False
        error: str | None = None
        prompt_tokens: int | None = None
        completion_tokens: int | None = None

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
                        ok = True
                        prompt_tokens = chunk.get("prompt_eval_count")
                        completion_tokens = chunk.get("eval_count")
                        yield sse_frame(
                            {
                                "done": True,
                                "model": chunk.get("model", model),
                                "prompt_tokens": prompt_tokens,
                                "completion_tokens": completion_tokens,
                            }
                        )
                        return
        except httpx.RequestError as exc:
            error = f"Could not reach Ollama at {self._settings.chat_url}: {exc}"
            raise OllamaError(502, error) from exc
        except OllamaError as exc:
            error = exc.detail
            raise
        finally:
            if not ok and error is None:
                error = "stream ended before completion"
            self._record(
                "chat/stream",
                model,
                started,
                ok=ok,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                error=error,
            )
