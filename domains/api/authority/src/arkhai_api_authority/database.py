"""The authority's database: the engine, sessions, and the migrated schema."""

from __future__ import annotations

from market_resource_pools.db import Base as PoolsBase
from market_site.db import Base as SiteBase
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from arkhai_api_authority.migrations import apply_schema_migrations
from arkhai_api_authority.models import Base


def create_db_engine(database_url: str, is_sqlite: bool) -> Engine:
    if not is_sqlite:
        raise ValueError(
            "The authority supports SQLite only; got a non-SQLite database_url "
            f"({database_url!r}). There is no tested or supported path for another "
            "database engine."
        )
    if ":memory:" in database_url:
        # A shared in-memory database exists on one connection only, so every
        # session must see the same one.
        return create_engine(
            database_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    # File-backed: SQLite's file lock serializes writers, and the busy timeout
    # keeps contending sessions waiting instead of erroring.
    return create_engine(
        database_url,
        connect_args={"check_same_thread": False, "timeout": 30},
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def run_migrations(engine: Engine) -> None:
    """Create missing tables and apply the versioned migrations, idempotently.

    ``create_all`` only creates missing tables; anything that alters an
    existing one is a migration in the chain.
    """
    Base.metadata.create_all(bind=engine)
    PoolsBase.metadata.create_all(bind=engine)
    SiteBase.metadata.create_all(bind=engine)
    apply_schema_migrations(engine)
