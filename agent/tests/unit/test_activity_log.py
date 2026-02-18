"""Unit tests for the activity_log table CRUD and activity endpoints."""

import sqlite3
import tempfile
from datetime import datetime

import pytest

from app.utils.sqlite_client import SQLiteClient


@pytest.fixture
def db():
    """Create a fresh SQLiteClient backed by a temp file."""
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        client = SQLiteClient(db_path=f.name)
        yield client


# ------------------------------------------------------------------
# CRUD tests
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_activity(db: SQLiteClient):
    """CRUD: create + retrieve."""
    await db.create_activity(event_id="evt_1", event_type="order_create")
    row = await db.get_activity(event_id="evt_1")
    assert row is not None
    assert row["event_id"] == "evt_1"
    assert row["event_type"] == "order_create"
    assert row["status"] == "queued"
    assert row["order_id"] is None
    assert row["error"] is None


@pytest.mark.asyncio
async def test_activity_status_transitions(db: SQLiteClient):
    """queued -> processing -> completed."""
    await db.create_activity(event_id="evt_2", event_type="order_create")

    await db.update_activity(event_id="evt_2", status="processing")
    row = await db.get_activity(event_id="evt_2")
    assert row["status"] == "processing"

    await db.update_activity(
        event_id="evt_2",
        status="completed",
        order_id="order_abc",
        summary="Processed order_create, order=order_abc",
    )
    row = await db.get_activity(event_id="evt_2")
    assert row["status"] == "completed"
    assert row["order_id"] == "order_abc"
    assert "order_abc" in row["summary"]


@pytest.mark.asyncio
async def test_activity_failed(db: SQLiteClient):
    """Error field populated on failure."""
    await db.create_activity(event_id="evt_3", event_type="order_close")
    await db.update_activity(
        event_id="evt_3", status="failed", error="Something went wrong"
    )
    row = await db.get_activity(event_id="evt_3")
    assert row["status"] == "failed"
    assert row["error"] == "Something went wrong"


@pytest.mark.asyncio
async def test_list_activities_filters(db: SQLiteClient):
    """status/event_type filtering works."""
    await db.create_activity(event_id="a1", event_type="order_create")
    await db.create_activity(event_id="a2", event_type="order_close")
    await db.create_activity(event_id="a3", event_type="order_create")

    await db.update_activity(event_id="a1", status="completed")

    # Filter by status
    completed = await db.list_activities(status="completed")
    assert len(completed) == 1
    assert completed[0]["event_id"] == "a1"

    queued = await db.list_activities(status="queued")
    assert len(queued) == 2

    # Filter by event_type
    creates = await db.list_activities(event_type="order_create")
    assert len(creates) == 2

    closes = await db.list_activities(event_type="order_close")
    assert len(closes) == 1

    # Combined filter
    queued_creates = await db.list_activities(status="queued", event_type="order_create")
    assert len(queued_creates) == 1
    assert queued_creates[0]["event_id"] == "a3"


@pytest.mark.asyncio
async def test_list_activities_limit(db: SQLiteClient):
    """Limit parameter caps results."""
    for i in range(10):
        await db.create_activity(event_id=f"lim_{i}", event_type="order_create")

    limited = await db.list_activities(limit=3)
    assert len(limited) == 3


@pytest.mark.asyncio
async def test_get_activity_not_found(db: SQLiteClient):
    """Retrieving non-existent activity returns None."""
    row = await db.get_activity(event_id="nonexistent")
    assert row is None


@pytest.mark.asyncio
async def test_create_activity_idempotent(db: SQLiteClient):
    """Creating the same event_id twice does not overwrite."""
    await db.create_activity(event_id="dup_1", event_type="order_create")
    await db.update_activity(event_id="dup_1", status="completed")

    # Second create should be a no-op (ON CONFLICT DO NOTHING)
    await db.create_activity(event_id="dup_1", event_type="order_close")
    row = await db.get_activity(event_id="dup_1")
    assert row["status"] == "completed"
    assert row["event_type"] == "order_create"
