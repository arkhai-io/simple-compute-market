"""The registry's engine and sessions over the database its settings name.

The application never creates or migrates its schema: ``registry-migrate``
does, before the application starts, and startup refuses a database the
command has not brought to its script head (``core_registry.db.migrations``).
"""

from fastapi import Request
from sqlalchemy import create_engine, make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from core_registry.config import settings
from core_registry.db.models import Base

__all__ = ["Base", "SessionLocal", "engine", "get_db"]

if settings.is_sqlite:
    database = make_url(settings.database_url).database
    # In-memory SQLite needs one shared connection. File-backed SQLite uses
    # separate connections so a retention worker cannot join an HTTP transaction.
    pool_options = {"poolclass": StaticPool} if database in (None, "", ":memory:") else {}
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
        **pool_options,
    )
else:
    engine = create_engine(
        settings.database_url,
        pool_size=20,
        max_overflow=0,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db(request: Request) -> Session:
    """Yield one registry-owned database session."""

    sessions = getattr(request.app.state, "database_sessions", SessionLocal)
    db = sessions()
    try:
        yield db
    finally:
        db.close()
