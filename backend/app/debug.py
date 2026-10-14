"""Debug API.

Exposes the internals the debug panel needs:

* ``GET  /debug/state``    — configuration snapshot + masked API key
* ``POST /debug/api-key``  — swap the API key at runtime (optionally persist)
* ``DELETE /debug/api-key``— revert to the environment/.env key
* ``GET  /debug/logs``     — recent server log records
* ``DELETE /debug/logs``   — clear the log buffer
* ``GET  /debug/usage``    — token usage totals + recent requests
* ``DELETE /debug/usage``  — clear usage history

When ``ADMIN_TOKEN`` is set, every route here requires a matching
``X-Admin-Token`` header.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from .config import Settings, get_settings
from .runtime import mask_key, parse_level, persist_api_key, runtime

router = APIRouter(prefix="/debug", tags=["debug"])


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class ApiKeyInfo(BaseModel):
    configured: bool
    masked: str | None = None
    source: str


class UsageTotals(BaseModel):
    requests: int = 0
    ok: int = 0
    errors: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class UsageRecord(BaseModel):
    id: int
    time: str
    endpoint: str
    model: str
    ok: bool
    latency_ms: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    error: str | None = None


class UsageReport(BaseModel):
    totals: UsageTotals
    records: list[UsageRecord]


class LogEntry(BaseModel):
    id: int
    time: str
    level: str
    logger: str
    message: str


class LogPage(BaseModel):
    records: list[LogEntry]
    last_id: int


class DebugState(BaseModel):
    debug_enabled: bool
    model: str
    base_url: str
    chat_url: str
    system_prompt: str
    request_timeout: float
    api_key: ApiKeyInfo
    started_at: str
    log_count: int
    usage: UsageTotals


class ApiKeyUpdate(BaseModel):
    api_key: str = Field(
        default="",
        description="New key to use. An empty string clears the override.",
    )
    persist: bool = Field(
        default=False,
        description="Also write the key to the .env file so it survives a restart.",
    )


class OkResponse(BaseModel):
    ok: bool = True


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    """Reject debug calls unless the configured admin token matches."""
    settings = get_settings()
    if not settings.admin_token:
        return
    provided = (x_admin_token or "").encode("utf-8")
    expected = settings.admin_token.encode("utf-8")
    if not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing X-Admin-Token header.")


def _state(settings: Settings) -> DebugState:
    key = runtime.effective_api_key(settings)
    totals, _ = runtime.usage.snapshot(limit=1)
    return DebugState(
        debug_enabled=settings.debug_enabled,
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        chat_url=settings.chat_url,
        system_prompt=settings.system_prompt,
        request_timeout=settings.request_timeout,
        api_key=ApiKeyInfo(
            configured=bool(key),
            masked=mask_key(key),
            source=runtime.key_source(settings),
        ),
        started_at=runtime.started_at.isoformat(),
        log_count=runtime.logs.count(),
        usage=UsageTotals(**totals),
    )


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@router.get("/state", response_model=DebugState)
async def get_state() -> DebugState:
    """Current configuration, with the API key masked."""
    return _state(get_settings())


@router.post("/api-key", response_model=DebugState)
async def set_api_key(update: ApiKeyUpdate) -> DebugState:
    """Set the API key used for subsequent requests."""
    key = update.api_key.strip()
    if update.persist and key and not persist_api_key(key):
        raise HTTPException(status_code=500, detail="Could not write the API key to .env.")

    runtime.set_api_key_override(key)
    return _state(get_settings())


@router.delete("/api-key", response_model=DebugState)
async def clear_api_key() -> DebugState:
    """Drop the runtime override and fall back to the environment/.env key."""
    runtime.set_api_key_override(None)
    return _state(get_settings())


@router.get("/logs", response_model=LogPage)
async def get_logs(
    limit: int = Query(200, ge=1, le=1000),
    after: int = Query(0, ge=0, description="Only return records with a higher id."),
    level: str = Query("INFO", description="Minimum level: DEBUG, INFO, WARNING, ERROR."),
) -> LogPage:
    """Recent server logs, oldest first."""
    records, last_id = runtime.logs.snapshot(
        limit=limit, after=after, min_level=parse_level(level)
    )
    return LogPage(records=records, last_id=last_id)


@router.delete("/logs", response_model=OkResponse)
async def clear_logs() -> OkResponse:
    runtime.logs.clear()
    return OkResponse()


@router.get("/usage", response_model=UsageReport)
async def get_usage(
    limit: int = Query(50, ge=1, le=200, description="How many recent requests to return."),
) -> UsageReport:
    """Token usage totals and the most recent requests, newest first."""
    totals, records = runtime.usage.snapshot(limit=limit)
    return UsageReport(totals=UsageTotals(**totals), records=records)


@router.delete("/usage", response_model=OkResponse)
async def clear_usage() -> OkResponse:
    runtime.usage.clear()
    return OkResponse()
