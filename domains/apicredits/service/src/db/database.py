from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from db.models import Base


def create_db_engine(database_url: str, is_sqlite: bool) -> Engine:
    if is_sqlite:
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
    return create_engine(database_url, pool_size=10, max_overflow=10)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db(engine: Engine) -> None:
    """Create all tables. Called once during application startup."""
    Base.metadata.create_all(bind=engine)
    # Site-authority quota ledger tables ride core_site's own metadata.
    from core_site.db import Base as SiteBase
    SiteBase.metadata.create_all(bind=engine)
