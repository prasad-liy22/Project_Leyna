"""SQLAlchemy models for persistent agent memory."""

from __future__ import annotations

import time
import uuid

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .database import Base


class ConversationModel(Base):
    __tablename__ = "conversations"

    id = Column(String, primary_key=True, default=lambda: uuid.uuid4().hex)
    created_at = Column(Float, default=time.time, nullable=False)
    updated_at = Column(Float, default=time.time, nullable=False)

    messages = relationship(
        "MessageModel",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="MessageModel.position",
    )


class MessageModel(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String, ForeignKey("conversations.id"), nullable=False, index=True)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    position = Column(Integer, nullable=False)
    created_at = Column(Float, default=time.time, nullable=False)

    conversation = relationship("ConversationModel", back_populates="messages")
