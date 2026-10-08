"""The capacity declaration contract migration.

Stored declarations gain the two current rules: every declaration names its
pool, and the legacy scalar ``total_units`` may be absent. The table is
rebuilt because SQLite cannot relax ``NOT NULL`` in place, so these tests
also prove the rebuild keeps what a rebuild most easily loses: its unique
constraints and the foreign key another table holds on it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from market_site import CapacityLedgerService

from compute_provisioning_service.db.migrations import apply_schema_migrations

_PREVIOUS_SCHEMA = Path(__file__).parent / "fixtures" / "schema_through_20260911_001.sql"


def _engine_with_the_previous_table():
    """The schema the preceding chain leaves, with two declarations and a debit."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    raw = engine.raw_connection()
    try:
        raw.driver_connection.executescript(_PREVIOUS_SCHEMA.read_text())
    finally:
        raw.close()
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO capacity_buckets (capacity_bucket_id, backing_resource_id, "
            "pool_id, resource_type, total_units, capacity, attributes, enabled, "
            "created_at, updated_at) VALUES "
            "('b1', 'r1', NULL, 'compute.gpu', 4, '{\"gpu_count\": 4}', '{}', 1, "
            "'2026-01-01', '2026-01-01'), "
            "('b2', 'r2', 'pool-a', 'compute.gpu', 2, '{\"gpu_count\": 2}', '{}', 1, "
            "'2026-01-01', '2026-01-01')"
        ))
        connection.execute(text(
            "INSERT INTO capacity_reservations (capacity_reservation_id, units, state, "
            "created_at, updated_at) VALUES ('reservation-1', 1, 'reserved', "
            "'2026-01-01', '2026-01-01')"
        ))
        connection.execute(text(
            "INSERT INTO capacity_reservation_debits (capacity_reservation_id, "
            "capacity_bucket_id, dimensions, created_at, updated_at) VALUES "
            "('reservation-1', 'b1', '{\"gpu_count\": 1}', '2026-01-01', '2026-01-01')"
        ))
    return engine


def _migrate(engine) -> None:
    """Run every migration after the fixture's chain, as a deployment does."""
    apply_schema_migrations(engine)


def _total_units_nullable(engine) -> bool:
    columns = {c["name"]: c for c in inspect(engine).get_columns("capacity_buckets")}
    return columns["total_units"]["nullable"]


def test_a_populated_table_is_migrated_in_place():
    engine = _engine_with_the_previous_table()
    assert not _total_units_nullable(engine)

    _migrate(engine)

    assert _total_units_nullable(engine)
    with engine.begin() as connection:
        rows = dict(connection.execute(text(
            "SELECT backing_resource_id, pool_id FROM capacity_buckets"
        )).all())
        debit = connection.execute(text(
            "SELECT capacity_bucket_id FROM capacity_reservation_debits"
        )).scalar_one()
    # A stored null pool is the default pool, as every reader resolved it.
    assert rows == {"r1": "default", "r2": "pool-a"}
    assert debit == "b1"


def test_the_rebuild_keeps_the_tables_unique_constraints():
    engine = _engine_with_the_previous_table()
    _migrate(engine)

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO capacity_buckets (capacity_bucket_id, backing_resource_id, "
                "pool_id, resource_type, capacity, attributes, enabled) "
                "VALUES ('b3', 'r1', 'default', 'compute.gpu', '{}', '{}', 1)"
            ))
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(text(
                "UPDATE capacity_buckets SET host_id='kvm1'"
            ))


def test_a_declaration_without_a_scalar_total_can_be_stored():
    engine = _engine_with_the_previous_table()
    _migrate(engine)

    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO capacity_buckets (capacity_bucket_id, backing_resource_id, "
            "pool_id, resource_type, total_units, capacity, attributes, enabled) "
            "VALUES ('b3', 'r3', 'default', 'api_credits', NULL, "
            "'{\"tokens\": 1000}', '{}', 1)"
        ))


def test_rerunning_changes_nothing():
    engine = _engine_with_the_previous_table()
    _migrate(engine)
    with engine.begin() as connection:
        before = connection.execute(text(
            "SELECT * FROM capacity_buckets ORDER BY capacity_bucket_id"
        )).all()

    _migrate(engine)

    with engine.begin() as connection:
        after = connection.execute(text(
            "SELECT * FROM capacity_buckets ORDER BY capacity_bucket_id"
        )).all()
    assert after == before


def test_rows_stored_under_the_previous_default_read_as_they_did():
    """The compute composition's mirror is the name the previous code wrote,
    so a row it stored reads identically: a named ``gpu_count`` and an empty
    capacity map (which the previous code, too, read as the scalar total)."""
    engine = _engine_with_the_previous_table()
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO capacity_buckets (capacity_bucket_id, backing_resource_id, "
            "pool_id, resource_type, total_units, capacity, attributes, enabled, "
            "created_at, updated_at) VALUES ('b3', 'r3', 'default', 'compute.gpu', "
            "2, '{}', '{}', 1, '2026-01-01', '2026-01-01')"
        ))
    _migrate(engine)
    ledger = CapacityLedgerService(
        sessionmaker(bind=engine),
        unit_claim_keys=("units", "gpu_count"),
        mirror_dimension="gpu_count",
    )

    by_id = {row["resource_id"]: row for row in ledger.list_resources()}

    for resource_id, units in (("r2", 2), ("r3", 2)):
        row = by_id[resource_id]
        assert row["capacity"] == {"gpu_count": units}
        assert row["value"] == units
        assert row["available_units"] == units
        assert row["available"] == {"gpu_count": units}
