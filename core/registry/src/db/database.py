import os
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from src.config import settings
from src.db.models import Base
from alembic.config import Config
from alembic import command

# Create engine based on database type
if settings.is_sqlite:
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
        poolclass=StaticPool if "sqlite" in settings.database_url else None,
    )
else:
    engine = create_engine(
        settings.database_url,
        pool_size=20,
        max_overflow=0,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Session:
    """Dependency for getting database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _apply_migrations() -> None:
    """Apply pending Alembic migrations to the current database.

    Three cases are handled:

    1. **Fresh database (no tables):** ``create_all`` has just created the
       schema from the current SQLAlchemy models.  ``alembic_version`` does
       not exist, so we *stamp* the database at head — recording that all
       migrations have logically been applied — rather than replaying the
       full migration chain against a schema that already matches.

    2. **Legacy database (tables exist, no alembic_version):** The database
       was created by a previous ``create_all``-only startup path and has
       never been Alembic-managed.  We stamp it at head on the same logic as
       case 1: the current models already represent head, so replaying the
       chain would attempt to re-create tables and columns that are already
       present.  Future schema additions will run as incremental migrations
       from this point.

    3. **Alembic-managed database (alembic_version present):** Standard
       ``upgrade head``.  Only migrations not yet recorded in
       ``alembic_version`` are applied.  This is the normal upgrade path.
    """
    # alembic/ lives two levels above this file (src/db/database.py -> /app/)
    alembic_dir = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "alembic")
    )
    cfg = Config()
    cfg.set_main_option("script_location", alembic_dir)
    # Override the URL so alembic/env.py uses the live settings value
    # rather than the placeholder in alembic.ini.
    cfg.set_main_option("sqlalchemy.url", settings.database_url)

    inspector = inspect(engine)
    if "alembic_version" not in inspector.get_table_names():
        # No version tracking yet: stamp rather than replay.
        command.stamp(cfg, "head")
    else:
        command.upgrade(cfg, "head")


def init_db():
    """Initialize database tables and apply all pending Alembic migrations."""
    Base.metadata.create_all(bind=engine)
    _apply_migrations()

