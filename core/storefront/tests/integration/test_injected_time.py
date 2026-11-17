"""The store's read times come from the process time source.

Library integration: core's client over a real SQLite file its migration chain
built. Escrows are listed oldest first and by their last change, a thread's last
change decides whether the stale-negotiation sweep abandons it, credentials and
stage events are read in time order. Under an injected source each of those
columns holds the source's instant, never a read of the wall clock.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import datetime, timezone

import injected_time
import pytest
from injected_time import InjectedTime
from market_identity import Ed25519Signer

from core_database import core_database
from core_storefront.sqlite_client import SQLiteClient
from core_storefront.stage_log import set_stage_event_db_path, stage_event

INSTANT = 1794821400
#: The instant as the store's text timestamps hold it: UTC, with no offset.
STORED = "2026-11-16T09:30:00"

#: Development keys, never used on a public network.
_BUYER = Ed25519Signer(b"\x61" * 32).identity
_SELLER = Ed25519Signer(b"\x62" * 32).identity


@pytest.fixture
def source() -> Iterator[InjectedTime]:
    before = injected_time.installed()
    installed = InjectedTime(start=INSTANT)
    injected_time.install(installed)
    yield installed
    injected_time.install(before)


@pytest.fixture
def client(tmp_path) -> Iterator[SQLiteClient]:
    client = SQLiteClient(core_database(tmp_path / "storefront.db"))
    set_stage_event_db_path(client.db_path)
    yield client
    set_stage_event_db_path(None)


def _row(client: SQLiteClient, sql: str, *args: object) -> tuple:
    with sqlite3.connect(client.db_path) as conn:
        return conn.execute(sql, args).fetchone()


def test_the_stored_form_is_the_instant_in_utc() -> None:
    assert datetime.fromisoformat(STORED).replace(tzinfo=timezone.utc).timestamp() == INSTANT


async def test_an_escrow_holds_the_injected_instant(source, client) -> None:
    await client.insert_escrow(
        escrow_uid="escrow-1", negotiation_id="neg-1", chain_name=None, escrow_address=None
    )
    assert _row(
        client, "SELECT created_at, updated_at FROM escrows WHERE escrow_uid = ?", "escrow-1"
    ) == (STORED, STORED)

    source.set(INSTANT + 600)
    await client.update_escrow(escrow_uid="escrow-1", reason="checked")
    assert _row(
        client, "SELECT created_at, updated_at FROM escrows WHERE escrow_uid = ?", "escrow-1"
    ) == (STORED, "2026-11-16T09:40:00")


async def test_a_threads_last_change_holds_the_injected_instant(source, client) -> None:
    with sqlite3.connect(client.db_path) as conn:
        conn.execute(
            "INSERT INTO negotiation_threads (negotiation_id, our_listing_id, buyer_scheme, "
            "buyer_identifier, seller_scheme, seller_identifier, updated_at) "
            "VALUES ('neg-1', 'listing-1', ?, ?, ?, ?, '2026-01-01T00:00:00')",
            (_BUYER.scheme.value, _BUYER.identifier, _SELLER.scheme.value, _SELLER.identifier),
        )

    await client.update_negotiation_thread_terminal(
        negotiation_id="neg-1", terminal_state="abandoned"
    )

    assert _row(
        client, "SELECT updated_at FROM negotiation_threads WHERE negotiation_id = ?", "neg-1"
    ) == (STORED,)


async def test_a_credential_holds_the_injected_instant(source, client) -> None:
    await client.store_credential(listing_id="listing-1", role="tenant", granted_to="buyer")

    assert _row(
        client, "SELECT created_at FROM credentials WHERE listing_id = ?", "listing-1"
    ) == (STORED,)


def test_stage_events_hold_the_injected_instant(source, client) -> None:
    for event in ("first", "second", "third"):
        stage_event("negotiation", event, negotiation_id="neg-1")

    with sqlite3.connect(client.db_path) as conn:
        rows = conn.execute("SELECT ts, event FROM stage_events ORDER BY id").fetchall()
    assert rows == [(f"{STORED}+00:00", event) for event in ("first", "second", "third")]
