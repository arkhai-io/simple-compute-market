from sqlalchemy import create_engine, Engine, inspect, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from db.models import Base


def create_db_engine(database_url: str, is_sqlite: bool) -> Engine:
    if is_sqlite:
        return create_engine(
            database_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    return create_engine(database_url, pool_size=10, max_overflow=10)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db(engine: Engine) -> None:
    """Create all tables. Called once during application startup."""
    Base.metadata.create_all(bind=engine)
    if engine.dialect.name == "sqlite":
        _migrate_sqlite_schema(engine)


def _migrate_sqlite_schema(engine: Engine) -> None:
    """Apply small additive SQLite migrations for persisted local DBs."""
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "hosts" not in table_names:
        return

    host_columns = {column["name"] for column in inspector.get_columns("hosts")}
    if "public_host" not in host_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE hosts ADD COLUMN public_host VARCHAR"))
