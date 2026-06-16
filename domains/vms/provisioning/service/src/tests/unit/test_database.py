from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from db.database import init_db
from db.models import AnsibleJob, Host


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


def test_init_db_applies_versioned_migrations_to_old_sqlite_schema():
    engine = _sqlite_memory_engine()
    _create_pre_migration_tables(engine)

    init_db(engine)

    inspector = inspect(engine)
    ansible_columns = {
        column["name"] for column in inspector.get_columns("ansible_jobs")
    }
    host_columns = {column["name"] for column in inspector.get_columns("hosts")}
    lease_columns = {
        column["name"] for column in inspector.get_columns("vm_leases")
    }

    assert "escrow_uid" in ansible_columns
    assert "public_host" in host_columns
    assert "vm_leases" in inspector.get_table_names()
    assert "allocation_id" in lease_columns

    with Session(engine) as session:
        host = session.query(Host).one()
        job = session.query(AnsibleJob).one()
        assert host.public_host is None
        assert job.escrow_uid is None

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
    }


def test_init_db_migrations_are_idempotent():
    engine = _sqlite_memory_engine()
    _create_pre_migration_tables(engine)

    init_db(engine)
    init_db(engine)

    inspector = inspect(engine)
    ansible_columns = [
        column["name"] for column in inspector.get_columns("ansible_jobs")
    ]
    host_columns = [column["name"] for column in inspector.get_columns("hosts")]
    lease_columns = [
        column["name"] for column in inspector.get_columns("vm_leases")
    ]

    assert ansible_columns.count("escrow_uid") == 1
    assert host_columns.count("public_host") == 1
    assert lease_columns.count("allocation_id") == 1

    with engine.begin() as connection:
        migration_count = connection.execute(
            text("SELECT COUNT(*) FROM schema_migrations")
        ).scalar_one()
    assert migration_count == 4
