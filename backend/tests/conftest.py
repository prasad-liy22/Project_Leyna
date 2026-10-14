"""Shared test fixtures."""

from collections.abc import Iterator

import pytest

from app.conversations import conversations
from app.runtime import runtime


@pytest.fixture(autouse=True)
def _reset_runtime() -> Iterator[None]:
    """Keep the process-wide state from leaking between tests."""
    runtime.set_api_key_override(None)
    runtime.logs.clear()
    runtime.usage.clear()
    conversations.reset()
    yield
    runtime.set_api_key_override(None)
    runtime.logs.clear()
    runtime.usage.clear()
    conversations.reset()
