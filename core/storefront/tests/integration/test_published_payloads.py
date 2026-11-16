"""Each registry's last successfully published payload for a listing.

A real SQLite database migrated through core's chain: the rule is the upsert's
own SQL, which keeps the published payload unless a write supplies one.
"""

from __future__ import annotations

import dataclasses
import sqlite3

import pytest
from market_schema_migrations import SqliteMigrationConnection, migrate

from core_storefront.sqlite_client import SQLiteClient
from core_database import CORE_CHAIN, core_database

_ACCEPTED = {"listing_id": "L1", "pricing": {"rate_structure": {"cpu": []}}}


@pytest.fixture
def client(tmp_path) -> SQLiteClient:
    return SQLiteClient(core_database(tmp_path / "storefront.db"))


async def test_a_failed_attempt_keeps_the_last_published_payload(client):
    await client.upsert_publication(
        listing_id="L1", registry_url="http://r1", payload=_ACCEPTED,
        status="published", published_payload=_ACCEPTED,
    )
    await client.upsert_publication(
        listing_id="L1", registry_url="http://r1", payload={"listing_id": "L1", "v": 2},
        status="failed", last_error="registry unavailable",
    )

    row = await client.load_publication(listing_id="L1", registry_url="http://r1")
    assert row["status"] == "failed"
    assert row["payload"] == {"listing_id": "L1", "v": 2}
    assert await client.load_published_payloads(listing_id="L1") == {
        "http://r1": _ACCEPTED
    }


async def test_an_accepted_publish_replaces_it(client):
    replaced = {"listing_id": "L1", "pricing": {"rate_structure": {"gpu": []}}}
    for payload in (_ACCEPTED, replaced):
        await client.upsert_publication(
            listing_id="L1", registry_url="http://r1", payload=payload,
            status="published", published_payload=payload,
        )

    assert await client.load_published_payloads(listing_id="L1") == {
        "http://r1": replaced
    }


async def test_a_registry_that_never_accepted_a_publish_is_absent(client):
    await client.upsert_publication(
        listing_id="L1", registry_url="http://r1", payload=_ACCEPTED,
        status="published", published_payload=_ACCEPTED,
    )
    await client.upsert_publication(
        listing_id="L1", registry_url="http://r2", payload=_ACCEPTED,
        status="failed", last_error="registry unavailable",
    )

    assert await client.load_published_payloads(listing_id="L1") == {
        "http://r1": _ACCEPTED
    }
    assert await client.load_published_payloads(listing_id="L2") == {}


def test_the_migration_adds_the_column_and_backfills_no_row(tmp_path) -> None:
    """A row recorded before the column exists has no published payload."""
    path = tmp_path / "upgraded.db"
    connection = sqlite3.connect(path)
    try:
        # The chain as it stood before the column: every migration after it is
        # dropped too, so the upgrade applies them in their real order.
        ids = [migration.id for migration in CORE_CHAIN.migrations]
        before = dataclasses.replace(
            CORE_CHAIN,
            migrations=CORE_CHAIN.migrations[
                : ids.index("20261111_001_publication_published_payload")
            ],
        )
        migrate(before, SqliteMigrationConnection(connection))
        with connection:
            connection.execute(
                "INSERT INTO publications (listing_id, registry_url, payload_json, "
                "published_at, status) VALUES ('L1', 'http://r1', '{}', 1, 'published')"
            )
        migrate(CORE_CHAIN, SqliteMigrationConnection(connection))
        assert connection.execute(
            "SELECT published_payload_json FROM publications"
        ).fetchall() == [(None,)]
    finally:
        connection.close()
