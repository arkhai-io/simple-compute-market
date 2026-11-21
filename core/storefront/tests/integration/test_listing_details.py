"""A listing's seller-authored details on the storefront's own listing row.

A real SQLite database migrated through core's chain: the columns are the
migration's, the writes and reads are the client's own SQL, and the fan-out
reads the stored row back and builds each registry's request with the real
``ListingRequest``, the registry client standing where publication injects it.
"""

from __future__ import annotations

import base64
import dataclasses
import sqlite3
from typing import Any

from market_identity import Identity, IdentityScheme
from market_schema_migrations import SqliteMigrationConnection, migrate
from registry_client import ListingRequest

from core_storefront.registry_publication import publish_listing_to_registries
from core_storefront.sqlite_client import SQLiteClient
from core_database import CORE_CHAIN, core_database

_SELLER = Identity(
    scheme=IdentityScheme.ED25519,
    identifier=base64.urlsafe_b64encode(bytes([0x11]) * 32).rstrip(b"=").decode(),
)
_STOREFRONT = "https://seller.example"
_DETAILS = {
    "title": "Two H100s in Frankfurt",
    "description": "Dedicated hosts; NVMe scratch is wiped between deals.",
    "metadata": {"acme.tier": "gold", "rack": 7, "ecc": True, "uptime": 99.95},
}
_DETAIL_COLUMNS = ("title", "description", "metadata")


async def _save(client: SQLiteClient, listing_id: str, **details: Any) -> None:
    await client.upsert_listing(
        listing_id=listing_id,
        status="open",
        created_at="2026-11-18T00:00:00Z",
        updated_at="2026-11-18T00:00:00Z",
        listing_resource={"resource_type": "compute.gpu", "offering_mode": "vm"},
        fulfillment_resource=None,
        max_duration_seconds=3600,
        storefront_url=_STOREFRONT,
        seller_principal=_SELLER,
        **details,
    )


def _listing_columns(connection: sqlite3.Connection) -> set[str]:
    return {row[1] for row in connection.execute("PRAGMA table_info(listings)")}


def test_the_migration_adds_the_columns_to_the_previous_head(tmp_path) -> None:
    """A database at the chain's head before the detail migration gains the
    three columns, and the listing it already holds states none."""
    connection = sqlite3.connect(tmp_path / "upgraded.db")
    try:
        ids = [migration.id for migration in CORE_CHAIN.migrations]
        before = dataclasses.replace(
            CORE_CHAIN,
            migrations=CORE_CHAIN.migrations[: ids.index("20261118_001_listing_details")],
        )
        migrate(before, SqliteMigrationConnection(connection))
        assert not _listing_columns(connection) & set(_DETAIL_COLUMNS)
        with connection:
            connection.execute(
                "INSERT INTO listings (listing_id, status, created_at, updated_at, "
                "listing_resource, storefront_url, seller_scheme, seller_identifier) "
                "VALUES ('L1', 'open', 'c', 'u', '{}', ?, ?, ?)",
                (_STOREFRONT, _SELLER.scheme.value, _SELLER.identifier),
            )

        migrate(CORE_CHAIN, SqliteMigrationConnection(connection))

        assert set(_DETAIL_COLUMNS) <= _listing_columns(connection)
        assert connection.execute(
            "SELECT title, description, metadata FROM listings"
        ).fetchall() == [(None, None, None)]
    finally:
        connection.close()


def test_a_fresh_chain_creates_the_columns(tmp_path) -> None:
    connection = sqlite3.connect(core_database(tmp_path / "fresh.db"))
    try:
        assert set(_DETAIL_COLUMNS) <= _listing_columns(connection)
    finally:
        connection.close()


async def test_a_saved_listing_loads_its_details(tmp_path) -> None:
    client = SQLiteClient(core_database(tmp_path / "storefront.db"))
    await _save(client, "L1", **_DETAILS)
    await _save(client, "L2")

    stated = await client.load_listing(listing_id="L1")
    unstated = await client.load_listing(listing_id="L2")
    listed = {row["listing_id"]: row for row in await client.list_listings()}

    assert {key: stated[key] for key in _DETAIL_COLUMNS} == _DETAILS
    assert {key: unstated[key] for key in _DETAIL_COLUMNS} == dict.fromkeys(
        _DETAIL_COLUMNS
    )
    assert {key: listed["L1"][key] for key in _DETAIL_COLUMNS} == _DETAILS


async def test_an_update_sets_and_clears_each_detail(tmp_path) -> None:
    client = SQLiteClient(core_database(tmp_path / "storefront.db"))
    await _save(client, "L1")

    await client.update_listing(listing_id="L1", **_DETAILS)
    set_row = await client.load_listing(listing_id="L1")
    await client.update_listing(listing_id="L1", title="Renamed")
    renamed = await client.load_listing(listing_id="L1")
    await client.update_listing(listing_id="L1", **dict.fromkeys(_DETAIL_COLUMNS))
    cleared = await client.load_listing(listing_id="L1")

    assert {key: set_row[key] for key in _DETAIL_COLUMNS} == _DETAILS
    # A detail an update does not name keeps its stored value.
    assert {key: renamed[key] for key in _DETAIL_COLUMNS} == {**_DETAILS, "title": "Renamed"}
    assert {key: cleared[key] for key in _DETAIL_COLUMNS} == dict.fromkeys(_DETAIL_COLUMNS)


class _Registries:
    """The registry client publication is injected with, answering success."""

    urls = ["http://registry-a.test", "http://registry-b.test"]

    def __init__(self) -> None:
        self.sent: dict[str, dict[str, Any]] = {}

    async def __aenter__(self) -> "_Registries":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None

    async def publish_listing_per_registry(self, *, payloads):
        self.sent = {url: request.to_dict() for url, request in payloads.items()}
        return [
            {"registry_url": url, "success": True, "error": None} for url in payloads
        ]


async def _published(client: SQLiteClient, listing_id: str) -> dict[str, dict[str, Any]]:
    registries = _Registries()
    result = await publish_listing_to_registries(
        await client.load_listing(listing_id=listing_id),
        enabled=True,
        registry_client_factory=lambda: registries,
        listing_request_factory=ListingRequest,
        storefront_url=_STOREFRONT,
    )
    assert result == {"status": "published", "listing_id": listing_id}
    return registries.sent


async def test_publication_sends_only_the_stated_details_to_every_registry(
    tmp_path,
) -> None:
    client = SQLiteClient(core_database(tmp_path / "storefront.db"))
    await _save(client, "all", **_DETAILS)
    await _save(client, "title-only", title=_DETAILS["title"])
    await _save(client, "none")

    every = await _published(client, "all")
    title_only = await _published(client, "title-only")
    none = await _published(client, "none")

    assert sorted(every) == sorted(_Registries.urls)
    for sent in (every, title_only, none):
        assert sent.keys() == set(_Registries.urls)
    for body in every.values():
        assert {key: body[key] for key in _DETAIL_COLUMNS} == _DETAILS
    for body in title_only.values():
        assert body["title"] == _DETAILS["title"]
        assert "description" not in body and "metadata" not in body
    for body in none.values():
        assert not body.keys() & set(_DETAIL_COLUMNS)
