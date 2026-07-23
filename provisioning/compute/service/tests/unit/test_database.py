import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from compute_provisioning_service.db.database import run_migrations
from compute_provisioning_service.db.migrations import SchemaDriftError, check_schema_version
from compute_provisioning_service.db.models import AnsibleJob, AnsiblePoolConfig, DEFAULT_POOL_ID, Host, ResourcePool
from market_site.ledger import CapacityLedgerService


def _sqlite_memory_engine():
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def test_schema_check_rejects_missing_fulfillment_table_after_current_marker():
    engine = _sqlite_memory_engine()
    run_migrations(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE scheduling_cursors"))

    with pytest.raises(SchemaDriftError, match="scheduling_cursors"):
        check_schema_version(engine)


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
        # Pre-POOLS-6 shape of the site-authority ledger tables: no
        # capacity/dimensions/dimensions columns yet. A populated row
        # here exercises the actual additive-column migration path,
        # rather than only the fresh-create-all path a brand new table
        # would take.
        connection.execute(text(
            """
            CREATE TABLE site_resources (
                resource_id VARCHAR NOT NULL,
                resource_type VARCHAR NOT NULL,
                resource_subtype VARCHAR,
                total_units INTEGER NOT NULL,
                attributes JSON,
                enabled BOOLEAN NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                PRIMARY KEY (resource_id)
            )
            """
        ))
        connection.execute(text(
            """
            INSERT INTO site_resources (
                resource_id, resource_type, resource_subtype, total_units,
                attributes, enabled
            ) VALUES (
                'pre-existing-gpu', 'compute.gpu', 'h200', 8,
                '{"vm_host": "kvm1", "pool_id": "legacy-pool"}', 1
            )
            """
        ))
        connection.execute(text(
            """
            CREATE TABLE site_allocations (
                allocation_id VARCHAR NOT NULL,
                resource_id VARCHAR NOT NULL,
                units INTEGER NOT NULL,
                state VARCHAR NOT NULL,
                deal_ref JSON,
                escrow_uid VARCHAR,
                hold_expires_at VARCHAR,
                executor_kind VARCHAR,
                executor_target VARCHAR,
                release_job_id VARCHAR,
                executor_ref JSON,
                vm_host VARCHAR,
                vm_target VARCHAR,
                lease_start_utc VARCHAR,
                lease_end_utc VARCHAR,
                create_job_id VARCHAR,
                vm_remove_job_id VARCHAR,
                failure_reason VARCHAR,
                failure_message TEXT,
                released_at VARCHAR,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                PRIMARY KEY (allocation_id)
            )
            """
        ))
        connection.execute(text(
            """
            INSERT INTO site_allocations (
                allocation_id, resource_id, units, state, deal_ref
            ) VALUES (
                'pre-existing-alloc', 'pre-existing-gpu', 3, 'reserved', '{}'
            )
            """
        ))
        connection.execute(text(
            """
            CREATE TABLE capacity_events (
                version INTEGER NOT NULL,
                kind VARCHAR NOT NULL,
                resource_id VARCHAR,
                occurred_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                PRIMARY KEY (version)
            )
            """
        ))
        connection.execute(text(
            """
            INSERT INTO capacity_events (version, kind, resource_id)
            VALUES (1, 'reserved', 'pre-existing-gpu')
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
    reservation_columns = {
        column["name"] for column in inspector.get_columns("capacity_reservations")
    }

    assert "escrow_uid" in ansible_columns
    assert {
        "contract_version",
        "capacity_reservation_id",
        "deal_ref",
        "executor_kind",
        "action_kind",
        "idempotency_key",
    }.issubset(ansible_columns)
    assert "public_host" in host_columns
    # The final schema has no dead lease table or legacy reservation name.
    assert "vm_leases" not in inspector.get_table_names()
    assert "site_allocations" not in inspector.get_table_names()
    assert {
        "executor_kind",
        "executor_target",
        "release_job_id",
        "executor_ref",
        "owner_principal",
    }.issubset(reservation_columns)

    # capacity/dimensions columns land on genuinely
    # pre-existing site-authority tables via the additive-column
    # migration path, not only via create_all() on a brand new table
    event_columns = {
        column["name"] for column in inspector.get_columns("capacity_events")
    }
    assert "site_resources" not in inspector.get_table_names()
    assert "capacity_buckets" in inspector.get_table_names()
    assert "capacity_reservation_debits" in inspector.get_table_names()
    bucket_indexes = {index["name"] for index in inspector.get_indexes("capacity_buckets")}
    debit_indexes = {index["name"] for index in inspector.get_indexes("capacity_reservation_debits")}
    assert "ix_capacity_buckets_backing_resource_id" in bucket_indexes
    assert "ix_capacity_buckets_pool_id" in bucket_indexes
    assert "ix_capacity_reservation_debits_capacity_bucket_id" in debit_indexes
    debit_foreign_keys = inspector.get_foreign_keys("capacity_reservation_debits")
    assert {fk["referred_table"] for fk in debit_foreign_keys} == {
        "capacity_reservations", "capacity_buckets"
    }
    assert "dimensions" in reservation_columns
    assert "dimensions" in event_columns

    # The pre-existing row (inserted before the migration ran, with
    # capacity/dimensions left NULL) reads correctly through the real
    # ledger's fallback-to-legacy-fields logic, not just via a raw column
    # check.
    ledger = CapacityLedgerService(sessionmaker(bind=engine))
    snapshot = {row["resource_id"]: row for row in ledger.snapshot()}
    pre_existing = snapshot["pre-existing-gpu"]
    assert pre_existing["capacity"] == {"gpu_count": 8}
    assert pre_existing["available"] == {"gpu_count": 5}  # 8 total - 3 held
    # pool_id is backfilled from the pre-existing row's attributes JSON,
    # where the storefront's old sync push put it -- not left NULL just
    # because the row predates the real column.
    assert pre_existing["pool_id"] == "legacy-pool"
    reservation = ledger.get_reservation("pre-existing-alloc")
    assert reservation["dimensions"] == {"gpu_count": 3}
    assert reservation["owner_principal"] == "legacy-admin"

    assert {"settlement_records", "provisioned_resources", "scheduling_cursors"}.issubset(
        inspector.get_table_names()
    )
    settlement_indexes = {
        index["name"] for index in inspector.get_indexes("settlement_records")
    }
    provisioned_indexes = {
        index["name"] for index in inspector.get_indexes("provisioned_resources")
    }
    assert "ix_settlement_records_fulfillment_id" in settlement_indexes
    assert "ix_settlement_records_settlement_resource_id" in settlement_indexes
    assert "ix_provisioned_resources_capacity_reservation_id" in provisioned_indexes
    assert "ix_provisioned_resources_fulfillment_id" in provisioned_indexes
    provisioned_foreign_keys = inspector.get_foreign_keys("provisioned_resources")
    assert {fk["referred_table"] for fk in provisioned_foreign_keys} == {
        "settlement_records"
    }
    cursor_pk = inspector.get_pk_constraint("scheduling_cursors")
    assert cursor_pk["constrained_columns"] == ["resource_kind"]

    # New fulfillment tables are mounted by current metadata and initialization
    # remains safe to run repeatedly.
    run_migrations(
        engine,
        default_playbook_path="/configured/playbook.yaml",
        default_inventory_group="legacy_hosts",
    )
    check_schema_version(engine)

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
        "20260718_001_drop_vm_leases_table",
        "20260720_001_multidimensional_capacity",
        "20260722_001_pools7_capacity_model_cutover",
        "20260723_001_fulfillment_aggregate",
        "20260723_002_storefront_ownership",
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
    reservation_columns = [
        column["name"] for column in inspector.get_columns("capacity_reservations")
    ]

    assert ansible_columns.count("escrow_uid") == 1
    assert ansible_columns.count("contract_version") == 1
    assert ansible_columns.count("capacity_reservation_id") == 1
    assert ansible_columns.count("deal_ref") == 1
    assert ansible_columns.count("executor_kind") == 1
    assert ansible_columns.count("action_kind") == 1
    assert ansible_columns.count("idempotency_key") == 1
    assert host_columns.count("public_host") == 1
    assert host_columns.count("pool_id") == 1
    assert "vm_leases" not in inspector.get_table_names()
    assert "site_allocations" not in inspector.get_table_names()
    assert reservation_columns.count("executor_kind") == 1
    assert reservation_columns.count("executor_target") == 1
    assert reservation_columns.count("release_job_id") == 1
    assert reservation_columns.count("executor_ref") == 1
    assert reservation_columns.count("dimensions") == 1
    assert reservation_columns.count("owner_principal") == 1
    event_columns = [
        column["name"] for column in inspector.get_columns("capacity_events")
    ]
    assert "site_resources" not in inspector.get_table_names()
    assert "capacity_buckets" in inspector.get_table_names()
    assert "capacity_reservation_debits" in inspector.get_table_names()
    assert event_columns.count("dimensions") == 1

    with Session(engine) as session:
        assert session.query(ResourcePool).filter(
            ResourcePool.id == DEFAULT_POOL_ID
        ).count() == 1

    with engine.begin() as connection:
        migration_count = connection.execute(
            text("SELECT COUNT(*) FROM schema_migrations")
        ).scalar_one()
    assert migration_count == 12


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
                "'20260722_001_pools7_capacity_model_cutover'"
            ))
        with pytest.raises(SchemaDriftError):
            check_schema_version(engine)


def test_fresh_current_schema_contains_only_capacity_bucket_model():
    engine = _sqlite_memory_engine()
    run_migrations(engine)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert "site_resources" not in tables
    assert "site_allocations" not in tables
    assert {
        "capacity_buckets",
        "capacity_reservations",
        "capacity_reservation_debits",
    }.issubset(tables)
