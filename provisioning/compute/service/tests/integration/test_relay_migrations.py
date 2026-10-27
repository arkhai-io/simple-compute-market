"""The service's migrations create and evolve VM's relay tables.

The service's database holds VM's tables, so its migration history creates them
on a database that predates them. VM's own suites, in the VM adapter, test the
tables over a schema built from VM's models; these test what the service's
migrations make of a stored database.

External boundary: SQLAlchemy against SQLite. The database is deterministic and
does no network I/O, so the real engine is used rather than a mock.
"""

from __future__ import annotations

import uuid

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from compute_provisioning_service.db.database import create_db_engine, run_migrations
from compute_provisioning_service.db.migrations import check_schema_version
from vm_provisioning_adapter.db import AnsiblePoolConfig, RelayPortLease

_PLAYBOOK_PATH = "/configured/playbook.yaml"
_ACTIVE_OWNER_INDEX = "uq_relay_port_leases_active_owner"


def _engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run_migrations(engine)
    return engine


def _lease(port: int, owner_id: str) -> RelayPortLease:
    return RelayPortLease(
        id=str(uuid.uuid4()),
        relay_id="site-a",
        remote_port=port,
        owner_kind="fulfillment",
        owner_id=owner_id,
    )


def _has_active_owner_index(engine) -> bool:
    with engine.connect() as connection:
        sql = connection.execute(
            text("SELECT sql FROM sqlite_master WHERE type = 'index' AND name = :name"),
            {"name": _ACTIVE_OWNER_INDEX},
        ).scalar_one_or_none()
    return sql is not None and "released_at IS NULL" in sql


def _refuses_a_second_active_lease(engine) -> bool:
    with Session(engine) as session:
        session.add(_lease(6100, "cr-1"))
        session.commit()
        session.add(_lease(6101, "cr-1"))
        try:
            session.commit()
        except IntegrityError:
            return True
    return False


class TestTheActiveOwnerIndex:
    def test_a_lease_table_lacking_the_index_gains_it(self, tmp_path):
        """A stored lease table without the index, and no migration history:
        migrating creates the index over the existing table, which schema
        creation leaves alone because the table already exists."""
        engine = create_db_engine(f"sqlite:///{tmp_path / 'old.db'}", is_sqlite=True)
        with engine.begin() as connection:
            connection.execute(text(
                """
                CREATE TABLE relay_port_leases (
                    id VARCHAR PRIMARY KEY,
                    relay_id VARCHAR NOT NULL,
                    remote_port INTEGER NOT NULL,
                    host_name VARCHAR,
                    pool_id VARCHAR,
                    owner_kind VARCHAR NOT NULL,
                    owner_id VARCHAR NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    released_at TIMESTAMP,
                    CONSTRAINT uq_relay_port_leases_endpoint UNIQUE (relay_id, remote_port)
                )
                """
            ))
        assert not _has_active_owner_index(engine)

        run_migrations(engine)

        assert _has_active_owner_index(engine)
        assert _refuses_a_second_active_lease(engine)
        check_schema_version(engine)
        engine.dispose()

    def test_a_fresh_database_created_from_the_models_migrates(self, tmp_path):
        """With VM's model declaring the index, a fresh database migrates, twice,
        and ends with the index in place."""
        engine = create_db_engine(f"sqlite:///{tmp_path / 'fresh.db'}", is_sqlite=True)

        run_migrations(engine)
        run_migrations(engine)

        assert _has_active_owner_index(engine)
        assert _refuses_a_second_active_lease(engine)
        check_schema_version(engine)
        engine.dispose()


class TestMigrations:
    def test_the_lease_table_carries_the_endpoint_constraint(self):
        engine = _engine()
        constraints = inspect(engine).get_unique_constraints("relay_port_leases")
        columns = [sorted(c["column_names"]) for c in constraints]
        assert ["relay_id", "remote_port"] in columns

    def test_the_relay_table_carries_the_endpoint_constraint(self):
        engine = _engine()
        constraints = inspect(engine).get_unique_constraints("relays")
        columns = [sorted(c["column_names"]) for c in constraints]
        assert ["relay_addr", "relay_port"] in columns

    def test_pool_config_gains_the_relay_reference(self):
        engine = _engine()
        names = {c["name"] for c in inspect(engine).get_columns("ansible_pool_configs")}
        assert "relay_id" in names

    def test_the_document_import_digest_table_exists(self):
        engine = _engine()
        names = {
            c["name"]
            for c in inspect(engine).get_columns("definition_document_imports")
        }
        assert {"document_kind", "digest", "imported_at"} <= names

    def test_existing_pool_rows_keep_working_without_a_relay(self):
        """Nullable reference: a pool row stored with no relay reads as none."""
        engine = _engine()
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO ansible_pool_configs "
                "(pool_id, playbook_path, requirement_delegate, extra_vars) "
                "VALUES ('legacy', :p, 'vm_management_v1', '{}')"
            ), {"p": _PLAYBOOK_PATH})
        with Session(engine) as session:
            assert session.get(AnsiblePoolConfig, "legacy").relay_id is None

    def test_running_migrations_twice_is_idempotent(self):
        engine = _engine()
        run_migrations(engine)
        with Session(engine) as session:
            session.add(_lease(6100, "cr-1"))
            session.commit()
            assert session.query(RelayPortLease).count() == 1
