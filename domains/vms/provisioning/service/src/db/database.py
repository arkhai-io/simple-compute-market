from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from db.migrations import apply_schema_migrations
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
        # File-backed: one connection per session. A single shared
        # connection (StaticPool) interleaves concurrent sessions'
        # transactions on one sqlite handle ("cannot commit - no
        # transaction is active") — rare under the old request rates,
        # but the capacity ledger's event-feed polling made it routine.
        # SQLite's file lock serializes writers; the busy timeout keeps
        # contending sessions waiting instead of erroring.
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
    apply_schema_migrations(engine)
