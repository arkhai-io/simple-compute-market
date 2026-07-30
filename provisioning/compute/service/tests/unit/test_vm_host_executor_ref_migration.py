"""DB-level tests for retiring capacity_reservations.vm_host in favor of
the generic executor_ref JSON field.

Simulates a pre-migration production database (a real vm_host column,
populated) by adding the column back via raw SQL onto an
already-current-schema engine, since the live ORM model no longer defines
it -- then runs the migration function directly and asserts the
backfill+drop behavior.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from compute_provisioning_service.db.database import run_migrations
from compute_provisioning_service.db.migrations import (
    _migrate_capacity_reservations_vm_host_to_executor_ref,
)

_PLAYBOOK_PATH = "/configured/playbook.yaml"
_INVENTORY_GROUP = "legacy_hosts"


def _sqlite_memory_engine():
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _bootstrap_engine_with_legacy_vm_host_column():
    """A fresh current-schema engine, with a real vm_host column added
    back via raw SQL and populated -- simulating an already-deployed
    database from before this migration existed."""
    engine = _sqlite_memory_engine()
    run_migrations(
        engine,
        default_playbook_path=_PLAYBOOK_PATH,
        default_inventory_group=_INVENTORY_GROUP,
    )
    with engine.begin() as connection:
        connection.execute(text(
            "ALTER TABLE capacity_reservations ADD COLUMN vm_host VARCHAR"
        ))
    return engine


def _insert_reservation(
    engine, *, capacity_reservation_id: str, vm_host: str | None,
    executor_ref: dict | None,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO capacity_reservations "
                "(capacity_reservation_id, units, state, vm_host, executor_ref) "
                "VALUES (:id, 1, 'reserved', :vm_host, :executor_ref)"
            ),
            {
                "id": capacity_reservation_id,
                "vm_host": vm_host,
                "executor_ref": json.dumps(executor_ref) if executor_ref is not None else None,
            },
        )


def _row(engine, capacity_reservation_id: str) -> dict:
    with engine.begin() as connection:
        result = connection.execute(
            text(
                "SELECT * FROM capacity_reservations WHERE capacity_reservation_id = :id"
            ),
            {"id": capacity_reservation_id},
        )
        row = result.mappings().first()
        return dict(row) if row else {}


class TestVmHostBackfill:
    def test_backfills_vm_host_into_fresh_executor_ref(self):
        engine = _bootstrap_engine_with_legacy_vm_host_column()
        _insert_reservation(
            engine, capacity_reservation_id="r1", vm_host="kvm1", executor_ref=None,
        )

        _migrate_capacity_reservations_vm_host_to_executor_ref(engine)

        row = _row(engine, "r1")
        assert "vm_host" not in row  # column dropped
        assert json.loads(row["executor_ref"]) == {"vm_host": "kvm1"}

    def test_merges_into_existing_executor_ref_rather_than_overwriting(self):
        engine = _bootstrap_engine_with_legacy_vm_host_column()
        _insert_reservation(
            engine, capacity_reservation_id="r2", vm_host="kvm2",
            executor_ref={"some_other_key": "keep-me"},
        )

        _migrate_capacity_reservations_vm_host_to_executor_ref(engine)

        row = _row(engine, "r2")
        merged = json.loads(row["executor_ref"])
        assert merged == {"some_other_key": "keep-me", "vm_host": "kvm2"}

    def test_null_vm_host_leaves_executor_ref_untouched(self):
        engine = _bootstrap_engine_with_legacy_vm_host_column()
        _insert_reservation(
            engine, capacity_reservation_id="r3", vm_host=None, executor_ref=None,
        )

        _migrate_capacity_reservations_vm_host_to_executor_ref(engine)

        row = _row(engine, "r3")
        assert row["executor_ref"] is None

    def test_does_not_overwrite_an_already_present_vm_host_key(self):
        """If executor_ref already carries a (possibly different) vm_host
        -- e.g. a row already migrated by a prior partial run -- the
        backfill must not clobber it."""
        engine = _bootstrap_engine_with_legacy_vm_host_column()
        _insert_reservation(
            engine, capacity_reservation_id="r4", vm_host="kvm-stale",
            executor_ref={"vm_host": "kvm-current"},
        )

        _migrate_capacity_reservations_vm_host_to_executor_ref(engine)

        row = _row(engine, "r4")
        assert json.loads(row["executor_ref"]) == {"vm_host": "kvm-current"}

    def test_is_idempotent(self):
        engine = _bootstrap_engine_with_legacy_vm_host_column()
        _insert_reservation(
            engine, capacity_reservation_id="r5", vm_host="kvm5", executor_ref=None,
        )
        _migrate_capacity_reservations_vm_host_to_executor_ref(engine)
        # Column is already gone; a second call must be a clean no-op,
        # not an error.
        _migrate_capacity_reservations_vm_host_to_executor_ref(engine)

        row = _row(engine, "r5")
        assert json.loads(row["executor_ref"]) == {"vm_host": "kvm5"}

    def test_no_op_on_a_database_that_never_had_the_column(self):
        """A database created fresh from the current ORM model never had
        vm_host at all -- the migration must not error."""
        engine = _sqlite_memory_engine()
        run_migrations(
            engine,
            default_playbook_path=_PLAYBOOK_PATH,
            default_inventory_group=_INVENTORY_GROUP,
        )
        # No exception, and it's already covered by run_migrations's own
        # invocation of this migration during bootstrap above -- calling
        # it again here proves the explicit no-op path too.
        _migrate_capacity_reservations_vm_host_to_executor_ref(engine)


class TestTableRebuildPreservesIndexesAndConstraints:
    """_drop_columns_via_table_rebuild does a full create/copy/drop/rename
    cycle rather than ALTER TABLE ... DROP COLUMN (deterministic across
    every supported SQLite version, not best-effort) -- these tests prove
    the rebuild doesn't lose the things a naive rebuild could drop:
    named indexes, the primary key, NOT NULL columns, and unrelated data.
    """

    def test_named_indexes_survive_the_rebuild(self):
        engine = _bootstrap_engine_with_legacy_vm_host_column()
        before = {
            name for (name,) in engine.connect().execute(text(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'index' AND tbl_name = 'capacity_reservations' "
                "AND sql IS NOT NULL"
            )).fetchall()
        }
        assert before, "test setup didn't actually have named indexes to prove survive"

        _migrate_capacity_reservations_vm_host_to_executor_ref(engine)

        after = {
            name for (name,) in engine.connect().execute(text(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'index' AND tbl_name = 'capacity_reservations' "
                "AND sql IS NOT NULL"
            )).fetchall()
        }
        assert after == before

        # And the index is not just present but still queryable/correct:
        # a lookup by escrow_uid (one of the indexed columns) still finds
        # the row after the rebuild.
        engine.connect().execute(text(
            "INSERT INTO capacity_reservations "
            "(capacity_reservation_id, units, state, escrow_uid) "
            "VALUES ('r-idx', 1, 'reserved', 'esc-idx')"
        )).connection.commit()
        found = engine.connect().execute(text(
            "SELECT capacity_reservation_id FROM capacity_reservations "
            "WHERE escrow_uid = 'esc-idx'"
        )).fetchall()
        assert [row[0] for row in found] == ["r-idx"]

    def test_primary_key_and_not_null_columns_survive_the_rebuild(self):
        engine = _bootstrap_engine_with_legacy_vm_host_column()
        _migrate_capacity_reservations_vm_host_to_executor_ref(engine)

        with engine.connect() as connection:
            columns = connection.execute(
                text("PRAGMA table_info(capacity_reservations)")
            ).fetchall()
        by_name = {c[1]: c for c in columns}
        assert by_name["capacity_reservation_id"][5] == 1  # pk flag
        assert by_name["units"][3] == 1  # notnull flag
        assert by_name["state"][3] == 1

        # A duplicate primary key must still be rejected post-rebuild.
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO capacity_reservations "
                "(capacity_reservation_id, units, state) "
                "VALUES ('dup', 1, 'reserved')"
            ))
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO capacity_reservations "
                    "(capacity_reservation_id, units, state) "
                    "VALUES ('dup', 1, 'reserved')"
                ))

    def test_unrelated_rows_and_columns_are_untouched_by_the_rebuild(self):
        """A row with no vm_host at all, and a row's other columns, must
        come through the rebuild exactly as they were."""
        engine = _bootstrap_engine_with_legacy_vm_host_column()
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO capacity_reservations "
                "(capacity_reservation_id, units, state, escrow_uid, "
                "vm_host, failure_reason) "
                "VALUES ('r-untouched', 3, 'committed', 'esc-x', NULL, 'oops')"
            ))

        _migrate_capacity_reservations_vm_host_to_executor_ref(engine)

        row = _row(engine, "r-untouched")
        assert row["units"] == 3
        assert row["state"] == "committed"
        assert row["escrow_uid"] == "esc-x"
        assert row["failure_reason"] == "oops"
        assert "vm_host" not in row

    def test_refuses_to_drop_every_column(self):
        from compute_provisioning_service.db.migrations import (
            _drop_columns_via_table_rebuild,
        )

        engine = _sqlite_memory_engine()
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE only_one_column (junk VARCHAR)"
            ))
        with pytest.raises(ValueError):
            _drop_columns_via_table_rebuild(engine, "only_one_column", ["junk"])

