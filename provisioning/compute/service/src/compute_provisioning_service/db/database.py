from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from market_schema_migrations import CheckResult, MigrateReport, migrate, refusal_message
from market_schema_migrations.sqlalchemy_adapter import (
    SqlAlchemyMigrationConnection,
    check_engine,
)

from compute_provisioning_service.db.migrations import CHAIN


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


class IncompatibleDatabase(RuntimeError):
    """The database is not exactly at the chain this image carries."""

    def __init__(self, result: CheckResult) -> None:
        super().__init__(refusal_message(result, service=CHAIN.service, command=CHAIN.command))
        self.result = result


def migrate_database(engine: Engine) -> MigrateReport:
    """Bring the database to the chain's head, adopting a v0.3.0 database.

    ``compute-provisioning-migrate`` calls this, and nothing else does outside
    tests: the application only checks. It takes only the database, so its
    result depends on the code and the data already stored, never on the
    service's configuration, which startup applies instead (seeding pools,
    importing documents). See
    openspec/specs/deployment-state/spec.md#requirement-service-owned-migration-history.
    """
    with engine.connect() as connection:
        return migrate(CHAIN, SqlAlchemyMigrationConnection(connection))


def check_database(engine: Engine) -> CheckResult:
    """The database's state against the chain, read without changing anything.

    A file-backed database is read through a read-only connection, so a
    missing file is reported absent and is not created.
    """
    return check_engine(CHAIN, engine)


def require_compatible_database(engine: Engine) -> None:
    """Refuse to serve a database not exactly at the chain this image carries."""
    result = check_database(engine)
    if not result.compatible:
        raise IncompatibleDatabase(result)
