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


def run_migrations(
    engine: Engine,
    *,
    default_playbook_path: str = "/opt/domains/vms/provisioning/iac/ansible/playbooks/single-tenant/vm-operations.yaml",
    default_inventory_group: str = "kvm_hosts",
) -> None:
    """Create all tables and apply versioned migrations.

    This is the full migration entrypoint: ``python -m db.migrate`` (CLI,
    for local dev and the Helm init container) and ``make migrate`` both
    call this. It is idempotent — safe to run on every deploy/restart.

    The main service container does **not** call this at startup; it calls
    :func:`db.migrations.check_schema_version` instead and fails fast if
    migrations haven't been applied. See ARCHITECTURE.md § Schema Migration
    Execution.
    """
    # Resource-pool tables must be created before this service's own Base:
    # ansible_pool_configs (on Base) has a ForeignKey("resource_pools.id"),
    # and SQLAlchemy's cross-metadata FK resolution during create_all needs
    # the referenced table to already exist.
    from market_resource_pools.db import Base as PoolsBase
    PoolsBase.metadata.create_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    # Site-authority ledger tables ride the shared market_site
    # metadata (db.models re-exports the classes).
    from market_site.db import Base as SiteBase
    SiteBase.metadata.create_all(bind=engine)
    apply_schema_migrations(
        engine,
        default_playbook_path=default_playbook_path,
        default_inventory_group=default_inventory_group,
    )
