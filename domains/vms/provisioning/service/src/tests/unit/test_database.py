import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from db.database import run_migrations
from db.migrations import SchemaDriftError, check_schema_version
from db.models import AnsibleJob, AnsiblePoolConfig, DEFAULT_POOL_ID, Host, ResourcePool


def _sqlite_memory_engine():
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _create_pre_migration_tables(engine):
    with engine.begin() as connection:
        connection.execute(text(
            """
            CREATE TABLE ansible_jobs (
                id VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                params JSON NOT NULL,
                result JSON,
                logs TEXT,
                error TEXT,
                process_id VARCHAR,
                retry_count INTEGER NOT NULL DEFAULT 0,
                max_retries INTEGER NOT NULL DEFAULT 3,
                next_retry_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                PRIMARY KEY (id)
            )
            """
        ))
        connection.execute(text(
            """
            INSERT INTO ansible_jobs (id, status, params)
            VALUES ('job-1', 'queued', '{}')
            """
        ))
        connection.execute(text(
            """
            CREATE TABLE hosts (
                name VARCHAR NOT NULL,
                kvm_host VARCHAR NOT NULL,
                ssh_user VARCHAR NOT NULL,
                ssh_key_type VARCHAR NOT NULL,
                ssh_key_value VARCHAR NOT NULL,
                gpu_count INTEGER NOT NULL,
                enabled BOOLEAN NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                PRIMARY KEY (name)
            )
            """
        ))
        connection.execute(text(
            """
            INSERT INTO hosts (
                name, kvm_host, ssh_user, ssh_key_type, ssh_key_value,
                gpu_count, enabled
            ) VALUES (
                'kvm1', '10.0.0.1', 'root', 'path', '/keys/id_ed25519',
                0, 1
            )
            """
        ))


def test_run_migrations_applies_versioned_migrations_to_old_sqlite_schema():
    engine = _sqlite_memory_engine()
    _create_pre_migration_tables(engine)

    run_migrations(
        engine,
        default_playbook_path="/configured/playbook.yaml",
        default_inventory_group="legacy_hosts",
    )

    inspector = inspect(engine)
    ansible_columns = {
        column["name"] for column in inspector.get_columns("ansible_jobs")
    }
    host_columns = {column["name"] for column in inspector.get_columns("hosts")}
    lease_columns = {
        column["name"] for column in inspector.get_columns("vm_leases")
    }
    allocation_columns = {
        column["name"] for column in inspector.get_columns("site_allocations")
    }

    assert "escrow_uid" in ansible_columns
    assert {
        "contract_version",
        "allocation_id",
        "deal_ref",
        "executor_kind",
        "action_kind",
        "idempotency_key",
    }.issubset(ansible_columns)
    assert "public_host" in host_columns
    assert "vm_leases" in inspector.get_table_names()
    assert "allocation_id" in lease_columns
    assert {
        "executor_kind",
        "executor_target",
        "release_job_id",
        "executor_ref",
    }.issubset(allocation_columns)

    assert "resource_pools" in inspector.get_table_names()
    assert "ansible_pool_configs" in inspector.get_table_names()
    assert "pool_id" in host_columns

    with Session(engine) as session:
        host = session.query(Host).one()
        job = session.query(AnsibleJob).one()
        assert host.public_host is None
        assert job.escrow_uid is None
        # The pre-existing host (inserted before the migration ran) is
        # backfilled to the default pool by the column's DB-level DEFAULT.
        assert host.pool_id == DEFAULT_POOL_ID

        default_pool = session.query(ResourcePool).filter(
            ResourcePool.id == DEFAULT_POOL_ID
        ).one()
        assert default_pool.label == "Default Pool"
        assert default_pool.provider == "ansible"
        assert default_pool.enabled is True

        # No ORM relationship crosses the resource_pools/ansible_pool_configs
        # boundary — ResourcePool and AnsiblePoolConfig now live in separate
        # declarative registries (market_resource_pools vs. this service's
        # own Base), so navigation is by explicit pool_id lookup, matching
        # how PoolConfigHandler implementations already read this table.
        ansible_config = session.query(AnsiblePoolConfig).filter(
            AnsiblePoolConfig.pool_id == DEFAULT_POOL_ID
        ).one()
        assert ansible_config.playbook_path == "/configured/playbook.yaml"
        assert ansible_config.inventory_group == "legacy_hosts"
        assert ansible_config.extra_vars == {}

    with engine.begin() as connection:
        migration_ids = {
            row[0] for row in connection.execute(
                text("SELECT id FROM schema_migrations")
            )
        }
    assert migration_ids == {
        "20260603_001_ansible_jobs_escrow_uid",
        "20260603_002_hosts_public_host",
        "20260603_003_vm_leases_table",
        "20260603_004_vm_leases_allocation_id",
        "20260707_001_site_allocations_executor_fields",
        "20260713_001_ansible_jobs_contract_fields",
        "20260713_002_resource_pools_and_hosts_pool_id",
    }


def test_run_migrations_is_idempotent():
    engine = _sqlite_memory_engine()
    _create_pre_migration_tables(engine)

    run_migrations(engine)
    run_migrations(engine)

    inspector = inspect(engine)
    ansible_columns = [
        column["name"] for column in inspector.get_columns("ansible_jobs")
    ]
    host_columns = [column["name"] for column in inspector.get_columns("hosts")]
    lease_columns = [
        column["name"] for column in inspector.get_columns("vm_leases")
    ]
    allocation_columns = [
        column["name"] for column in inspector.get_columns("site_allocations")
    ]

    assert ansible_columns.count("escrow_uid") == 1
    assert ansible_columns.count("contract_version") == 1
    assert ansible_columns.count("allocation_id") == 1
    assert ansible_columns.count("deal_ref") == 1
    assert ansible_columns.count("executor_kind") == 1
    assert ansible_columns.count("action_kind") == 1
    assert ansible_columns.count("idempotency_key") == 1
    assert host_columns.count("public_host") == 1
    assert host_columns.count("pool_id") == 1
    assert lease_columns.count("allocation_id") == 1
    assert allocation_columns.count("executor_kind") == 1
    assert allocation_columns.count("executor_target") == 1
    assert allocation_columns.count("release_job_id") == 1
    assert allocation_columns.count("executor_ref") == 1

    with Session(engine) as session:
        assert session.query(ResourcePool).filter(
            ResourcePool.id == DEFAULT_POOL_ID
        ).count() == 1

    with engine.begin() as connection:
        migration_count = connection.execute(
            text("SELECT COUNT(*) FROM schema_migrations")
        ).scalar_one()
    assert migration_count == 7


# ---------------------------------------------------------------------------
# check_schema_version — the startup drift guard
# ---------------------------------------------------------------------------


class TestCheckSchemaVersion:
    def test_passes_after_run_migrations(self):
        engine = _sqlite_memory_engine()
        run_migrations(engine)
        check_schema_version(engine)  # must not raise

    def test_raises_on_fresh_engine_with_no_migrations_table(self):
        engine = _sqlite_memory_engine()
        with pytest.raises(SchemaDriftError):
            check_schema_version(engine)

    def test_raises_when_behind_the_latest_migration(self):
        engine = _sqlite_memory_engine()
        run_migrations(engine)
        # Simulate an older DB that's missing the most recent migration.
        with engine.begin() as connection:
            connection.execute(text(
                "DELETE FROM schema_migrations WHERE id = "
                "'20260713_002_resource_pools_and_hosts_pool_id'"
            ))
        with pytest.raises(SchemaDriftError):
            check_schema_version(engine)
