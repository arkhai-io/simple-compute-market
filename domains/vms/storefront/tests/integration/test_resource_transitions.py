"""A resource state transition records its event and its row change together."""

from __future__ import annotations

import sqlite3

import pytest

from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    build_vm_storefront_registry,
)
from market_storefront.utils.sqlite_client import SQLiteClient


@pytest.fixture
def client(tmp_path) -> SQLiteClient:
    return SQLiteClient(
        db_path=str(tmp_path / "transitions.db"),
        registry=build_vm_storefront_registry(build_vm_storefront_domain()),
    )


def _events(client: SQLiteClient) -> list[tuple]:
    conn = sqlite3.connect(client.db_path)
    try:
        return conn.execute(
            "SELECT event_id, resource_id, event_type, set_state, idempotency_key"
            " FROM resource_transition_events ORDER BY pk"
        ).fetchall()
    finally:
        conn.close()


def _state(client: SQLiteClient, resource_id: str) -> tuple[str, str]:
    conn = sqlite3.connect(client.db_path)
    try:
        return conn.execute(
            "SELECT state, updated_at FROM resources WHERE resource_id = ?",
            (resource_id,),
        ).fetchone()
    finally:
        conn.close()


async def _release(client: SQLiteClient, resource_id: str, key: str) -> dict:
    return await client.apply_resource_transition(
        resource_id=resource_id,
        event_type="reservation_released_by_admin",
        idempotency_key=key,
        set_state="available",
    )


async def test_a_transition_records_one_event_and_sets_the_state(client):
    await client.upsert_resource(resource_id="r1", resource_type="compute.gpu", state="leased")

    result = await _release(client, "r1", "release-r1")

    assert result["applied"] is True and result["duplicate"] is False
    assert _state(client, "r1")[0] == "available"
    assert _events(client) == [
        (result["event_id"], "r1", "reservation_released_by_admin", "available", "release-r1")
    ]


async def test_a_repeated_idempotency_key_changes_nothing(client):
    await client.upsert_resource(resource_id="r1", resource_type="compute.gpu", state="leased")
    first = await _release(client, "r1", "release-r1")
    await client.upsert_resource(resource_id="r1", resource_type="compute.gpu", state="leased")
    row_before = _state(client, "r1")

    again = await _release(client, "r1", "release-r1")

    assert again["applied"] is False and again["duplicate"] is True
    assert _state(client, "r1") == row_before
    assert [event[0] for event in _events(client)] == [first["event_id"]]


async def test_a_missing_resource_raises_and_leaves_no_event(client):
    with pytest.raises(ValueError, match="Resource not found: ghost"):
        await _release(client, "ghost", "release-ghost")

    assert _events(client) == []
