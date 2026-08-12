import os

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.config import settings
from src.db.models import Base

if settings.is_sqlite:
    engine = create_engine(
        settings.database_url,
        connect_args={
            "check_same_thread": False
        }
        if "sqlite" in settings.database_url
        else {},
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
    """Yield one registry-owned database session."""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _alembic_config() -> Config:
    alembic_dir = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "alembic")
    )
    config = Config()
    config.set_main_option("script_location", alembic_dir)
    config.set_main_option("sqlalchemy.url", settings.database_url)
    return config


def _legacy_revision(inspector) -> str:
    """Infer only registry-owned unversioned schemas with unambiguous boundaries."""

    tables = set(inspector.get_table_names())
    if "agents" in tables and "listings" in tables:
        columns = {column["name"] for column in inspector.get_columns("agents")}
        if {"scheme", "identifier"}.issubset(columns):
            return "013_api_key_scope"
        if "owner" in columns:
            return "011_listing_accepted_escrows"
        raise RuntimeError("unversioned agent registry lacks publisher ownership")

    if {"publishers", "identities", "listings"}.issubset(tables):
        identity_columns = {
            column["name"] for column in inspector.get_columns("identities")
        }
        if "status" in identity_columns:
            replay_columns = (
                {
                    column["name"]
                    for column in inspector.get_columns(
                        "publisher_replay_reservations"
                    )
                }
                if "publisher_replay_reservations" in tables
                else set()
            )
            if {"lease_owner", "lease_expires_at"}.issubset(replay_columns):
                return "017_publisher_replay_leases"
            return "016_marketplace_principal_auth"
        listing_columns = {
            column["name"] for column in inspector.get_columns("listings")
        }
        if "settlement_options" in listing_columns:
            return "015_listing_settlement_options"
        return "014_agent_to_publisher"

    raise RuntimeError("unversioned registry schema cannot be migrated safely")


def _apply_migrations() -> None:
    """Create a fresh schema or migrate one explicitly recognized schema boundary."""

    config = _alembic_config()
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if not tables:
        Base.metadata.create_all(bind=engine)
        command.stamp(config, "head")
        return
    if "alembic_version" in tables:
        command.upgrade(config, "head")
        return

    revision = _legacy_revision(inspector)
    command.stamp(config, revision)
    command.upgrade(config, "head")


def init_db() -> None:
    """Initialize or transactionally migrate the registry-owned schema."""

    _apply_migrations()
