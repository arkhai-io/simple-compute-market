"""DB-level tests for renaming ``listings.offer_resource`` to
``listings.listing_resource`` and moving the offering mode onto its settled
key inside the stored payload.

Simulates a pre-migration production database by creating the retired column
and payload key via raw SQL, since the live schema defines neither, then runs
the migration directly.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from core_storefront.sqlite_migrations import (
    count_listings_carrying_retired_offering_mode_key,
    migrate_listing_resource_column,
)


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE listings (
          listing_id TEXT PRIMARY KEY,
          status TEXT NOT NULL,
          offer_resource TEXT NOT NULL
        )
        """
    )
    yield connection
    connection.close()


def _listing(conn, listing_id, payload):
    conn.execute(
        "INSERT INTO listings VALUES (?, 'open', ?)",
        (listing_id, json.dumps(payload, sort_keys=True)),
    )


def _columns(conn):
    return [str(row[1]) for row in conn.execute("PRAGMA table_info(listings)")]


def _payload(conn, listing_id):
    raw = conn.execute(
        "SELECT listing_resource FROM listings WHERE listing_id=?", (listing_id,)
    ).fetchone()[0]
    return json.loads(raw)


class TestColumnRename:
    def test_the_column_moves_and_values_survive(self, conn):
        _listing(conn, "L1", {"gpu_model": "H200"})

        migrate_listing_resource_column(conn)

        columns = _columns(conn)
        assert "listing_resource" in columns
        assert "offer_resource" not in columns
        assert _payload(conn, "L1") == {"gpu_model": "H200"}

    def test_rerunning_is_a_no_op(self, conn):
        _listing(conn, "L1", {"gpu_model": "H200"})

        migrate_listing_resource_column(conn)
        migrate_listing_resource_column(conn)

        assert _payload(conn, "L1") == {"gpu_model": "H200"}

    def test_an_absent_table_is_tolerated(self):
        empty = sqlite3.connect(":memory:")
        migrate_listing_resource_column(empty)  # must not raise
        empty.close()


class TestNestedOfferingModeBackfill:
    """The payload half runs in the same migration as the column rename.

    A row must never be observable with the column migrated and its payload
    not: the payload's mode is read back as the listing's offering mode, so a
    half-migrated row would publish a listing whose mode looks absent and
    would silently fail an offering-mode filter rather than erroring.
    """

    def test_the_retired_key_moves(self, conn):
        _listing(conn, "L1", {"gpu_model": "H200", "virtualization_type": "vm"})

        migrate_listing_resource_column(conn)

        assert _payload(conn, "L1") == {"gpu_model": "H200", "offering_mode": "vm"}

    def test_a_payload_already_settled_is_untouched(self, conn):
        _listing(conn, "L1", {"gpu_model": "A100", "offering_mode": "bare_metal"})

        migrate_listing_resource_column(conn)

        assert _payload(conn, "L1") == {
            "gpu_model": "A100",
            "offering_mode": "bare_metal",
        }

    def test_a_payload_carrying_both_keeps_the_settled_value(self, conn):
        """The settled value is the one a live publication wrote; the retired
        key is the stale copy."""
        _listing(
            conn, "L1",
            {"offering_mode": "vm", "virtualization_type": "container"},
        )

        migrate_listing_resource_column(conn)

        assert _payload(conn, "L1") == {"offering_mode": "vm"}

    def test_an_unparseable_payload_is_left_exactly_as_stored(self, conn):
        """It is the seller's published shape, and this migration has no basis
        for rewriting something it cannot read."""
        conn.execute("INSERT INTO listings VALUES ('L1', 'open', 'not json')")

        migrate_listing_resource_column(conn)

        raw = conn.execute(
            "SELECT listing_resource FROM listings WHERE listing_id='L1'"
        ).fetchone()[0]
        assert raw == "not json"


class TestCutoverGate:
    def test_the_count_is_meaningful_before_the_rename(self, conn):
        """Reading only the settled column would report zero on a database
        that has not been migrated at all -- the exact state the gate exists
        to catch."""
        _listing(conn, "L1", {"virtualization_type": "vm"})
        _listing(conn, "L2", {"offering_mode": "vm"})

        assert count_listings_carrying_retired_offering_mode_key(conn) == 1

    def test_the_count_reaches_zero_after_the_migration(self, conn):
        _listing(conn, "L1", {"virtualization_type": "vm"})
        _listing(conn, "L2", {"virtualization_type": "bare_metal"})
        _listing(conn, "L3", {"offering_mode": "vm"})

        assert count_listings_carrying_retired_offering_mode_key(conn) == 2

        migrate_listing_resource_column(conn)

        assert count_listings_carrying_retired_offering_mode_key(conn) == 0

    def test_an_absent_table_counts_zero_rather_than_raising(self):
        empty = sqlite3.connect(":memory:")
        assert count_listings_carrying_retired_offering_mode_key(empty) == 0
        empty.close()
