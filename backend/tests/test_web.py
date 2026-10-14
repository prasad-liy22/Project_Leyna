"""Tests for the statically-served Tailwind web UI.

The assets are built with ``cd web && npm run build`` and committed, so they are
present in a normal checkout. If someone has not built them yet the serving
tests skip rather than fail.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.routing import Mount

from app.config import get_settings
from app.main import app

WEB_DIR = Path(get_settings().web_dir)
needs_build = pytest.mark.skipif(
    not (WEB_DIR / "index.html").is_file(),
    reason="web UI not built (run 'cd web && npm run build')",
)


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Runs the lifespan so ``app.state`` is populated, but hits no network."""
    with TestClient(app) as test_client:
        yield test_client


def test_mount_is_registered() -> None:
    """The built web app is mounted at the root, after the API routes."""
    mounts = [route for route in app.routes if isinstance(route, Mount)]
    assert any(getattr(mount, "path", "") in ("/", "") for mount in mounts)


@needs_build
def test_root_serves_the_app(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Leyna" in response.text
    assert "app.css" in response.text


@needs_build
def test_built_assets_are_served(client: TestClient) -> None:
    css = client.get("/app.css")
    assert css.status_code == 200
    assert "text/css" in css.headers["content-type"]
    # Sanity-check that Tailwind actually compiled our component classes.
    assert "bubble-assistant" in css.text

    js = client.get("/app.js")
    assert js.status_code == 200
    assert "javascript" in js.headers["content-type"]


def test_unknown_static_path_is_404(client: TestClient) -> None:
    assert client.get("/definitely-not-here").status_code == 404


def test_api_routes_take_precedence(client: TestClient) -> None:
    """The mount at '/' must not shadow the API."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_docs_are_not_shadowed(client: TestClient) -> None:
    """The catch-all mount at '/' must not swallow FastAPI's own docs."""
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
