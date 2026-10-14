"""Server-side short-term memory for conversations.

A request is stateless unless it carries a ``conversation_id``. When it does,
the transcript lives here — in process memory — and the model is sent only the
newest slice of it that fits a token budget.

Scope and limitations:

* **Single process.** State lives in this interpreter and is not shared between
  workers, so run one uvicorn worker (with or without ``--reload``). With
  several workers the same ``conversation_id`` would resolve to different
  histories depending on which one handled the request.
* **Not durable.** Restarting the process forgets everything.
* **Approximate.** Token counts come from a character heuristic rather than a
  real tokenizer, so the budget is a guide rather than a hard limit.

Swap in Redis or a database behind the same handful of methods for anything
more serious.
"""

from __future__ import annotations

import logging
import math
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .config import Settings
from .schemas import ChatMessage

logger = logging.getLogger("leyna.memory")

#: Rough characters per token for English prose. A real tokenizer would be
#: exact but would add a dependency; this only has to bound the window sanely.
CHARS_PER_TOKEN = 3.5

#: Cap the characters we bother to measure so one pathological message cannot
#: make windowing expensive.
MAX_CONTENT_CHARS = 100_000


def estimate_tokens(text: str) -> int:
    """Estimate the token count of ``text`` from its length."""
    if not text:
        return 0
    return max(1, math.ceil(min(len(text), MAX_CONTENT_CHARS) / CHARS_PER_TOKEN))


def iso(timestamp: float) -> str:
    """Format a POSIX timestamp as an ISO-8601 UTC string."""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class MemoryConfig:
    """Tunables for the store, derived from :class:`~app.config.Settings`."""

    enabled: bool = True
    token_budget: int = 3000
    max_messages: int = 60
    max_conversations: int = 100
    ttl_seconds: float = 180 * 60.0
    keep_first: bool = False

    @classmethod
    def from_settings(cls, settings: Settings) -> MemoryConfig:
        """Build a config from the application settings."""
        return cls(
            enabled=settings.memory_enabled,
            token_budget=settings.memory_token_budget,
            max_messages=settings.memory_max_messages,
            max_conversations=settings.memory_max_conversations,
            ttl_seconds=settings.memory_ttl_minutes * 60.0,
            keep_first=settings.memory_keep_first,
        )


@dataclass
class Conversation:
    """One stored transcript (user and assistant turns, no system prompt)."""

    id: str
    messages: list[ChatMessage] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class Window:
    """The slice of a transcript that is sent to the model."""

    messages: list[ChatMessage]
    trimmed: bool
    estimated_tokens: int
    stored_messages: int


def window(
    messages: list[ChatMessage],
    *,
    token_budget: int,
    keep_first: bool = False,
) -> Window:
    """Choose the newest messages that fit ``token_budget``.

    Three rules keep the slice coherent:

    * the most recent message is always included, even when it alone exceeds
      the budget — the model must see the current turn;
    * the window never begins with an ``assistant`` message, so a reply is never
      shown without the question it answers;
    * with ``keep_first`` the opening user message is pinned to the front, so
      the original question survives trimming. This deliberately breaks the
      contiguity of the window; it is an anchor, not a summary.
    """
    total = len(messages)
    if total == 0:
        return Window([], False, 0, 0)

    costs = [estimate_tokens(message.content) for message in messages]

    # Walk backwards from the newest message, taking as many as fit. The first
    # pass is unconditional, which pins the current turn.
    start = total
    used = 0
    for index in range(total - 1, -1, -1):
        if start < total and used + costs[index] > token_budget:
            break
        start = index
        used += costs[index]

    # Turn integrity: a window must not open on a reply.
    while start < total - 1 and messages[start].role == "assistant":
        used -= costs[start]
        start += 1

    selected = list(messages[start:])

    if keep_first and start > 0:
        opening = next(
            (index for index, message in enumerate(messages) if message.role == "user"),
            None,
        )
        if opening is not None and opening < start:
            selected.insert(0, messages[opening])
            used += costs[opening]

    return Window(
        messages=selected,
        trimmed=start > 0,
        estimated_tokens=used,
        stored_messages=total,
    )


class ConversationStore:
    """A bounded, thread-safe, in-memory set of conversations.

    Lookups purge idle entries and refresh recency, so the store behaves as an
    LRU cache with a TTL. ``_purge`` and ``_evict`` assume the lock is held.
    """

    def __init__(self, config: MemoryConfig | None = None) -> None:
        self._lock = threading.Lock()
        self._conversations: OrderedDict[str, Conversation] = OrderedDict()
        self._config = config or MemoryConfig()

    # -- configuration ------------------------------------------------------
    def configure(self, settings: Settings) -> None:
        """Apply settings to this store (called once at startup)."""
        with self._lock:
            self._config = MemoryConfig.from_settings(settings)

    @property
    def config(self) -> MemoryConfig:
        """The active configuration."""
        return self._config

    @property
    def enabled(self) -> bool:
        """Whether memory is on."""
        return self._config.enabled

    def reset(self) -> None:
        """Forget everything and restore the default configuration."""
        with self._lock:
            self._conversations.clear()
            self._config = MemoryConfig()

    # -- lifecycle ----------------------------------------------------------
    def create(self, conversation_id: str | None = None) -> Conversation:
        """Start a new, empty conversation (replacing any existing one)."""
        with self._lock:
            now = time.time()
            self._purge(now)
            cid = (conversation_id or "").strip() or uuid.uuid4().hex
            conversation = Conversation(id=cid, created_at=now, updated_at=now)
            self._conversations[cid] = conversation
            self._conversations.move_to_end(cid)
            self._evict()
            logger.debug("memory: created conversation %s", cid)
            return Conversation(id=cid, created_at=now, updated_at=now)

    def ensure(self, conversation_id: str) -> None:
        """Create a conversation if it does not already exist (keeping it)."""
        with self._lock:
            if conversation_id in self._conversations:
                self._conversations.move_to_end(conversation_id)
                return
            now = time.time()
            self._purge(now)
            self._conversations[conversation_id] = Conversation(
                id=conversation_id, created_at=now, updated_at=now
            )
            self._evict()
            logger.debug("memory: created conversation %s", conversation_id)

    def get(self, conversation_id: str) -> Conversation | None:
        """A detached snapshot of a conversation, or ``None`` when unknown."""
        with self._lock:
            self._purge(time.time())
            conversation = self._conversations.get(conversation_id)
            if conversation is None:
                return None
            self._conversations.move_to_end(conversation_id)
            return Conversation(
                id=conversation.id,
                messages=list(conversation.messages),
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
            )

    def load(self, conversation_id: str) -> list[ChatMessage] | None:
        """The stored transcript (a copy), or ``None`` when unknown."""
        conversation = self.get(conversation_id)
        return None if conversation is None else conversation.messages

    def append(
        self,
        conversation_id: str,
        messages: Iterable[ChatMessage],
    ) -> Conversation | None:
        """Append messages to a conversation, trimming to ``max_messages``."""
        with self._lock:
            now = time.time()
            self._purge(now)
            conversation = self._conversations.get(conversation_id)
            if conversation is None:
                return None
            conversation.messages.extend(messages)
            overflow = len(conversation.messages) - self._config.max_messages
            if overflow > 0:
                del conversation.messages[:overflow]
            conversation.updated_at = now
            self._conversations.move_to_end(conversation_id)
            self._evict()
            return conversation

    def delete(self, conversation_id: str) -> bool:
        """Forget one conversation. Returns whether it existed."""
        with self._lock:
            return self._conversations.pop(conversation_id, None) is not None

    def clear(self) -> None:
        """Forget every conversation."""
        with self._lock:
            self._conversations.clear()

    # -- introspection ------------------------------------------------------
    def stats(self) -> dict[str, Any]:
        """A JSON-serialisable snapshot for the debug panel."""
        with self._lock:
            self._purge(time.time())
            config = self._config
            items = [
                {
                    "conversation_id": conversation.id,
                    "messages": len(conversation.messages),
                    "created_at": iso(conversation.created_at),
                    "updated_at": iso(conversation.updated_at),
                }
                for conversation in reversed(self._conversations.values())
            ]
        return {
            "settings": {
                "enabled": config.enabled,
                "token_budget": config.token_budget,
                "max_messages": config.max_messages,
                "max_conversations": config.max_conversations,
                "ttl_minutes": round(config.ttl_seconds / 60.0, 2),
                "keep_first": config.keep_first,
            },
            "conversations": len(items),
            "messages": sum(item["messages"] for item in items),
            "items": items,
        }

    # -- internals ----------------------------------------------------------
    def _purge(self, now: float) -> None:
        """Drop conversations that have been idle longer than the TTL."""
        ttl = self._config.ttl_seconds
        if ttl <= 0:
            return
        cutoff = now - ttl
        stale = [cid for cid, item in self._conversations.items() if item.updated_at < cutoff]
        for cid in stale:
            self._conversations.pop(cid, None)
        if stale:
            logger.debug("memory: expired %d idle conversation(s)", len(stale))

    def _evict(self) -> None:
        """Enforce the conversation cap, dropping the least recently used."""
        limit = self._config.max_conversations
        while len(self._conversations) > limit:
            cid, _ = self._conversations.popitem(last=False)
            logger.debug("memory: evicted least-recently-used conversation %s", cid)


#: The process-wide store. Configured from settings during application startup.
conversations = ConversationStore()
