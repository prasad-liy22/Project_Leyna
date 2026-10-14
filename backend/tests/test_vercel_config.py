"""Guards for the Vercel deployment configuration.

Vercel ships zero-config FastAPI support: it builds the whole app from a single
entrypoint, found by looking for a ``FastAPI`` instance named ``app`` at one of
a fixed set of paths (``app.py``, ``index.py``, ``server.py``, ``main.py``,
``wsgi.py``, ``asgi.py`` — either at the project root or inside ``src/`` /
``app/``). ``vercel.json`` then keys its ``functions`` settings on that same
resolved entrypoint file.

These tests keep the code and that configuration in sync, which is exactly the
kind of contradiction that silently breaks a deploy.
"""

import json
from pathlib import Path

from app import main as app_main
from app.main import app

BACKEND_DIR = Path(__file__).resolve().parents[1]
VERCEL_JSON = BACKEND_DIR / "vercel.json"

# Filenames Vercel recognises for zero-config FastAPI detection.
SUPPORTED_FILENAMES = {"app.py", "index.py", "server.py", "main.py", "wsgi.py", "asgi.py"}
# Directories those filenames are allowed to live in ("" = project root).
SUPPORTED_PARENTS = {"", "src", "app", "."}

# Hobby-plan maximum function duration (seconds) with Fluid compute.
HOBBY_MAX_DURATION = 300


def _entrypoint_path() -> Path:
    """The entrypoint file Vercel resolves, relative to the backend root.

    Taken from the module that actually defines ``app`` (``app/main.py``), so a
    file move is caught here rather than at deploy time.
    """
    return Path(app_main.__file__).resolve().relative_to(BACKEND_DIR)


def _load_config() -> dict:
    return json.loads(VERCEL_JSON.read_text(encoding="utf-8"))


def test_app_is_the_fastapi_instance_in_our_module() -> None:
    """Vercel looks for a ``FastAPI`` instance literally named ``app``."""
    from fastapi import FastAPI

    assert isinstance(app, FastAPI)
    assert app_main.app is app


def test_entrypoint_is_where_vercel_looks() -> None:
    """The app must sit at a path Vercel auto-detects without extra config."""
    entrypoint = _entrypoint_path()
    assert entrypoint.name in SUPPORTED_FILENAMES, entrypoint
    assert entrypoint.parent.name in SUPPORTED_PARENTS, entrypoint


def test_vercel_json_exists_and_is_valid() -> None:
    assert VERCEL_JSON.is_file(), "backend/vercel.json is required for deployment"
    assert isinstance(_load_config(), dict)


def test_vercel_json_is_minimal_and_has_no_conflicting_routing() -> None:
    """Only ``functions`` is set — no legacy builds or custom routing.

    ``builds`` is the legacy builder list, and ``rewrites``/``routes`` would
    fight Vercel's own FastAPI routing. Any of them here would be a red flag.
    """
    config = _load_config()
    assert set(config) <= {"$schema", "functions"}, config
    assert config.get("functions"), "expected the FastAPI function to be configured"


def test_configured_function_points_at_the_real_entrypoint() -> None:
    """A ``functions`` key that does not exist would fail the deploy."""
    functions = _load_config()["functions"]
    entrypoint = _entrypoint_path()
    assert entrypoint.as_posix() in functions, (functions, entrypoint.as_posix())
    assert (BACKEND_DIR / entrypoint).is_file()


def test_max_duration_is_within_hobby_limits() -> None:
    functions = _load_config()["functions"]
    duration = functions[_entrypoint_path().as_posix()]["maxDuration"]
    assert 1 <= duration <= HOBBY_MAX_DURATION, duration
