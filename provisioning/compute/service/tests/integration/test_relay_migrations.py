"""The service's migrations create and evolve the relay tables.

The service's database holds the family's relay tables and VM's pool
configuration, so its migration history creates them on a database that
predates them. The family kit's suites test the tables over a schema built from
the family's models; these test what the service's migrations make of a stored
database.

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
from compute_provisioning.relays import RelayPortLease
from vm_provisioning_adapter.db import AnsiblePoolConfig

_PLAYBOOK_PATH = "/configured/playbook.yaml"
_ACTIVE_OWNER_INDEX = "uq_relay_port_leases_active_owner"
_GRANT_KEY_COLUMNS = (
    "grant_key_encrypted",
    "grant_key_id",
    "grant_key_public",
    "grant_key_activated_at",
    "staged_grant_key_encrypted",
    "staged_grant_key_id",
    "staged_grant_key_public",
)
_LEASE_GRANT_COLUMNS = ("grant_expires_at", "grant_key_id")


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
        """With the lease model declaring the index, a fresh database migrates, twice,
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

    def test_a_pools_relay_reference_is_the_familys_not_vms(self):
        """Every pool's reference is held in ``pool_relays``; VM's pool
        configuration table carries none."""
        engine = _engine()
        names = {c["name"] for c in inspect(engine).get_columns("ansible_pool_configs")}
        assert "relay_id" not in names
        assert {c["name"] for c in inspect(engine).get_columns("pool_relays")} == {
            "pool_id",
            "relay_id",
        }
        assert {
            fk["referred_table"] for fk in inspect(engine).get_foreign_keys("pool_relays")
        } == {"resource_pools", "relays"}

    def test_the_document_import_digest_table_exists(self):
        engine = _engine()
        names = {
            c["name"]
            for c in inspect(engine).get_columns("definition_document_imports")
        }
        assert {"document_kind", "digest", "imported_at"} <= names


class TestThePoolRelaysMigration:
    """A database whose VM pools hold their relay in ``ansible_pool_configs``
    keeps every reference, now in ``pool_relays``, and loses the column."""

    def _database_before_pool_relays(self, tmp_path):
        """The current schema with the migration unrecorded and the column back
        on VM's table holding references. Schema creation recreates
        ``pool_relays`` before the chain runs, so what this exercises is the copy
        and the drop; a database older than the rebuild that would otherwise
        lose the column is ``test_vm_pool_config_migration.py``'s."""
        engine = create_db_engine(f"sqlite:///{tmp_path / 'before.db'}", is_sqlite=True)
        run_migrations(engine)
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE pool_relays"))
            connection.execute(text(
                "ALTER TABLE ansible_pool_configs ADD COLUMN relay_id VARCHAR"
            ))
            connection.execute(text(
                "DELETE FROM schema_migrations WHERE id = '20261101_001_pool_relays'"
            ))
            connection.execute(text(
                "INSERT INTO relays (id, relay_addr, relay_port, vm_port_range_start, "
                "vm_port_range_count, enabled) VALUES ('site-a', '203.0.113.9', 7000, "
                "6100, 100, 1)"
            ))
            for pool_id, relay_id in (("relayed", "site-a"), ("direct", None)):
                connection.execute(
                    text(
                        "INSERT INTO resource_pools (id, label, provider, enabled, "
                        "policy_tags) VALUES (:id, :id, 'vm.ansible', 1, '{}')"
                    ),
                    {"id": pool_id},
                )
                connection.execute(
                    text(
                        "INSERT INTO ansible_pool_configs (pool_id, playbook_path, "
                        "requirement_delegate, extra_vars, relay_id) VALUES "
                        "(:id, :p, 'vm_management_v1', '{}', :relay)"
                    ),
                    {"id": pool_id, "p": _PLAYBOOK_PATH, "relay": relay_id},
                )
        return engine

    def test_a_stored_reference_is_copied_and_the_column_dropped(self, tmp_path):
        engine = self._database_before_pool_relays(tmp_path)

        run_migrations(engine)

        with engine.begin() as connection:
            held = connection.execute(
                text("SELECT pool_id, relay_id FROM pool_relays ORDER BY pool_id")
            ).all()
        assert [tuple(row) for row in held] == [("relayed", "site-a")]
        names = {c["name"] for c in inspect(engine).get_columns("ansible_pool_configs")}
        assert "relay_id" not in names
        with Session(engine) as session:
            assert session.get(AnsiblePoolConfig, "relayed").playbook_path == _PLAYBOOK_PATH
            assert session.get(AnsiblePoolConfig, "direct").playbook_path == _PLAYBOOK_PATH
        check_schema_version(engine)
        engine.dispose()

    def test_a_fresh_database_holds_no_reference_anywhere_else(self, tmp_path):
        """Schema creation makes VM's table without the column and an earlier
        migration adds it back; the chain ends without it all the same."""
        engine = create_db_engine(f"sqlite:///{tmp_path / 'fresh.db'}", is_sqlite=True)

        run_migrations(engine)

        names = {c["name"] for c in inspect(engine).get_columns("ansible_pool_configs")}
        assert "relay_id" not in names
        engine.dispose()

    def test_running_migrations_twice_is_idempotent(self):
        engine = _engine()
        run_migrations(engine)
        with Session(engine) as session:
            session.add(_lease(6100, "cr-1"))
            session.commit()
            assert session.query(RelayPortLease).count() == 1


class TestTheLeaseGrantMigration:
    def test_a_database_with_the_grant_keys_gains_the_lease_columns(self, tmp_path):
        """The upgrade from a database that recorded the grant-key migration
        and not the lease one."""
        engine = create_db_engine(f"sqlite:///{tmp_path / 'leases.db'}", is_sqlite=True)
        run_migrations(engine)
        with engine.begin() as connection:
            for column in _LEASE_GRANT_COLUMNS:
                connection.execute(
                    text(f"ALTER TABLE relay_port_leases DROP COLUMN {column}")
                )
            connection.execute(text(
                "DELETE FROM schema_migrations WHERE id = '20261101_003_relay_lease_grants'"
            ))

        run_migrations(engine)

        lease_names = {c["name"] for c in inspect(engine).get_columns("relay_port_leases")}
        assert set(_LEASE_GRANT_COLUMNS) <= lease_names
        check_schema_version(engine)
        engine.dispose()


class TestTheGrantKeyMigration:
    def test_a_stored_relay_gains_grant_key_state_and_holds_no_key(self, tmp_path):
        """A relay stored before relays held grant keys keeps its row, with no
        active key, the retired-key table appears, and each port lease gains
        its grant's expiry and signing key."""
        engine = create_db_engine(f"sqlite:///{tmp_path / 'keys.db'}", is_sqlite=True)
        run_migrations(engine)
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE relay_retired_grant_keys"))
            for column in _GRANT_KEY_COLUMNS:
                connection.execute(text(f"ALTER TABLE relays DROP COLUMN {column}"))
            for column in _LEASE_GRANT_COLUMNS:
                connection.execute(
                    text(f"ALTER TABLE relay_port_leases DROP COLUMN {column}")
                )
            connection.execute(text(
                "DELETE FROM schema_migrations WHERE id IN "
                "('20261101_002_relay_grant_keys', '20261101_003_relay_lease_grants')"
            ))
            connection.execute(text(
                "INSERT INTO relays (id, relay_addr, relay_port, vm_port_range_start, "
                "vm_port_range_count, enabled) VALUES ('site-a', '203.0.113.9', 7000, "
                "6100, 100, 1)"
            ))

        run_migrations(engine)

        names = {c["name"] for c in inspect(engine).get_columns("relays")}
        assert set(_GRANT_KEY_COLUMNS) <= names
        lease_names = {c["name"] for c in inspect(engine).get_columns("relay_port_leases")}
        assert set(_LEASE_GRANT_COLUMNS) <= lease_names
        assert {c["name"] for c in inspect(engine).get_columns("relay_retired_grant_keys")} == {
            "relay_id",
            "key_id",
            "retired_at",
        }
        with engine.begin() as connection:
            assert connection.execute(
                text("SELECT grant_key_id FROM relays WHERE id = 'site-a'")
            ).scalar_one() is None
        check_schema_version(engine)
        engine.dispose()
