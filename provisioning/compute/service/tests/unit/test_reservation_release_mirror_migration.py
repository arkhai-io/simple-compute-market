"""DB-level tests for dropping the reservation table's domain-named copy of
its release handle.

Simulates a deployed database by adding the column back via raw SQL onto a
current-schema engine, since the live ORM model no longer defines it, then
migrates and asserts what is dropped and what is kept. The rebuild helper's
own guarantees (indexes, keys, foreign-key children, identifier validation)
are covered by ``test_vm_host_executor_ref_migration.py``.
"""

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from market_site.db import CapacityReservation

from compute_provisioning_service.db.database import run_migrations
from compute_provisioning_service.db.migrations import (
    _migrate_drop_reservation_release_mirror,
)

_MIGRATION_ID = "20260927_001_drop_reservation_release_mirror"
_RETIRED = "vm_remove_job_id"


def _current_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run_migrations(
        engine,
        default_playbook_path="/configured/playbook.yaml",
        default_inventory_group="legacy_hosts",
    )
    return engine


def _add_retired_column(engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(f"ALTER TABLE capacity_reservations ADD COLUMN {_RETIRED} VARCHAR")
        )


def _deployed_engine():
    """A current-schema database still carrying the column, as one migrated
    before this drop existed would."""
    engine = _current_engine()
    _add_retired_column(engine)
    return engine


def _insert(engine, reservation_id: str, handle: str | None) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO capacity_reservations "
                f"(capacity_reservation_id, units, state, offering_mode, "
                f"release_job_id, {_RETIRED}) "
                "VALUES (:id, 1, 'releasing', 'vm', :handle, :handle)"
            ),
            {"id": reservation_id, "handle": handle},
        )


def _columns(engine) -> set[str]:
    with engine.begin() as connection:
        return {
            row[1]
            for row in connection.execute(
                text("PRAGMA table_info(capacity_reservations)")
            ).all()
        }


def _handles(engine) -> dict[str, str | None]:
    with engine.begin() as connection:
        return {
            row[0]: row[1]
            for row in connection.execute(
                text(
                    "SELECT capacity_reservation_id, release_job_id "
                    "FROM capacity_reservations"
                )
            ).all()
        }


def _forget_migration(engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM schema_migrations WHERE id = :id"),
            {"id": _MIGRATION_ID},
        )


class TestDropReservationReleaseMirror:
    def test_the_column_is_dropped_and_every_handle_kept(self):
        engine = _deployed_engine()
        _insert(engine, "r1", "fulfillment-1")
        _insert(engine, "r2", None)

        _migrate_drop_reservation_release_mirror(engine)

        assert _RETIRED not in _columns(engine)
        assert _handles(engine) == {"r1": "fulfillment-1", "r2": None}

    def test_the_current_model_reads_the_migrated_table(self):
        engine = _deployed_engine()
        _insert(engine, "r1", "fulfillment-1")

        _migrate_drop_reservation_release_mirror(engine)

        with Session(engine) as session:
            reservation = session.get(CapacityReservation, "r1")
            assert reservation is not None
            assert reservation.release_job_id == "fulfillment-1"

    def test_a_database_without_the_column_is_unchanged(self):
        engine = _current_engine()
        insert_without_retired = (
            "INSERT INTO capacity_reservations "
            "(capacity_reservation_id, units, state, release_job_id) "
            "VALUES ('r1', 1, 'releasing', 'fulfillment-1')"
        )
        with engine.begin() as connection:
            connection.execute(text(insert_without_retired))
        before = _columns(engine)

        _migrate_drop_reservation_release_mirror(engine)

        assert _columns(engine) == before
        assert _handles(engine) == {"r1": "fulfillment-1"}

    def test_rerunning_is_a_no_op(self):
        engine = _deployed_engine()
        _insert(engine, "r1", "fulfillment-1")

        _migrate_drop_reservation_release_mirror(engine)
        after_first = _columns(engine)
        _migrate_drop_reservation_release_mirror(engine)

        assert _columns(engine) == after_first
        assert _handles(engine) == {"r1": "fulfillment-1"}

    def test_run_migrations_applies_the_drop_to_a_database_that_has_not_recorded_it(
        self,
    ):
        engine = _deployed_engine()
        _insert(engine, "r1", "fulfillment-1")
        _forget_migration(engine)

        run_migrations(
            engine,
            default_playbook_path="/configured/playbook.yaml",
            default_inventory_group="legacy_hosts",
        )

        assert _RETIRED not in _columns(engine)
        assert _handles(engine) == {"r1": "fulfillment-1"}

    def test_a_column_re_added_for_rollback_survives_a_later_migration_run(self):
        """Rolling back past the drop means re-adding the column empty. Once
        the drop is recorded, returning to this release leaves that column
        in place rather than rebuilding the table a second time."""
        engine = _current_engine()
        _add_retired_column(engine)

        run_migrations(
            engine,
            default_playbook_path="/configured/playbook.yaml",
            default_inventory_group="legacy_hosts",
        )

        assert _RETIRED in _columns(engine)
        with Session(engine) as session:
            assert session.query(CapacityReservation).all() == []
