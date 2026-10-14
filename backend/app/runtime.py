"""In-memory runtime state for the debug features.

Three things live here, all scoped to the process lifetime:

* a bounded buffer of recent log records (the "server log console"),
* per-request token usage accounting,
* an optional API key override that takes precedence over the environment.

Everything is guarded by locks because log handlers can be called from
arbitrary threads.
"""

from __future__ import annotations

import logging
import re
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Settings

LOG_BUFFER_SIZE = 500
USAGE_BUFFER_SIZE = 200
MAX_MESSAGE_CHARS = 4000
ENV_FILE = Path(".env")

_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def parse_level(name: str) -> int:
    """Map a level name to its numeric value, defaulting to INFO."""
    return _LEVELS.get(name.strip().upper(), logging.INFO)


def _now_iso(timestamp: float | None = None) -> str:
    moment = datetime.fromtimestamp(timestamp, tz=timezone.utc) if timestamp else datetime.now(timezone.utc)
    return moment.isoformat(timespec="milliseconds")


class LogBuffer:
    """A bounded, thread-safe ring buffer of structured log records."""

    def __init__(self, maxlen: int = LOG_BUFFER_SIZE) -> None:
        self._entries: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._next_id = 0

    def add(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if record.exc_info:
            message += "\n" + logging.Formatter().formatException(record.exc_info)
        if len(message) > MAX_MESSAGE_CHARS:
            message = message[:MAX_MESSAGE_CHARS] + "…"

        with self._lock:
            self._next_id += 1
            self._entries.append(
                {
                    "id": self._next_id,
                    "time": _now_iso(record.created),
                    "level": record.levelname,
                    "logger": record.name,
                    "message": message,
                }
            )

    def snapshot(
        self, *, limit: int = 200, after: int = 0, min_level: int = logging.INFO
    ) -> tuple[list[dict[str, Any]], int]:
        """Return up to ``limit`` entries newer than ``after``, plus the last id."""
        with self._lock:
            entries = [
                entry
                for entry in self._entries
                if entry["id"] > after and _LEVELS.get(entry["level"], 0) >= min_level
            ]
            last_id = self._next_id
        return entries[-limit:], last_id

    def count(self) -> int:
        with self._lock:
            return len(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


class _RingBufferHandler(logging.Handler):
    """Feeds log records into a :class:`LogBuffer`."""

    def __init__(self, buffer: LogBuffer) -> None:
        super().__init__(level=logging.INFO)
        self._buffer = buffer

    def emit(self, record: logging.LogRecord) -> None:
        try:
            # Avoid the console logging its own polling traffic.
            if record.name.startswith("uvicorn.access") and "/debug" in record.getMessage():
                return
            # httpx logs one INFO line per request; keep only its warnings+.
            if record.name.startswith("httpx") and record.levelno < logging.WARNING:
                return
            self._buffer.add(record)
        except Exception:  # pragma: no cover - logging must never raise
            self.handleError(record)


class UsageStore:
    """Token/latency accounting for completed (and failed) requests."""

    def __init__(self, maxlen: int = USAGE_BUFFER_SIZE) -> None:
        self._records: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._next_id = 0
        self._totals: dict[str, int] = {
            "requests": 0,
            "ok": 0,
            "errors": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    def record(
        self,
        *,
        endpoint: str,
        model: str,
        ok: bool,
        latency_ms: float,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        error: str | None = None,
    ) -> None:
        if prompt_tokens is None and completion_tokens is None:
            total_tokens: int | None = None
        else:
            total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)

        with self._lock:
            self._next_id += 1
            self._records.append(
                {
                    "id": self._next_id,
                    "time": _now_iso(),
                    "endpoint": endpoint,
                    "model": model,
                    "ok": ok,
                    "latency_ms": latency_ms,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "error": error,
                }
            )
            self._totals["requests"] += 1
            self._totals["ok" if ok else "errors"] += 1
            self._totals["prompt_tokens"] += prompt_tokens or 0
            self._totals["completion_tokens"] += completion_tokens or 0
            self._totals["total_tokens"] += total_tokens or 0

    def snapshot(self, *, limit: int = 50) -> tuple[dict[str, int], list[dict[str, Any]]]:
        """Return aggregate totals and the newest ``limit`` records."""
        with self._lock:
            totals = dict(self._totals)
            records = list(self._records)[-limit:]
        return totals, list(reversed(records))

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
            for key in self._totals:
                self._totals[key] = 0


class RuntimeState:
    """Mutable state layered on top of the cached :class:`Settings`."""

    def __init__(self) -> None:
        self.logs = LogBuffer()
        self.usage = UsageStore()
        self.started_at = datetime.now(timezone.utc)
        self._api_key_override: str | None = None
        self._handler: logging.Handler | None = None

    # -- API key ------------------------------------------------------------
    def set_api_key_override(self, key: str | None) -> None:
        """Set (or clear, when empty/None) the runtime API key override."""
        self._api_key_override = (key or "").strip() or None

    def effective_api_key(self, settings: Settings) -> str:
        if self._api_key_override is not None:
            return self._api_key_override
        return settings.ollama_api_key.strip()

    def key_source(self, settings: Settings) -> str:
        if self._api_key_override is not None:
            return "debug-override"
        return "env" if settings.ollama_api_key.strip() else "unset"

    def is_configured(self, settings: Settings) -> bool:
        return bool(self.effective_api_key(settings))

    # -- logging ------------------------------------------------------------
    def attach_log_handler(self) -> None:
        """Capture root + uvicorn logs into :attr:`logs` (idempotent)."""
        if self._handler is not None:
            return
        self._handler = _RingBufferHandler(self.logs)
        root = logging.getLogger()
        root.addHandler(self._handler)
        if root.level == logging.NOTSET or root.level > logging.INFO:
            root.setLevel(logging.INFO)
        # uvicorn's default config stops these from reaching the root logger.
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            logging.getLogger(name).propagate = True

    def detach_log_handler(self) -> None:
        if self._handler is not None:
            logging.getLogger().removeHandler(self._handler)
            self._handler = None


runtime = RuntimeState()


def mask_key(key: str) -> str | None:
    """Mask a secret for display, keeping a short prefix/suffix."""
    key = key.strip()
    if not key:
        return None
    if len(key) <= 8:
        return "•" * len(key)
    return f"{key[:4]}…{key[-4:]}"


def persist_api_key(key: str, path: Path = ENV_FILE) -> bool:
    """Write ``OLLAMA_API_KEY`` into the ``.env`` file. Returns success."""
    try:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
    except OSError:
        return False

    line = f"OLLAMA_API_KEY={key}"
    pattern = re.compile(r"^\s*OLLAMA_API_KEY\s*=.*$", re.MULTILINE)

    if pattern.search(text):
        new_text = pattern.sub(lambda _match: line, text, count=1)
    else:
        separator = "" if (not text or text.endswith("\n")) else "\n"
        new_text = f"{text}{separator}{line}\n"

    try:
        path.write_text(new_text, encoding="utf-8")
    except OSError:
        return False
    return True
