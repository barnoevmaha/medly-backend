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


def _literal(value: Any) -> str:
    """Render a Python default as a SQL literal for an ALTER TABLE clause."""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


# Columns that used to exist and no longer do. Left in place they are harmless
# on Postgres but fatal on SQLite: a NOT NULL column the model no longer sets
# makes every INSERT fail. Dropping them is the migration.
DROPPED_COLUMNS: Dict[str, list] = {
    "users": ["certified", "certified_at", "competency_score"],
    "courses": ["is_certification", "emoji"],
    "quizzes": ["is_certification"],
    "challenges": ["emoji"],
    "communities": ["emoji"],
}


def migrate_columns() -> None:
    """Add columns that exist on the models but not yet in the database.

    `create_all` only ever creates missing *tables*. A column added to a model
    that already has a table — `users.points`, say — is silently absent, and the
    first query naming it fails at runtime. Doing this here means an existing
    deployment picks up new columns on boot instead of needing the volume wiped.

    New columns are added nullable and then backfilled, because SQLite refuses
    to add a NOT NULL column to a table that already has rows.
    """
    import app.models  # noqa: F401  (registers every SQLModel table)

    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy import text

    inspector = sa_inspect(engine)
    tables = set(inspector.get_table_names())

    with engine.begin() as connection:
        for table in SQLModel.metadata.sorted_tables:
            if table.name not in tables:
                continue
            present = {column["name"] for column in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in present:
                    continue
                type_sql = column.type.compile(engine.dialect)
                default = getattr(column.default, "arg", None)
                clause = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {type_sql}'
                if default is not None and not callable(default):
                    clause += f" DEFAULT {_literal(default)}"
                connection.execute(text(clause))
                if default is not None and not callable(default):
                    connection.execute(
                        text(
                            f'UPDATE "{table.name}" SET "{column.name}" = {_literal(default)} '
                            f'WHERE "{column.name}" IS NULL'
                        )
                    )

    # Drop what the models no longer declare. Needs SQLite 3.35+ (2021) or any
    # Postgres; a failure here is logged rather than fatal, because a database
    # with a stale extra column is still a working database on Postgres.
    for table_name, columns in DROPPED_COLUMNS.items():
        if table_name not in tables:
            continue
        present = {column["name"] for column in inspector.get_columns(table_name)}
        for column_name in columns:
            if column_name not in present:
                continue
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text(f'ALTER TABLE "{table_name}" DROP COLUMN "{column_name}"')
                    )
            except Exception as error:  # pragma: no cover — depends on engine version
                print(f"medly: could not drop {table_name}.{column_name}: {error}")


def init_db() -> None:
    """Import models for their side effects, then create tables."""
    import app.models  # noqa: F401  (registers every SQLModel table)

    SQLModel.metadata.create_all(engine)
    migrate_columns()


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
