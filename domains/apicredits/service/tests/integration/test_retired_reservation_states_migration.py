"""Persistence tests for converting reservations stored in a retired state.

A current-schema file-backed database is seeded with reservations in states the
site lifecycle no longer writes, and the service's own migration chain is run
over it. Whether a reservation holds quota is the site ledger's rule,
``HELD_RESERVATION_STATES``, which its debit sums read.
"""

from __future__ import annotations

from market_site.db import HELD_RESERVATION_STATES
from sqlalchemy import create_engine, text

from apicredits_service.db.database import run_migrations
from apicredits_service.db.migrations import _migrate_retired_reservation_states


def _engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'credits.db'}")
    run_migrations(engine)
    return engine


def _insert(engine, reservation_id: str, state: str, *, reason: str | None = None) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO capacity_reservations "
                "(capacity_reservation_id, units, state, offering_mode, failure_reason) "
                "VALUES (:id, 1, :state, 'api_credits', :reason)"
            ),
            {"id": reservation_id, "state": state, "reason": reason},
        )


def _rows(engine) -> dict[str, dict]:
    with engine.begin() as connection:
        rows = connection.execute(
            text(
                "SELECT capacity_reservation_id, state, failure_reason, "
                "failure_message, released_at FROM capacity_reservations"
            )
        ).mappings().all()
    return {row["capacity_reservation_id"]: dict(row) for row in rows}


def test_a_held_reservation_in_a_retired_state_becomes_unmanaged_and_stays_held(
    tmp_path,
) -> None:
    engine = _engine(tmp_path)
    _insert(engine, "issuing", "provisioning")

    _migrate_retired_reservation_states(engine)

    row = _rows(engine)["issuing"]
    assert row["state"] == "unmanaged"
    assert row["state"] in HELD_RESERVATION_STATES
    assert row["failure_reason"] == "retired_state_provisioning"
    assert row["released_at"] is None


def test_a_terminal_reservation_in_a_retired_state_becomes_force_released_and_stays_free(
    tmp_path,
) -> None:
    engine = _engine(tmp_path)
    _insert(engine, "failed", "provisioning_failed", reason="issuance_error")

    _migrate_retired_reservation_states(engine)

    row = _rows(engine)["failed"]
    assert row["state"] == "force_released"
    assert row["state"] not in HELD_RESERVATION_STATES
    assert row["failure_reason"] == "retired_state_provisioning_failed"
    assert "issuance_error" in row["failure_message"]
    assert row["released_at"] is not None


def test_a_database_with_no_retired_state_is_unchanged_and_a_rerun_changes_nothing(
    tmp_path,
) -> None:
    engine = _engine(tmp_path)
    for reservation_id, state in (("held", "reserved"), ("freed", "released")):
        _insert(engine, reservation_id, state)
    untouched = _rows(engine)

    _migrate_retired_reservation_states(engine)
    assert _rows(engine) == untouched

    _insert(engine, "issuing", "provisioning")
    _migrate_retired_reservation_states(engine)
    converted = _rows(engine)
    _migrate_retired_reservation_states(engine)
    assert _rows(engine) == converted


def test_the_service_migration_chain_applies_the_conversion(tmp_path) -> None:
    engine = _engine(tmp_path)
    _insert(engine, "issuing", "provisioning")
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM schema_migrations WHERE id = :id"),
            {"id": "20261028_006_retired_reservation_states"},
        )

    run_migrations(engine)

    assert _rows(engine)["issuing"]["state"] == "unmanaged"
