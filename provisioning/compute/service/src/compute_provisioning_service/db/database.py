from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from compute_provisioning_service.db.migrations import apply_schema_migrations
from compute_provisioning_service.db.models import Base


def _enable_sqlite_foreign_keys(engine: Engine) -> Engine:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def create_db_engine(database_url: str, is_sqlite: bool) -> Engine:
    if is_sqlite:
        if ":memory:" in database_url:
            # A shared in-memory DB only exists on one connection — tests
            # rely on every session seeing the same data.
            return _enable_sqlite_foreign_keys(create_engine(
                database_url,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            ))
        # File-backed: one connection per session. A single shared
        # connection (StaticPool) interleaves concurrent sessions'
        # transactions on one sqlite handle ("cannot commit - no
        # transaction is active") — rare under the old request rates,
        # but the capacity ledger's event-feed polling made it routine.
        # SQLite's file lock serializes writers; the busy timeout keeps
        # contending sessions waiting instead of erroring.
        return _enable_sqlite_foreign_keys(create_engine(
            database_url,
            connect_args={"check_same_thread": False, "timeout": 30},
        ))
    return create_engine(database_url, pool_size=10, max_overflow=10)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def run_migrations(
    engine: Engine,
    *,
    default_playbook_path: str = "/opt/domains/vms/provisioning/iac/ansible/playbooks/single-tenant/vm-operations.yaml",
    default_inventory_group: str = "kvm_hosts",
) -> None:
    """Create all tables and apply versioned migrations.

    This is the full migration entrypoint: ``compute-provisioning-migrate`` (CLI,
    for local dev and the Helm init container) and ``make migrate`` both
    call this. It is idempotent — safe to run on every deploy/restart.

    The main service container does **not** call this at startup; it calls
    :func:`compute_provisioning_service.db.migrations.check_schema_version` instead and fails fast if
    migrations haven't been applied. See ARCHITECTURE.md § Schema Migration
    Execution.
    """
    # Resource-pool tables must be created before this service's own Base:
    # ansible_pool_configs (on Base) has a ForeignKey("resource_pools.id"),
    # and SQLAlchemy's cross-metadata FK resolution during create_all needs
    # the referenced table to already exist.
    from sqlalchemy import inspect
    from market_resource_pools.db import Base as PoolsBase
    from market_site.db import Base as SiteBase

    PoolsBase.metadata.create_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    # Preserve the legacy reservation table name until the versioned rename
    # migration has claimed the current name. Other site tables may be created
    # before migrations because historical migrations depend on them existing.
    existing = set(inspect(engine).get_table_names())
    site_tables = list(SiteBase.metadata.sorted_tables)
    if "site_allocations" in existing and "capacity_reservations" not in existing:
        site_tables = [table for table in site_tables if table.name != "capacity_reservations"]
    SiteBase.metadata.create_all(bind=engine, tables=site_tables)

    apply_schema_migrations(
        engine,
        default_playbook_path=default_playbook_path,
        default_inventory_group=default_inventory_group,
    )
    SiteBase.metadata.create_all(bind=engine)
