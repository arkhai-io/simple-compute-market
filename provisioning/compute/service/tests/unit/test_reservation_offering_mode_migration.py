"""DB-level tests for moving the reservation's offering mode onto its
settled column name, and the same value onto its settled key inside
persisted scheduling requirements.

Simulates a pre-migration production database by creating the retired
column and payload key via raw SQL, since the live ORM model no longer
defines either -- then runs the migration function directly and asserts
the backfill, the drop, and what must be left alone.
"""

from __future__ import annotations

import json

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from sqlalchemy.orm import Session

from market_fulfillment.db import SettlementRecord

from compute_provisioning_service.db.migrations import (
    _migrate_reservation_offering_mode_name,
    count_rows_carrying_retired_offering_mode_key,
)


def _pre_upgrade_engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE capacity_reservations (
                    capacity_reservation_id VARCHAR PRIMARY KEY,
                    units INTEGER,
                    executor_kind VARCHAR,
                    executor_target VARCHAR,
                    executor_ref JSON,
                    state VARCHAR
                )
                """
            )
        )
    # Created from the live ORM metadata rather than hand-written DDL: only
    # the payload's key changes here, not the table's shape, and a
    # hand-written copy of this schema is free to disagree with the real one
    # -- which is exactly how an earlier draft of this test passed against a
    # column name production does not have.
    SettlementRecord.__table__.create(engine)
    return engine


def _reservation(connection, reservation_id, mode, target=None, ref=None):
    connection.execute(
        text(
            "INSERT INTO capacity_reservations VALUES "
            "(:rid, 1, :mode, :target, :ref, 'reserved')"
        ),
        {"rid": reservation_id, "mode": mode, "target": target, "ref": ref},
    )


def _requirement(engine, reservation_id, payload):
    """Written through the ORM rather than raw SQL, because several columns
    on this table default Python-side and raw SQL bypasses those defaults."""
    with Session(engine) as session:
        session.add(
            SettlementRecord(
                capacity_reservation_id=reservation_id,
                market="vms",
                scheduling_requirements=payload,
            )
        )
        session.commit()


def _columns(engine, table):
    with engine.begin() as connection:
        return [
            row[1]
            for row in connection.execute(text(f"PRAGMA table_info({table})")).all()
        ]


class TestReservationColumnRename:
    def test_values_move_to_the_settled_column_and_the_retired_one_is_dropped(self):
        engine = _pre_upgrade_engine()
        with engine.begin() as connection:
            _reservation(connection, "r1", "vm")
            _reservation(connection, "r2", "bare_metal")

        _migrate_reservation_offering_mode_name(engine)

        columns = _columns(engine, "capacity_reservations")
        assert "offering_mode" in columns
        assert "executor_kind" not in columns
        with engine.begin() as connection:
            rows = dict(
                connection.execute(
                    text(
                        "SELECT capacity_reservation_id, offering_mode "
                        "FROM capacity_reservations"
                    )
                ).all()
            )
        assert rows == {"r1": "vm", "r2": "bare_metal"}

    def test_a_null_mode_stays_null_rather_than_acquiring_a_default(self):
        """The authority never derives the mode from host attributes,
        resource type, or a default, so a row that recorded none must not
        gain one here."""
        engine = _pre_upgrade_engine()
        with engine.begin() as connection:
            _reservation(connection, "r1", None)

        _migrate_reservation_offering_mode_name(engine)

        with engine.begin() as connection:
            assert connection.execute(
                text(
                    "SELECT offering_mode FROM capacity_reservations "
                    "WHERE capacity_reservation_id='r1'"
                )
            ).scalar() is None

    def test_the_retained_executor_compounds_are_left_alone(self):
        """`executor_target` and `executor_ref` name the action-dispatch
        abstraction's own target and reference, not the offering mode, so
        the rename must not reach them."""
        engine = _pre_upgrade_engine()
        with engine.begin() as connection:
            _reservation(
                connection, "r1", "vm",
                target="vm-a", ref=json.dumps({"vm_host": "host-1"}),
            )

        _migrate_reservation_offering_mode_name(engine)

        columns = _columns(engine, "capacity_reservations")
        assert "executor_target" in columns
        assert "executor_ref" in columns
        with engine.begin() as connection:
            target, ref = connection.execute(
                text(
                    "SELECT executor_target, executor_ref FROM capacity_reservations"
                )
            ).one()
        assert target == "vm-a"
        assert json.loads(ref) == {"vm_host": "host-1"}

    def test_rerunning_is_a_no_op(self):
        engine = _pre_upgrade_engine()
        with engine.begin() as connection:
            _reservation(connection, "r1", "vm")

        _migrate_reservation_offering_mode_name(engine)
        _migrate_reservation_offering_mode_name(engine)

        with engine.begin() as connection:
            assert connection.execute(
                text("SELECT offering_mode FROM capacity_reservations")
            ).scalar() == "vm"


class TestSchedulingRequirementsBackfill:
    def test_the_payload_key_moves(self):
        """`SettlementRepository` compares the stored payload structurally
        against a freshly serialized requirement to detect a retried
        request. A payload left under the retired key would not compare
        equal, so a settlement retried across this upgrade would submit a
        second time instead of recognizing its own request.
        """
        engine = _pre_upgrade_engine()
        _requirement(
                engine, "s1",
                {
                    "executor_kind": "vm",
                    "resource_kind": "gpu_host",
                    "dimensions": {"gpu_count": 1},
                },
            )

        _migrate_reservation_offering_mode_name(engine)

        with engine.begin() as connection:
            payload = json.loads(
                connection.execute(
                    text("SELECT scheduling_requirements FROM settlement_records")
                ).scalar()
            )
        assert payload == {
            "offering_mode": "vm",
            "resource_kind": "gpu_host",
            "dimensions": {"gpu_count": 1},
        }

    def test_a_payload_already_settled_is_untouched(self):
        engine = _pre_upgrade_engine()
        _requirement(
                engine, "s1",
                {"offering_mode": "bare_metal", "resource_kind": "machine"},
            )

        _migrate_reservation_offering_mode_name(engine)

        with engine.begin() as connection:
            payload = json.loads(
                connection.execute(
                    text("SELECT scheduling_requirements FROM settlement_records")
                ).scalar()
            )
        assert payload == {"offering_mode": "bare_metal", "resource_kind": "machine"}

    def test_a_payload_carrying_both_keeps_the_settled_value(self):
        """The settled value is the one a live caller serialized; the
        retired key is the stale copy."""
        engine = _pre_upgrade_engine()
        _requirement(
                engine, "s1",
                {"offering_mode": "vm", "executor_kind": "bare_metal"},
            )

        _migrate_reservation_offering_mode_name(engine)

        with engine.begin() as connection:
            payload = json.loads(
                connection.execute(
                    text("SELECT scheduling_requirements FROM settlement_records")
                ).scalar()
            )
        assert payload == {"offering_mode": "vm"}


class TestCutoverGate:
    def test_the_count_reports_stale_rows_before_and_none_after(self):
        engine = _pre_upgrade_engine()
        _requirement(engine, "s1", {"executor_kind": "vm"})
        _requirement(engine, "s2", {"offering_mode": "vm"})
        _requirement(engine, "s3", {"executor_kind": "bare_metal"})

        assert count_rows_carrying_retired_offering_mode_key(engine) == 2

        _migrate_reservation_offering_mode_name(engine)

        assert count_rows_carrying_retired_offering_mode_key(engine) == 0

    def test_an_absent_table_counts_zero_rather_than_raising(self):
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        assert count_rows_carrying_retired_offering_mode_key(engine) == 0
