"""Compute provisioning's chain against the schema the v0.3.0 release built.

The floor fixture was written by that release's own migration command on a
fresh database (``tests/fixtures/v0_3_0_floor``). The baselines alone must
reproduce it; a fresh database migrated by the chain must equal a v0.3.0
database adopted and brought forward by the same chain, so the migrations after
the baseline are the only difference from the release; and every table and
column the service's models map must be one the chain creates, since nothing
else creates schema.

External boundary: file-backed SQLite in a temp directory, migrated through the
engine as ``compute-provisioning-migrate`` runs it; no application.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from market_schema_migrations import schema_snapshot
from market_schema_migrations.sqlalchemy_adapter import SqlAlchemyMigrationConnection

from compute_provisioning.hosts.db import Base as HostsBase
from compute_provisioning.jobs.db import Base as JobsBase
from compute_provisioning.relays.db import Base as RelaysBase
from compute_provisioning_service.db.database import migrate_database
from compute_provisioning_service.db.migrations import CHAIN, FLOOR_IDS
from compute_provisioning_service.db.models import Base as ServiceBase
from market_fulfillment.db import Base as FulfillmentBase
from market_resource_pools.db import Base as PoolsBase
from market_site.db import Base as SiteBase
from vm_provisioning_adapter.db import Base as VmBase

from .floor_database import create_floor_database, floor_ids, floor_snapshot


def _snapshot(path: Path) -> dict:
    connection = sqlite3.connect(path)
    try:
        return schema_snapshot(connection)
    finally:
        connection.close()


def _recorded(path: Path) -> set[str]:
    connection = sqlite3.connect(path)
    try:
        return {row[0] for row in connection.execute("SELECT id FROM schema_migrations")}
    finally:
        connection.close()


def test_the_fixture_is_the_snapshot_of_its_own_ddl(tmp_path):
    """The committed snapshot and stored DDL describe one database."""
    assert _snapshot(create_floor_database(tmp_path / "floor.db")) == floor_snapshot()


def test_the_chain_adopts_exactly_the_ids_the_release_recorded():
    assert list(FLOOR_IDS) == floor_ids()
    assert CHAIN.floor_ids == FLOOR_IDS


def test_the_baselines_alone_reproduce_the_v0_3_0_schema(tmp_path):
    path = tmp_path / "baselines.db"
    engine = create_engine(f"sqlite:///{path}")
    try:
        with engine.connect() as connection:
            adapter = SqlAlchemyMigrationConnection(connection)
            for baseline in CHAIN.baselines:
                with adapter.transaction():
                    baseline.apply(connection)
    finally:
        engine.dispose()

    assert _snapshot(path) == floor_snapshot()


def test_a_fresh_chain_is_the_v0_3_0_schema_with_the_later_migrations(tmp_path):
    fresh_path = tmp_path / "fresh.db"
    adopted_path = create_floor_database(tmp_path / "adopted.db")

    fresh = migrate_database(create_engine(f"sqlite:///{fresh_path}"))
    adopted = migrate_database(create_engine(f"sqlite:///{adopted_path}"))

    assert not fresh.adopted
    assert fresh.applied == CHAIN.ids
    # Adoption runs no baseline: it records them, and the migrations after the
    # baseline are all that run.
    assert adopted.adopted
    assert adopted.applied == tuple(m.id for m in CHAIN.migrations)
    assert _snapshot(adopted_path) == _snapshot(fresh_path)
    assert _recorded(adopted_path) == _recorded(fresh_path) == set(CHAIN.ids)
    # The later migrations are what the chain adds to the release's schema.
    assert _snapshot(fresh_path) != floor_snapshot()


def test_adoption_keeps_every_row_the_database_holds(tmp_path):
    path = create_floor_database(tmp_path / "provisioning.db")
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO resource_pools (id, label, provider, enabled, policy_tags) "
            "VALUES ('default', 'Default Pool', 'vm.ansible', 1, '{}')"
        ))
        connection.execute(text(
            "INSERT INTO capacity_reservations (capacity_reservation_id, units, state) "
            "VALUES ('r-1', 1, 'leased')"
        ))

    migrate_database(engine)

    with engine.connect() as connection:
        assert connection.execute(text("SELECT id FROM resource_pools")).all() == [("default",)]
        assert connection.execute(text(
            "SELECT capacity_reservation_id, state, placement_key FROM capacity_reservations"
        )).all() == [("r-1", "leased", None)]


def test_every_mapped_table_and_column_is_one_the_chain_creates(tmp_path):
    """The models are read against the migrated schema and create none of it,
    so a column added to a model without a migration fails here."""
    engine = create_engine(f"sqlite:///{tmp_path / 'provisioning.db'}")
    migrate_database(engine)
    inspector = inspect(engine)
    stored = {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table in inspector.get_table_names()
    }

    missing = []
    for base in (
        PoolsBase, RelaysBase, VmBase, HostsBase, JobsBase, ServiceBase,
        FulfillmentBase, SiteBase,
    ):
        for table in base.metadata.sorted_tables:
            if table.name not in stored:
                missing.append(table.name)
                continue
            missing.extend(
                f"{table.name}.{column.name}"
                for column in table.columns
                if column.name not in stored[table.name]
            )
    assert missing == []
