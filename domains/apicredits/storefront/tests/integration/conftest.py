"""Fixtures for API-credit tests against a real SQLite database."""

from __future__ import annotations

import market_policy.negotiation_thread as thread_module
import pytest
from apicredits_storefront import negotiation_runtime as runtime_module
from apicredits_storefront.utils.sqlite_client import SQLiteClient
from market_policy.identity import Identity
from market_policy.negotiation_thread import get_thread_store

from tests.integration.credit_negotiation import FakeCapacity, seed_listing


@pytest.fixture
def fake_capacity(monkeypatch):
    capacity = FakeCapacity()

    monkeypatch.setattr(
        runtime_module,
        "build_capacity_client",
        lambda factory: capacity,
    )
    return capacity


@pytest.fixture
def key_records(monkeypatch):
    records: dict[str, dict | None] = {}

    async def _lookup(key_id: str):
        return records.get(key_id)

    monkeypatch.setattr(runtime_module, "lookup_key_record", _lookup)
    return records


@pytest.fixture
async def db(tmp_path):
    client = SQLiteClient(db_path=str(tmp_path / "credits-storefront.db"))
    thread_module._thread_store = None
    get_thread_store(
        sqlite_client=client,
        identity=Identity(agent_url="http://test-seller:8002"),
    )
    await seed_listing(client)
    yield client
    thread_module._thread_store = None
