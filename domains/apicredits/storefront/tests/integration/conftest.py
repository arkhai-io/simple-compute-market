"""Fixtures for API-credit tests against a real SQLite database."""

from __future__ import annotations

import market_policy.negotiation_thread as thread_module
import pytest
from apicredits_storefront import container, server
from apicredits_storefront.container import storefront_sqlite_client
from market_policy.identity import Identity
from market_policy.negotiation_thread import get_thread_store

from tests.integration.credit_negotiation import FakeCapacity, anvil_chain, seed_listing


@pytest.fixture
def fake_capacity(monkeypatch):
    capacity = FakeCapacity()

    monkeypatch.setattr(container.QUOTA_CAPACITY, "client", lambda factory: capacity)
    return capacity


@pytest.fixture
def key_records(monkeypatch):
    records: dict[str, dict | None] = {}

    async def _lookup(key_id: str):
        return records.get(key_id)

    monkeypatch.setattr(server, "lookup_key_record", _lookup)
    return records


@pytest.fixture
async def db(tmp_path):
    client = storefront_sqlite_client(db_path=str(tmp_path / "credits-storefront.db"))
    thread_module._thread_store = None
    get_thread_store(
        sqlite_client=client,
        identity=Identity(agent_url="http://test-seller:8002"),
    )
    await seed_listing(client)
    with anvil_chain():
        yield client
    thread_module._thread_store = None
