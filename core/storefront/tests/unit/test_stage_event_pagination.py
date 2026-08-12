"""A capped stage-event query says when it withheld rows.

The cap has always existed and was applied silently, so a caller receiving the
maximum could not tell a complete history from part of one. That is a poor thing
to be silent about: the reader most likely to hit the cap is the one summarising
everything that happened, which is exactly the reader a partial answer misleads.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

import pytest

from core_storefront.sqlite_client import SQLiteClient


@pytest.fixture
def client(tmp_path) -> SQLiteClient:
    return SQLiteClient(db_path=str(tmp_path / "stage-events.db"))


def _seed(client: SQLiteClient, count: int, *, stage: str = "claims") -> None:
    conn = sqlite3.connect(client.db_path)
    try:
        ts = datetime.now(timezone.utc).isoformat()
        conn.executemany(
            "INSERT INTO stage_events (ts, stage, event, negotiation_id, "
            "listing_id, escrow_uid, data) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (ts, stage, "claim_submitted", None, None, f"0x{i:04x}",
                 json.dumps({"claim_ref": f"0x{i:04x}"}))
                for i in range(count)
            ],
        )
        conn.commit()
    finally:
        conn.close()


class TestTruncationIsReported:
    async def test_a_complete_result_is_not_truncated(self, client):
        _seed(client, 10)

        rows, truncated = await client.list_stage_events_page(limit=100)

        assert len(rows) == 10
        assert truncated is False

    async def test_exactly_the_requested_count_is_not_truncated(self, client):
        """The boundary the flag exists for.

        A caller asking for ten and receiving ten has everything it asked for;
        reporting that as truncated would make the flag useless by firing on the
        commonest complete case.
        """
        _seed(client, 10)

        rows, truncated = await client.list_stage_events_page(limit=10)

        assert len(rows) == 10
        assert truncated is False

    async def test_withheld_rows_are_reported(self, client):
        _seed(client, 12)

        rows, truncated = await client.list_stage_events_page(limit=10)

        assert len(rows) == 10
        assert truncated is True

    async def test_the_page_cap_applies_above_the_requested_limit(self, client):
        """A caller asking for more than the cap gets the cap, and is told.

        Silently returning fewer rows than asked for is the failure mode this
        replaces — over HTTP the request is rejected outright, but every
        in-process caller reaches this path.
        """
        _seed(client, SQLiteClient.STAGE_EVENT_PAGE_LIMIT + 5)

        rows, truncated = await client.list_stage_events_page(limit=100_000)

        assert len(rows) == SQLiteClient.STAGE_EVENT_PAGE_LIMIT
        assert truncated is True

    async def test_the_cap_is_logged_when_it_bites(self, client, caplog):
        _seed(client, 3)

        with caplog.at_level("WARNING"):
            await client.list_stage_events_page(limit=100_000)

        assert any("page cap" in r.getMessage() for r in caplog.records)

    async def test_a_filtered_query_counts_only_matching_rows(self, client):
        """Truncation is about the filtered result, not the table.

        A stage filter that matches ten rows in a table of a thousand is
        complete, and reporting it as truncated would be wrong in the direction
        that makes a caller distrust a good answer.
        """
        _seed(client, 10, stage="claims")
        _seed(client, 600, stage="negotiation")

        rows, truncated = await client.list_stage_events_page(
            limit=100, stage="claims",
        )

        assert len(rows) == 10
        assert truncated is False


class TestRowsOnlyWrapper:
    async def test_it_returns_the_same_rows(self, client):
        _seed(client, 12)

        rows = await client.list_stage_events(limit=10)
        paged, _ = await client.list_stage_events_page(limit=10)

        assert rows == paged
