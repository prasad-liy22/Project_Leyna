"""Tests for the debug API (logs, usage, runtime API key)."""

import logging
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app
from app.ollama import OllamaClient

ENV_KEY = "env-key-1234567890"


def _ok_response(content: str = "ok") -> httpx.Response:
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


def _auth_header(response_status: int | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if response_status is not None:
            return httpx.Response(response_status, json={"error": "nope"})
        return _ok_response()

    return handler


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, list[str]]]:
    """A TestClient whose upstream is mocked; records Authorization headers."""
    monkeypatch.setenv("OLLAMA_API_KEY", ENV_KEY)
    get_settings.cache_clear()
    settings = Settings(ollama_api_key=ENV_KEY)
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["authorization"])
        return _ok_response()

    with TestClient(app) as client:
        app.state.ollama = OllamaClient(
            settings, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )
        yield client, seen

    get_settings.cache_clear()


def test_state_masks_env_key(wired: tuple[TestClient, list[str]]) -> None:
    client, _ = wired
    body = client.get("/debug/state").json()

    assert body["api_key"]["configured"] is True
    assert body["api_key"]["source"] == "env"
    assert body["api_key"]["masked"] == "env-…7890"
    assert ENV_KEY not in client.get("/debug/state").text  # never leak the raw key


def test_set_api_key_override_is_used(wired: tuple[TestClient, list[str]]) -> None:
    client, seen = wired
    response = client.post("/debug/api-key", json={"api_key": "runtime-key-9876543210"})

    assert response.status_code == 200
    assert response.json()["api_key"]["source"] == "debug-override"
    assert response.json()["api_key"]["masked"] == "runt…3210"

    client.post("/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert seen[-1] == "Bearer runtime-key-9876543210"


def test_clear_api_key_reverts_to_env(wired: tuple[TestClient, list[str]]) -> None:
    client, seen = wired
    client.post("/debug/api-key", json={"api_key": "runtime-key-9876543210"})

    response = client.delete("/debug/api-key")
    assert response.json()["api_key"]["source"] == "env"

    client.post("/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert seen[-1] == f"Bearer {ENV_KEY}"


def test_empty_api_key_clears_override(wired: tuple[TestClient, list[str]]) -> None:
    client, _ = wired
    client.post("/debug/api-key", json={"api_key": "runtime-key-9876543210"})

    response = client.post("/debug/api-key", json={"api_key": ""})
    assert response.json()["api_key"]["source"] == "env"


def test_persist_writes_env_file(
    wired: tuple[TestClient, list[str]], tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = wired
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("OLLAMA_MODEL=keep-me\nOLLAMA_API_KEY=old\n")

    response = client.post(
        "/debug/api-key", json={"api_key": "persist-me-123456", "persist": True}
    )
    assert response.status_code == 200

    text = (tmp_path / ".env").read_text()
    assert "OLLAMA_API_KEY=persist-me-123456" in text
    assert "OLLAMA_API_KEY=old" not in text
    assert "OLLAMA_MODEL=keep-me" in text  # other lines untouched


def test_health_follows_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_API_KEY", "")
    get_settings.cache_clear()
    settings = Settings(ollama_api_key="")

    with TestClient(app) as client:
        app.state.ollama = OllamaClient(settings)
        assert client.get("/health").json()["configured"] is False

        client.post("/debug/api-key", json={"api_key": "fresh-key-1234567890"})
        assert client.get("/health").json()["configured"] is True

    get_settings.cache_clear()


def test_usage_records_tokens(wired: tuple[TestClient, list[str]]) -> None:
    client, _ = wired
    client.post("/chat", json={"messages": [{"role": "user", "content": "hi"}]})

    body = client.get("/debug/usage").json()
    assert body["totals"] == {
        "requests": 1,
        "ok": 1,
        "errors": 0,
        "prompt_tokens": 11,
        "completion_tokens": 4,
        "total_tokens": 15,
    }
    record = body["records"][0]
    assert record["endpoint"] == "chat"
    assert record["prompt_tokens"] == 11
    assert record["completion_tokens"] == 4
    assert record["ok"] is True
    assert record["latency_ms"] >= 0


def test_usage_records_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_API_KEY", ENV_KEY)
    get_settings.cache_clear()
    settings = Settings(ollama_api_key=ENV_KEY)

    with TestClient(app) as client:
        app.state.ollama = OllamaClient(
            settings,
            client=httpx.AsyncClient(
                transport=httpx.MockTransport(_auth_header(response_status=401))
            ),
        )
        response = client.post("/chat", json={"messages": [{"role": "user", "content": "hi"}]})
        assert response.status_code == 401
        body = client.get("/debug/usage").json()

    get_settings.cache_clear()
    assert body["totals"]["errors"] == 1
    assert body["totals"]["requests"] == 1
    assert body["records"][0]["ok"] is False
    assert body["records"][0]["error"] == "nope"


def test_logs_capture_and_incremental_poll(wired: tuple[TestClient, list[str]]) -> None:
    client, _ = wired
    logging.getLogger("leyna.test").warning("hello from the test")

    page = client.get("/debug/logs").json()
    assert any("hello from the test" in entry["message"] for entry in page["records"])

    # Polling with `after` only returns newer records.
    page2 = client.get(f"/debug/logs?after={page['last_id']}").json()
    assert page2["records"] == []

    logging.getLogger("leyna.test").error("second message")
    page3 = client.get(f"/debug/logs?after={page['last_id']}").json()
    assert [entry["message"] for entry in page3["records"]] == ["second message"]


def test_clear_logs(wired: tuple[TestClient, list[str]]) -> None:
    client, _ = wired
    logging.getLogger("leyna.test").info("something")
    assert client.delete("/debug/logs").json()["ok"] is True
    assert client.get("/debug/logs").json()["records"] == []


def test_admin_token_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "s3cr3t")
    monkeypatch.setenv("OLLAMA_API_KEY", ENV_KEY)
    get_settings.cache_clear()

    with TestClient(app) as client:
        assert client.get("/debug/state").status_code == 401
        assert client.get("/debug/state", headers={"X-Admin-Token": "wrong"}).status_code == 401
        ok = client.get("/debug/state", headers={"X-Admin-Token": "s3cr3t"})
        assert ok.status_code == 200

    get_settings.cache_clear()
