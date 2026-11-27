"""The authority's database: the engine, sessions, and its state against a migration chain."""

from __future__ import annotations

from market_schema_migrations import (
    Chain,
    CheckResult,
    MigrateReport,
    migrate,
    refusal_message,
)
from market_schema_migrations.sqlalchemy_adapter import (
    SqlAlchemyMigrationConnection,
    check_engine,
)
from sqlalchemy import Connection, Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


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


class IncompatibleDatabase(RuntimeError):
    """The database is not exactly at the chain the service's image carries."""

    def __init__(self, result: CheckResult, chain: Chain[Connection]) -> None:
        super().__init__(
            refusal_message(result, service=chain.service, command=chain.command)
        )
        self.result = result


def migrate_database(engine: Engine, chain: Chain[Connection]) -> MigrateReport:
    """Bring the database to the chain's head, refusing one it did not build.

    A service's migration command calls this, and nothing else does outside
    tests: the application only checks. It takes only the database, so its
    result depends on the code and the data already stored, never on the
    service's configuration.
    """
    with engine.connect() as connection:
        return migrate(chain, SqlAlchemyMigrationConnection(connection))


def check_database(engine: Engine, chain: Chain[Connection]) -> CheckResult:
    """The database's state against the chain, read without changing anything.

    A file-backed database is read through a read-only connection, so a
    missing file is reported absent and is not created.
    """
    return check_engine(chain, engine)


def require_migrated(engine: Engine, chain: Chain[Connection]) -> None:
    """Refuse a database not exactly at the chain, naming the migration command.

    A service root calls this at startup before anything writes; it issues no
    DDL.
    """
    result = check_database(engine, chain)
    if not result.compatible:
        raise IncompatibleDatabase(result, chain)
