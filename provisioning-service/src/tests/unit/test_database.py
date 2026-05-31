from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from db.database import init_db
from db.models import Host


def _sqlite_memory_engine():
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _create_hosts_table_without_public_host(engine):
    with engine.begin() as connection:
        connection.execute(
            text(
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
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO hosts (
                    name,
                    kvm_host,
                    ssh_user,
                    ssh_key_type,
                    ssh_key_value,
                    gpu_count,
                    enabled
                ) VALUES (
                    'kvm1',
                    '10.0.0.1',
                    'root',
                    'path',
                    '/keys/id_ed25519',
                    0,
                    1
                )
                """
            )
        )


def test_init_db_adds_public_host_to_existing_sqlite_hosts_table():
    engine = _sqlite_memory_engine()
    _create_hosts_table_without_public_host(engine)

    init_db(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("hosts")}
    assert "public_host" in columns

    with Session(engine) as session:
        host = session.query(Host).one()
        assert host.name == "kvm1"
        assert host.public_host is None


def test_init_db_sqlite_public_host_migration_is_idempotent():
    engine = _sqlite_memory_engine()
    _create_hosts_table_without_public_host(engine)

    init_db(engine)
    init_db(engine)

    columns = [column["name"] for column in inspect(engine).get_columns("hosts")]
    assert columns.count("public_host") == 1
