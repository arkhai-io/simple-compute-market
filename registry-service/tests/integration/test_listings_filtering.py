"""Integration tests for spec-driven filtering on GET /listings.

These exercise the JSONPath-driven evaluator + the ETag-gated query
path that replaced ``matches_resource_filters``.  Uses raw httpx
through ASGITransport so we can hit the new query syntax (arbitrary
filter params + If-Match header) without going through the registry-
client typed surface, which still carries the legacy parameter list
(client gets bumped in a1b-4).
"""

from __future__ import annotations

import httpx
import pytest

from src.api.filter_spec import compute_etag, get_loaded_spec
from src.db.models import Listing, OrderStatusEnum
from src.main import app


@pytest.fixture
def _raw_client(db_session):
    """httpx.AsyncClient over the FastAPI app, sharing the test DB session."""
    from src.db.database import get_db

    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        )
    finally:
        app.dependency_overrides.clear()


def _make_listing(db_session, agent, listing_id: str, **offer_extras) -> Listing:
    offer = {
        "gpu_model": "A100",
        "region": "us-west",
        "gpu_count": 4,
        "ram_gb": 256,
        **offer_extras,
    }
    row = Listing(
        listing_id=listing_id,
        agent_id=agent.agent_id,
        seller="",
        offer_resource=offer,
        accepted_escrows=[{
            "chain_name": "anvil",
            "escrow_address": "0x" + "11" * 20,
            "fields": {"token": "0x" + "ab" * 20},
        }],
        max_duration_seconds=3600,
        status=OrderStatusEnum.open,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


@pytest.mark.asyncio
async def test_gpu_model_filter_narrows_results(_raw_client, db_session, maker_agent):
    _make_listing(db_session, maker_agent, "a100-listing", gpu_model="A100")
    _make_listing(db_session, maker_agent, "h200-listing", gpu_model="H200")

    async with _raw_client as c:
        resp = await c.get("/listings", params={"gpu_model": "A100"})
    assert resp.status_code == 200
    body = resp.json()
    ids = [item["listing_id"] for item in body["items"]]
    assert "a100-listing" in ids
    assert "h200-listing" not in ids


@pytest.mark.asyncio
async def test_ram_gb_min_lower_bound_alias(_raw_client, db_session, maker_agent):
    _make_listing(db_session, maker_agent, "small", ram_gb=128)
    _make_listing(db_session, maker_agent, "big", ram_gb=1024)

    async with _raw_client as c:
        resp = await c.get("/listings", params={"ram_gb_min": "512"})
    body = resp.json()
    ids = [item["listing_id"] for item in body["items"]]
    assert ids == ["big"]


@pytest.mark.asyncio
async def test_unknown_filter_returns_400(_raw_client, db_session, maker_agent):
    _make_listing(db_session, maker_agent, "x", gpu_model="A100")

    async with _raw_client as c:
        resp = await c.get("/listings", params={"banana": "yellow"})
    assert resp.status_code == 400
    assert "banana" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_etag_mismatch_returns_412(_raw_client, db_session, maker_agent):
    _make_listing(db_session, maker_agent, "x", gpu_model="A100")

    async with _raw_client as c:
        resp = await c.get(
            "/listings",
            headers={"If-Match": '"deadbeef"'},
        )
    assert resp.status_code == 412
    body = resp.json()
    # Current etag returned so the buyer can refresh and retry.
    assert body["detail"]["current_etag"] == compute_etag(get_loaded_spec())


@pytest.mark.asyncio
async def test_etag_match_passes_through(_raw_client, db_session, maker_agent):
    _make_listing(db_session, maker_agent, "x", gpu_model="A100")
    current = compute_etag(get_loaded_spec())

    async with _raw_client as c:
        resp = await c.get("/listings", headers={"If-Match": f'"{current}"'})
    assert resp.status_code == 200
    assert resp.json()["count"] == 1


@pytest.mark.asyncio
async def test_token_array_projection_filter(_raw_client, db_session, maker_agent):
    """Filter on accepted_escrows[*].fields.token works via JSONPath."""
    usdc = "0x" + "ab" * 20
    weth = "0x" + "cd" * 20

    a = _make_listing(db_session, maker_agent, "usdc-only", gpu_model="A100")
    a.accepted_escrows = [
        {"chain_name": "anvil", "escrow_address": "0x" + "11" * 20, "fields": {"token": usdc}},
    ]
    b = _make_listing(db_session, maker_agent, "both", gpu_model="A100")
    b.accepted_escrows = [
        {"chain_name": "anvil", "escrow_address": "0x" + "22" * 20, "fields": {"token": usdc}},
        {"chain_name": "anvil", "escrow_address": "0x" + "33" * 20, "fields": {"token": weth}},
    ]
    db_session.commit()

    async with _raw_client as c:
        resp = await c.get("/listings", params={"token": weth})
    body = resp.json()
    ids = {item["listing_id"] for item in body["items"]}
    assert "both" in ids
    assert "usdc-only" not in ids


@pytest.mark.asyncio
async def test_no_filters_returns_all_open(_raw_client, db_session, maker_agent):
    _make_listing(db_session, maker_agent, "a")
    _make_listing(db_session, maker_agent, "b")
    _make_listing(db_session, maker_agent, "c")

    async with _raw_client as c:
        resp = await c.get("/listings")
    body = resp.json()
    assert body["count"] == 3
    assert body["total_after_filter"] == 3
