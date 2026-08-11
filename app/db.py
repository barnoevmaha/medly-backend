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
    """Name the driver explicitly in the URL.

    Hosted databases hand out URLs that either use a scheme SQLAlchemy rejects
    or one that resolves to a driver we do not install:

      postgres://      Railway, Heroku and Fly still emit this. SQLAlchemy 2.x
                       refuses it outright.
      postgresql://    Defaults to psycopg2. We install psycopg 3.
      mysql://         Defaults to MySQLdb, which needs a C toolchain to build.
                       We install PyMySQL, which is pure Python.

    Rewriting here means MEDLY_DATABASE_URL can be pasted straight from a
    provider dashboard without anyone having to know this.
    """
    prefixes = {
        "postgres://": "postgresql+psycopg://",
        "postgresql://": "postgresql+psycopg://",
        "mysql://": "mysql+pymysql://",
    }
    for old, new in prefixes.items():
        if url.startswith(old):
            return url.replace(old, new, 1)
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
