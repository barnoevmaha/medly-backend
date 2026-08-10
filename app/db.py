"""Database engine and session helpers.

Works with SQLite and Postgres from the same `MEDLY_DATABASE_URL`. The engine
arguments differ between the two, so they are selected here rather than being
the caller's problem.
"""
from __future__ import annotations

from typing import Any, Dict, Iterator

from sqlmodel import Session, SQLModel, create_engine

from app.config import settings


def _normalise(url: str) -> str:
    """Make a hosted Postgres URL usable by SQLAlchemy.

    Railway, Heroku and Fly hand out `postgres://…`, a scheme SQLAlchemy 2.x
    rejects outright. `postgresql://…` defaults to psycopg2, which is not what
    we install. Both are rewritten to name psycopg 3 explicitly.
    """
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


DATABASE_URL = _normalise(settings.database_url)
_is_sqlite = DATABASE_URL.startswith("sqlite")

_engine_args: Dict[str, Any] = {"echo": False}
if _is_sqlite:
    # FastAPI serves requests from a threadpool, and SQLite objects are bound
    # to the thread that made them unless this is off.
    _engine_args["connect_args"] = {"check_same_thread": False}
else:
    # Managed Postgres drops idle connections; without pre-ping the first query
    # after an idle period fails with a stale-connection error rather than
    # transparently reconnecting.
    _engine_args["pool_pre_ping"] = True
    _engine_args["pool_recycle"] = 300

engine = create_engine(DATABASE_URL, **_engine_args)


def init_db() -> None:
    """Import models for their side effects, then create tables."""
    import app.models  # noqa: F401  (registers every SQLModel table)

    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
