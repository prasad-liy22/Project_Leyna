"""Database-backed conversation store for persistent agent memory."""

from __future__ import annotations

import logging
import time
from typing import Any, Iterable

from sqlalchemy.orm import Session

from .config import Settings
from .conversations import (
    Conversation,
    MemoryConfig,
    Window,
    estimate_tokens,
    iso,
    window,
)
from .database import SessionLocal, init_db
from .models import ConversationModel, MessageModel
from .schemas import ChatMessage

logger = logging.getLogger("leyna.memory.db")


class DBConversationStore:
    def __init__(self, config: MemoryConfig | None = None) -> None:
        self._config = config or MemoryConfig()
        init_db()

    def configure(self, settings: Settings) -> None:
        self._config = MemoryConfig.from_settings(settings)

    @property
    def config(self) -> MemoryConfig:
        return self._config

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def reset(self) -> None:
        db: Session = SessionLocal()
        try:
            db.query(MessageModel).delete()
            db.query(ConversationModel).delete()
            db.commit()
        finally:
            db.close()
        self._config = MemoryConfig()

    def create(self, conversation_id: str | None = None) -> Conversation:
        db: Session = SessionLocal()
        try:
            now = time.time()
            cid = (conversation_id or "").strip() or __import__("uuid").uuid4().hex
            conv = ConversationModel(id=cid, created_at=now, updated_at=now)
            db.add(conv)
            db.commit()
            db.refresh(conv)
            logger.debug("db memory: created conversation %s", cid)
            return Conversation(id=cid, messages=[], created_at=now, updated_at=now)
        finally:
            db.close()

    def ensure(self, conversation_id: str) -> None:
        db: Session = SessionLocal()
        try:
            conv = db.query(ConversationModel).filter_by(id=conversation_id).first()
            if conv:
                conv.updated_at = time.time()
                db.commit()
                return
            now = time.time()
            conv = ConversationModel(id=conversation_id, created_at=now, updated_at=now)
            db.add(conv)
            db.commit()
        finally:
            db.close()

    def get(self, conversation_id: str) -> Conversation | None:
        db: Session = SessionLocal()
        try:
            conv = db.query(ConversationModel).filter_by(id=conversation_id).first()
            if not conv:
                return None
            conv.updated_at = time.time()
            db.commit()
            messages = [
                ChatMessage(role=m.role, content=m.content)
                for m in sorted(conv.messages, key=lambda x: x.position)
            ]
            return Conversation(
                id=conv.id,
                messages=messages,
                created_at=conv.created_at,
                updated_at=conv.updated_at,
            )
        finally:
            db.close()

    def load(self, conversation_id: str) -> list[ChatMessage] | None:
        conv = self.get(conversation_id)
        return None if conv is None else conv.messages

    def append(self, conversation_id: str, messages: Iterable[ChatMessage]) -> Conversation | None:
        db: Session = SessionLocal()
        try:
            conv = db.query(ConversationModel).filter_by(id=conversation_id).first()
            if not conv:
                return None
            now = time.time()
            existing = len(conv.messages)
            for i, msg in enumerate(messages):
                db.add(
                    MessageModel(
                        conversation_id=conversation_id,
                        role=msg.role,
                        content=msg.content,
                        position=existing + i,
                        created_at=now,
                    )
                )
            # Trim to max_messages
            all_msgs = db.query(MessageModel).filter_by(conversation_id=conversation_id).order_by(MessageModel.position).all()
            if len(all_msgs) > self._config.max_messages:
                to_delete = all_msgs[: len(all_msgs) - self._config.max_messages]
                for m in to_delete:
                    db.delete(m)
                # Reindex
                remaining = db.query(MessageModel).filter_by(conversation_id=conversation_id).order_by(MessageModel.position).all()
                for idx, m in enumerate(remaining):
                    m.position = idx
            conv.updated_at = now
            db.commit()
            return self.get(conversation_id)
        finally:
            db.close()

    def delete(self, conversation_id: str) -> bool:
        db: Session = SessionLocal()
        try:
            conv = db.query(ConversationModel).filter_by(id=conversation_id).first()
            if not conv:
                return False
            db.delete(conv)
            db.commit()
            return True
        finally:
            db.close()

    def clear(self) -> None:
        db: Session = SessionLocal()
        try:
            db.query(MessageModel).delete()
            db.query(ConversationModel).delete()
            db.commit()
        finally:
            db.close()

    def stats(self) -> dict[str, Any]:
        db: Session = SessionLocal()
        try:
            convs = db.query(ConversationModel).all()
            items = []
            total_msgs = 0
            for c in convs:
                count = len(c.messages)
                total_msgs += count
                items.append(
                    {
                        "conversation_id": c.id,
                        "messages": count,
                        "created_at": iso(c.created_at),
                        "updated_at": iso(c.updated_at),
                    }
                )
            items.sort(key=lambda x: x["updated_at"], reverse=True)
            config = self._config
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
                "messages": total_msgs,
                "items": items,
            }
        finally:
            db.close()


# Alias for compatibility
conversations = DBConversationStore()
