from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from db.migrations import apply_schema_migrations
from db.models import Base


def create_db_engine(database_url: str, is_sqlite: bool) -> Engine:
    if not is_sqlite:
        raise ValueError(
            "The API-credits service supports SQLite only; got a "
            f"non-SQLite database_url ({database_url!r}). There is no "
            "tested or supported path for another database engine."
        )
    if ":memory:" in database_url:
        # A shared in-memory DB only exists on one connection — tests
        # rely on every session seeing the same data.
        return create_engine(
            database_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    # File-backed: one connection per session; SQLite's file lock
    # serializes writers and the busy timeout keeps contending
    # sessions waiting instead of erroring (same reasoning as the
    # provisioning service's engine).
    return create_engine(
        database_url,
        connect_args={"check_same_thread": False, "timeout": 30},
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def run_migrations(engine: Engine) -> None:
    """Create all tables and apply versioned migrations.

    Called once during application startup, before the app is ready to
    serve requests (see ``container.py``). Idempotent — safe to call on
    every restart. ``create_all`` remains appropriate for an empty
    bootstrap (it only creates missing tables, never alters existing
    ones); anything beyond that — a column rename, a dropped column, a
    backfill — is what ``apply_schema_migrations`` is for once this
    service's schema actually needs to evolve.
    """
    Base.metadata.create_all(bind=engine)
    # Site-authority quota ledger tables ride market_site's own metadata.
    from market_site.db import Base as SiteBase
    SiteBase.metadata.create_all(bind=engine)

    apply_schema_migrations(engine)
