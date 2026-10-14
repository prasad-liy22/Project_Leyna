"""Tests for the chat API.

The upstream Ollama API is mocked with ``httpx.MockTransport`` so the suite
runs offline and without an API key.
"""

import json
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app
from app.ollama import OllamaClient


def _non_stream_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "gemma4:31b-cloud",
            "message": {"role": "assistant", "content": "Hello, I am Leyna."},
            "done": True,
            "prompt_eval_count": 12,
            "eval_count": 7,
        },
    )


def _stream_response() -> httpx.Response:
    lines = [
        json.dumps({"model": "gemma4:31b-cloud", "message": {"content": "Hel"}, "done": False}),
        json.dumps({"model": "gemma4:31b-cloud", "message": {"content": "lo"}, "done": False}),
        json.dumps({"model": "gemma4:31b-cloud", "message": {"content": ""}, "done": True, "eval_count": 2}),
    ]
    body = "\n".join(lines) + "\n"
    return httpx.Response(200, content=body, headers={"content-type": "application/x-ndjson"})


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """App wired to a mock transport and a fake API key."""
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    get_settings.cache_clear()
    settings = Settings(ollama_api_key="test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-key"
        assert request.url.path == "/api/chat"
        body = json.loads(request.content)
        return _stream_response() if body.get("stream") else _non_stream_response()

    with TestClient(app) as test_client:
        app.state.ollama = OllamaClient(
            settings, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )
        yield test_client

    get_settings.cache_clear()


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_chat_returns_message(client: TestClient) -> None:
    response = client.post("/chat", json={"messages": [{"role": "user", "content": "Hi"}]})
    assert response.status_code == 200
    body = response.json()
    assert body["message"]["role"] == "assistant"
    assert body["message"]["content"] == "Hello, I am Leyna."
    assert body["completion_tokens"] == 7


def test_chat_validates_empty_messages(client: TestClient) -> None:
    response = client.post("/chat", json={"messages": []})
    assert response.status_code == 422


def test_chat_stream_sends_deltas_then_done(client: TestClient) -> None:
    with client.stream(
        "POST", "/chat/stream", json={"messages": [{"role": "user", "content": "Hi"}]}
    ) as response:
        assert response.status_code == 200
        frames = [line for line in response.iter_lines() if line.startswith("data:")]

    payloads = [json.loads(frame.removeprefix("data: ").strip()) for frame in frames]
    assert "".join(p.get("delta", "") for p in payloads) == "Hello"
    assert payloads[-1]["done"] is True


def test_chat_without_api_key_returns_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    get_settings.cache_clear()
    with TestClient(app) as test_client:
        test_client.app.state.ollama = OllamaClient(Settings(ollama_api_key=""))
        response = test_client.post("/chat", json={"messages": [{"role": "user", "content": "Hi"}]})
    get_settings.cache_clear()

    assert response.status_code == 500
    assert "OLLAMA_API_KEY" in response.json()["detail"]
