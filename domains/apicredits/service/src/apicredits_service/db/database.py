from typing import Any

from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from market_resource_pools import DEFAULT_POOL_ID, ResourcePool
from market_resource_pools_contracts import (
    BACKED,
    PoolDeclarationError,
    resolve_pool_declarations,
)
from market_schema_migrations import CheckResult, MigrateReport, migrate, refusal_message
from market_schema_migrations.sqlalchemy_adapter import (
    SqlAlchemyMigrationConnection,
    check_engine,
)

from apicredits_service.db.migrations import CHAIN


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


class IncompatibleDatabase(RuntimeError):
    """The database is not exactly at the chain this image carries."""

    def __init__(self, result: CheckResult) -> None:
        super().__init__(refusal_message(result, service=CHAIN.service, command=CHAIN.command))
        self.result = result


def migrate_database(engine: Engine) -> MigrateReport:
    """Bring the database to the chain's head, refusing one it did not build.

    ``apicredits-service-migrate`` calls this, and nothing else does outside
    tests: the application only checks. It takes only the database, so its
    result depends on the code and the data already stored, never on the
    service's configuration.
    """
    with engine.connect() as connection:
        return migrate(CHAIN, SqlAlchemyMigrationConnection(connection))


def check_database(engine: Engine) -> CheckResult:
    """The database's state against the chain, read without changing anything.

    A file-backed database is read through a read-only connection, so a
    missing file is reported absent and is not created.
    """
    return check_engine(CHAIN, engine)


def initialise_database(engine: Engine) -> None:
    """Startup's database steps: check, seed the ``default`` pool, check pools.

    A database not exactly at the chain is refused before anything writes to
    it, naming the migration command. The ``default`` pool every quota resource
    registers into is seeded here rather than by a migration: no schema
    constraint requires it, so it is runtime initialization
    (``docs/guidance/engineering/persistence.md``, "Schema changes").
    """
    result = check_database(engine)
    if not result.compatible:
        raise IncompatibleDatabase(result)
    _seed_default_pool(engine)
    _require_valid_pool_declarations(engine)


def _seed_default_pool(engine: Engine) -> None:
    with Session(engine) as session, session.begin():
        if session.get(ResourcePool, DEFAULT_POOL_ID) is None:
            session.add(
                ResourcePool(
                    id=DEFAULT_POOL_ID,
                    label="Default Pool",
                    provider="api_credits",
                    enabled=True,
                    policy_tags={
                        "deliverable_modes": ["api_credits"],
                        "advertisable_modes": ["api_credits"],
                        "capacity_backing": BACKED.label,
                    },
                )
            )


def _require_valid_pool_declarations(engine: Engine) -> None:
    """Refuse to start while any stored pool lacks valid declarations.

    Every pool must declare what it advertises and whether it can be admitted
    against; one that does not must never be served, because a reader could
    not tell it from a producer that predates those declarations.
    """
    failures: list[str] = []
    with Session(engine) as session:
        for pool in session.query(ResourcePool).order_by(ResourcePool.id):
            try:
                resolve_pool_declarations(pool.policy_tags or {})
            except PoolDeclarationError as exc:
                failures.append(f"pool '{pool.id}': {exc}")
    if failures:
        raise RuntimeError(
            "stored resource pools carry invalid declarations: " + "; ".join(failures)
        )


def load_pool_directory(
    session_factory: "sessionmaker[Session]",
) -> dict[str, dict[str, Any]]:
    """Each stored pool's metadata, as the resource-pool projection carries it.

    A storefront reads a quota resource's pool declarations from the site's
    projection through the shared resolver, the same way it reads any site's.
    """
    with session_factory() as session:
        return {
            pool.id: {
                "label": pool.label,
                "enabled": bool(pool.enabled),
                "mechanism": pool.provider,
                "policy_tags": dict(pool.policy_tags or {}),
            }
            for pool in session.query(ResourcePool).all()
        }
