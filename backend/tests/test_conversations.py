"""Tests for short-term memory (windowing, the store, and the HTTP surface).

The upstream Ollama API is mocked with ``httpx.MockTransport`` so the suite runs
offline and without an API key.
"""

import json
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.conversations import (
    ConversationStore,
    MemoryConfig,
    conversations,
    estimate_tokens,
    window,
)
from app.main import app
from app.ollama import OllamaClient
from app.schemas import ChatMessage


# --------------------------------------------------------------------------- #
# Token estimation + windowing
# --------------------------------------------------------------------------- #
def test_estimate_tokens_scales_with_length() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("a") == 1
    assert estimate_tokens("x" * 35) == 10
    assert estimate_tokens("x" * 36) == 11


def test_window_of_nothing_is_empty() -> None:
    result = window([], token_budget=100)
    assert result.messages == []
    assert result.trimmed is False
    assert result.estimated_tokens == 0
    assert result.stored_messages == 0


def test_window_keeps_everything_that_fits() -> None:
    messages = [
        ChatMessage(role="user", content="x" * 35),
        ChatMessage(role="assistant", content="y" * 35),
    ]
    result = window(messages, token_budget=100)
    assert result.messages == messages
    assert result.trimmed is False
    assert result.estimated_tokens == 20
    assert result.stored_messages == 2


def test_window_drops_the_oldest_messages() -> None:
    messages = [
        ChatMessage(role="user", content="a" * 35),
        ChatMessage(role="assistant", content="b" * 35),
        ChatMessage(role="user", content="c" * 35),
        ChatMessage(role="assistant", content="d" * 35),
    ]
    # Newest first: 10 + 10 = 20 fits; the third would reach 30.
    result = window(messages, token_budget=25)
    assert result.messages == messages[2:]
    assert result.trimmed is True
    assert result.estimated_tokens == 20


def test_window_always_keeps_the_current_turn() -> None:
    messages = [
        ChatMessage(role="user", content="x" * 3500),
        ChatMessage(role="assistant", content="y" * 3500),
        ChatMessage(role="user", content="z" * 350),
    ]
    result = window(messages, token_budget=50)
    assert result.messages == [messages[-1]]
    assert result.trimmed is True


def test_window_never_opens_with_an_assistant_reply() -> None:
    messages = [
        ChatMessage(role="user", content="a" * 350),
        ChatMessage(role="assistant", content="b" * 35),
        ChatMessage(role="user", content="c" * 35),
    ]
    # 10 (current) + 10 (reply) fits, but the question before the reply does not,
    # so the orphaned reply is dropped too.
    result = window(messages, token_budget=25)
    assert result.messages == [messages[2]]
    assert result.trimmed is True
    assert result.estimated_tokens == 10


def test_window_can_pin_the_opening_question() -> None:
    messages = [
        ChatMessage(role="user", content="first " + "a" * 350),
        ChatMessage(role="assistant", content="b" * 350),
        ChatMessage(role="user", content="c" * 35),
        ChatMessage(role="assistant", content="d" * 35),
        ChatMessage(role="user", content="e" * 35),
    ]
    result = window(messages, token_budget=25, keep_first=True)
    assert result.messages == [messages[0], messages[4]]
    assert result.trimmed is True


def test_window_keep_first_does_not_duplicate() -> None:
    messages = [
        ChatMessage(role="user", content="x" * 35),
        ChatMessage(role="assistant", content="y" * 35),
    ]
    result = window(messages, token_budget=100, keep_first=True)
    assert result.messages == messages


# --------------------------------------------------------------------------- #
# The store
# --------------------------------------------------------------------------- #
def _store(**overrides) -> ConversationStore:
    return ConversationStore(MemoryConfig(**overrides))


def test_store_generates_unique_ids() -> None:
    store = _store()
    assert store.create().id != store.create().id


def test_store_creates_loads_and_appends() -> None:
    store = _store()
    store.create("abc")
    assert store.load("abc") == []

    store.append("abc", [ChatMessage(role="user", content="hi")])
    store.append("abc", [ChatMessage(role="assistant", content="hello")])

    assert [m.content for m in store.load("abc")] == ["hi", "hello"]
    snapshot = store.get("abc")
    assert snapshot is not None
    assert snapshot.updated_at >= snapshot.created_at


def test_store_ensure_keeps_an_existing_conversation() -> None:
    store = _store()
    store.ensure("abc")
    store.append("abc", [ChatMessage(role="user", content="hi")])
    store.ensure("abc")
    assert [m.content for m in store.load("abc")] == ["hi"]


def test_store_returns_detached_snapshots() -> None:
    store = _store()
    store.create("abc")
    store.append("abc", [ChatMessage(role="user", content="hi")])
    snapshot = store.load("abc")
    assert snapshot is not None
    snapshot.clear()
    assert store.load("abc") != []


def test_store_trims_to_max_messages() -> None:
    store = _store(max_messages=4)
    store.create("abc")
    store.append("abc", [ChatMessage(role="user", content=str(i)) for i in range(10)])
    messages = store.load("abc")
    assert [m.content for m in messages] == ["6", "7", "8", "9"]


def test_store_evicts_the_least_recently_used() -> None:
    store = _store(max_conversations=2)
    store.create("a")
    store.create("b")
    store.load("a")  # 'a' is now the most recently used
    store.create("c")

    assert store.load("b") is None
    assert store.load("a") == []
    assert store.load("c") == []


def test_store_expires_idle_conversations(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _store(ttl_seconds=60)
    store.create("abc")
    store.append("abc", [ChatMessage(role="user", content="hi")])
    assert store.load("abc") is not None

    later = time.time() + 61
    monkeypatch.setattr("app.conversations.time.time", lambda: later)

    assert store.load("abc") is None


def test_store_delete_and_clear() -> None:
    store = _store()
    store.create("a")
    store.create("b")
    assert store.delete("a") is True
    assert store.delete("a") is False
    assert store.load("a") is None

    store.clear()
    assert store.load("b") is None


def test_store_stats_reports_configuration_and_contents() -> None:
    store = _store(
        token_budget=123,
        max_messages=7,
        max_conversations=3,
        ttl_seconds=120,
        keep_first=True,
    )
    store.create("a")
    store.append("a", [ChatMessage(role="user", content="hi")])

    stats = store.stats()
    assert stats["settings"] == {
        "enabled": True,
        "token_budget": 123,
        "max_messages": 7,
        "max_conversations": 3,
        "ttl_minutes": 2.0,
        "keep_first": True,
    }
    assert stats["conversations"] == 1
    assert stats["messages"] == 1
    assert stats["items"] == [
        {
            "conversation_id": "a",
            "messages": 1,
            "created_at": stats["items"][0]["created_at"],
            "updated_at": stats["items"][0]["updated_at"],
        }
    ]


# --------------------------------------------------------------------------- #
# HTTP surface
# --------------------------------------------------------------------------- #
def _ok_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "gemma4:31b-cloud",
            "message": {"role": "assistant", "content": content},
            "done": True,
            "prompt_eval_count": 11,
            "eval_count": 4,
        },
    )


def _stream_response() -> httpx.Response:
    lines = [
        json.dumps({"model": "gemma4:31b-cloud", "message": {"content": "Hel"}, "done": False}),
        json.dumps({"model": "gemma4:31b-cloud", "message": {"content": "lo"}, "done": False}),
        json.dumps({"model": "gemma4:31b-cloud", "message": {"content": ""}, "done": True}),
    ]
    return httpx.Response(
        200,
        content="\n".join(lines) + "\n",
        headers={"content-type": "application/x-ndjson"},
    )


@dataclass
class Harness:
    """The test client plus the upstream payloads it received."""

    client: TestClient
    seen: list[dict]


def _sent(harness: Harness) -> list[dict]:
    """The messages in the most recent upstream request (system prompt first)."""
    return harness.seen[-1]["messages"]


def _sse_payloads(response: httpx.Response) -> list[dict]:
    frames = [line for line in response.iter_lines() if line.startswith("data:")]
    return [json.loads(frame.removeprefix("data: ").strip()) for frame in frames]


def _wire(test_client: TestClient, settings: Settings, handler) -> None:
    test_client.app.state.ollama = OllamaClient(
        settings, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


@pytest.fixture
def chat(monkeypatch: pytest.MonkeyPatch) -> Iterator[Harness]:
    """The app wired to a mock transport that records each upstream payload."""
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    get_settings.cache_clear()
    settings = Settings(ollama_api_key="test-key")
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        index = len(seen)
        seen.append(body)
        return _stream_response() if body.get("stream") else _ok_response(f"reply-{index}")

    with TestClient(app) as test_client:
        _wire(test_client, settings, handler)
        conversations.reset()
        yield Harness(client=test_client, seen=seen)

    get_settings.cache_clear()


def test_stateless_request_is_not_stored(chat: Harness) -> None:
    response = chat.client.post("/chat", json={"messages": [{"role": "user", "content": "Hi"}]})
    assert response.status_code == 200
    assert response.json()["conversation_id"] is None
    assert response.json()["memory"] is None
    assert conversations.stats()["conversations"] == 0


def test_first_turn_is_stored_and_reported(chat: Harness) -> None:
    response = chat.client.post(
        "/chat",
        json={"conversation_id": "conv-1", "messages": [{"role": "user", "content": "Hi"}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"] == "conv-1"
    assert body["memory"] == {
        "enabled": True,
        "stored_messages": 1,
        "window_messages": 1,
        "estimated_tokens": 1,
        "trimmed": False,
        "keep_first": False,
    }

    detail = chat.client.get("/conversations/conv-1").json()
    assert detail["message_count"] == 2
    assert [m["content"] for m in detail["messages"]] == ["Hi", "reply-0"]


def test_second_turn_sends_the_first(chat: Harness) -> None:
    chat.client.post(
        "/chat", json={"conversation_id": "c", "messages": [{"role": "user", "content": "one"}]}
    )
    chat.client.post(
        "/chat", json={"conversation_id": "c", "messages": [{"role": "user", "content": "two"}]}
    )

    sent = _sent(chat)
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
    assert [m["content"] for m in sent[1:]] == ["one", "reply-0", "two"]


def test_client_history_is_ignored_for_a_known_conversation(
    chat: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    chat.client.post(
        "/chat", json={"conversation_id": "c", "messages": [{"role": "user", "content": "one"}]}
    )
    caplog.set_level(logging.DEBUG, logger="leyna.memory")
    chat.client.post(
        "/chat",
        json={
            "conversation_id": "c",
            "messages": [
                {"role": "user", "content": "stale"},
                {"role": "assistant", "content": "stale"},
                {"role": "user", "content": "two"},
            ],
        },
    )

    assert [m["content"] for m in _sent(chat)[1:]] == ["one", "reply-0", "two"]
    assert any("ignoring 2 client-supplied" in message for message in caplog.messages)


def test_unknown_conversation_id_is_seeded_from_the_request(chat: Harness) -> None:
    response = chat.client.post(
        "/chat",
        json={
            "conversation_id": "restart",
            "messages": [
                {"role": "user", "content": "one"},
                {"role": "assistant", "content": "old"},
                {"role": "user", "content": "two"},
            ],
        },
    )
    assert response.status_code == 200
    assert response.json()["memory"]["stored_messages"] == 3

    detail = chat.client.get("/conversations/restart").json()
    assert [m["content"] for m in detail["messages"]] == ["one", "old", "two", "reply-0"]


def test_memory_disabled_is_stateless(chat: Harness) -> None:
    conversations.configure(Settings(memory_enabled=False))

    response = chat.client.post(
        "/chat",
        json={"conversation_id": "c", "messages": [{"role": "user", "content": "Hi"}]},
    )
    assert response.status_code == 200
    assert response.json()["conversation_id"] is None
    assert response.json()["memory"] is None
    assert conversations.stats()["conversations"] == 0
    assert chat.client.post("/conversations").status_code == 409


def test_streaming_remembers_after_completion(chat: Harness) -> None:
    with chat.client.stream(
        "POST",
        "/chat/stream",
        json={"conversation_id": "s", "messages": [{"role": "user", "content": "Hi"}]},
    ) as response:
        assert response.status_code == 200
        payloads = _sse_payloads(response)

    assert "".join(p.get("delta", "") for p in payloads) == "Hello"
    assert payloads[-1]["done"] is True
    assert payloads[-1]["conversation_id"] == "s"
    assert payloads[-1]["memory"]["window_messages"] == 1

    detail = chat.client.get("/conversations/s").json()
    assert [m["content"] for m in detail["messages"]] == ["Hi", "Hello"]


def _always_500(request: httpx.Request) -> httpx.Response:
    return httpx.Response(500, json={"error": "boom"})


def test_failed_request_is_not_remembered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    get_settings.cache_clear()
    settings = Settings(ollama_api_key="test-key")

    with TestClient(app) as test_client:
        _wire(test_client, settings, _always_500)
        conversations.reset()
        response = test_client.post(
            "/chat",
            json={"conversation_id": "c", "messages": [{"role": "user", "content": "Hi"}]},
        )
    get_settings.cache_clear()

    assert response.status_code == 500
    assert conversations.stats()["conversations"] == 0


def test_failed_stream_is_not_remembered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    get_settings.cache_clear()
    settings = Settings(ollama_api_key="test-key")

    with TestClient(app) as test_client:
        _wire(test_client, settings, _always_500)
        conversations.reset()
        with test_client.stream(
            "POST",
            "/chat/stream",
            json={"conversation_id": "c", "messages": [{"role": "user", "content": "Hi"}]},
        ) as response:
            payloads = _sse_payloads(response)
    get_settings.cache_clear()

    assert payloads[-1]["error"] == "boom"
    assert conversations.stats()["conversations"] == 0


def test_conversation_lifecycle(chat: Harness) -> None:
    created = chat.client.post("/conversations")
    assert created.status_code == 200
    conversation_id = created.json()["conversation_id"]
    assert conversation_id

    empty = chat.client.get(f"/conversations/{conversation_id}").json()
    assert empty["message_count"] == 0
    assert empty["messages"] == []

    chat.client.post(
        "/chat",
        json={"conversation_id": conversation_id, "messages": [{"role": "user", "content": "Hi"}]},
    )
    detail = chat.client.get(f"/conversations/{conversation_id}").json()
    assert detail["conversation_id"] == conversation_id
    assert detail["message_count"] == 2
    assert detail["created_at"] and detail["updated_at"]

    deleted = chat.client.delete(f"/conversations/{conversation_id}")
    assert deleted.status_code == 200
    assert deleted.json() == {"ok": True}

    assert chat.client.get(f"/conversations/{conversation_id}").status_code == 404
    assert chat.client.delete(f"/conversations/{conversation_id}").status_code == 404


def test_unknown_conversation_is_a_404(chat: Harness) -> None:
    assert chat.client.get("/conversations/nope").status_code == 404


def test_health_reports_memory(chat: Harness) -> None:
    assert chat.client.get("/health").json()["memory_enabled"] is True


def test_debug_memory_reports_and_clears(chat: Harness) -> None:
    chat.client.post("/conversations")
    chat.client.post(
        "/chat", json={"conversation_id": "c", "messages": [{"role": "user", "content": "Hi"}]}
    )

    body = chat.client.get("/debug/memory").json()
    assert body["settings"]["enabled"] is True
    assert body["settings"]["token_budget"] == 3000
    assert body["conversations"] == 2
    assert body["messages"] == 2

    assert chat.client.delete("/debug/memory").json() == {"ok": True}
    assert chat.client.get("/debug/memory").json()["conversations"] == 0
