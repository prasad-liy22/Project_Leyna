"""Database setup for persistent agent memory.

Supports SQLite by default (local dev) and Postgres via DATABASE_URL.
"""

from __future__ import annotations

import os
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def _get_database_url() -> str:
    url = os.getenv("DATABASE_URL") or os.getenv("DB_URL") or ""
    if url.strip():
        return url.strip()
    # Default to local SQLite file
    return "sqlite:///./leyna_memory.db"


DATABASE_URL = _get_database_url()

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables if they don't exist."""
    from . import models  # ensure models are imported

    Base.metadata.create_all(bind=engine)
