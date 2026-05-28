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
            "literal_fields": {"token": "0x" + "ab" * 20},
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
    """Filter on accepted_escrows[*].literal_fields.token works via JSONPath."""
    usdc = "0x" + "ab" * 20
    weth = "0x" + "cd" * 20

    a = _make_listing(db_session, maker_agent, "usdc-only", gpu_model="A100")
    a.accepted_escrows = [
        {"chain_name": "anvil", "escrow_address": "0x" + "11" * 20, "literal_fields": {"token": usdc}},
    ]
    b = _make_listing(db_session, maker_agent, "both", gpu_model="A100")
    b.accepted_escrows = [
        {"chain_name": "anvil", "escrow_address": "0x" + "22" * 20, "literal_fields": {"token": usdc}},
        {"chain_name": "anvil", "escrow_address": "0x" + "33" * 20, "literal_fields": {"token": weth}},
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


# ---------------------------------------------------------------------------
# Raw set-form URL syntax + strict.* override (a2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_form_in_multi_value(_raw_client, db_session, maker_agent):
    _make_listing(db_session, maker_agent, "a100", gpu_model="A100")
    _make_listing(db_session, maker_agent, "h200", gpu_model="H200")
    _make_listing(db_session, maker_agent, "b200", gpu_model="B200")

    async with _raw_client as c:
        resp = await c.get("/listings", params={"gpu_model": "in:[A100,B200]"})
    body = resp.json()
    ids = {item["listing_id"] for item in body["items"]}
    assert ids == {"a100", "b200"}


@pytest.mark.asyncio
async def test_set_form_range_full_interval(_raw_client, db_session, maker_agent):
    _make_listing(db_session, maker_agent, "small", ram_gb=64)
    _make_listing(db_session, maker_agent, "mid", ram_gb=256)
    _make_listing(db_session, maker_agent, "big", ram_gb=1024)

    async with _raw_client as c:
        resp = await c.get("/listings", params={"ram_gb_min": "range:[128,512]"})
    body = resp.json()
    ids = {item["listing_id"] for item in body["items"]}
    assert ids == {"mid"}


@pytest.mark.asyncio
async def test_set_form_not_in_excludes_token(_raw_client, db_session, maker_agent):
    usdc = "0x" + "ab" * 20
    weth = "0x" + "cd" * 20

    a = _make_listing(db_session, maker_agent, "usdc-listing", gpu_model="A100")
    a.accepted_escrows = [
        {"chain_name": "anvil", "escrow_address": "0x" + "11" * 20, "literal_fields": {"token": usdc}},
    ]
    b = _make_listing(db_session, maker_agent, "weth-listing", gpu_model="A100")
    b.accepted_escrows = [
        {"chain_name": "anvil", "escrow_address": "0x" + "22" * 20, "literal_fields": {"token": weth}},
    ]
    db_session.commit()

    async with _raw_client as c:
        resp = await c.get(
            "/listings", params={"token_exclude": f"not_in:[{usdc}]"}
        )
    body = resp.json()
    ids = {item["listing_id"] for item in body["items"]}
    assert "weth-listing" in ids
    assert "usdc-listing" not in ids


@pytest.mark.asyncio
async def test_set_form_exists_oracle(_raw_client, db_session, maker_agent):
    a = _make_listing(db_session, maker_agent, "with-oracle", gpu_model="A100")
    a.oracle_address = "0x" + "ff" * 20
    _make_listing(db_session, maker_agent, "no-oracle", gpu_model="A100")
    db_session.commit()

    async with _raw_client as c:
        resp = await c.get("/listings", params={"has_oracle": "exists:true"})
    body = resp.json()
    ids = {item["listing_id"] for item in body["items"]}
    assert ids == {"with-oracle"}


@pytest.mark.asyncio
async def test_strict_token_tightens_default(_raw_client, db_session, maker_agent):
    """token defaults to on_missing: pass; strict tightens for this query.

    A listing with no escrows passes the default token filter (lenient)
    but fails when strict.token=true is set.
    """
    usdc = "0x" + "ab" * 20

    a = _make_listing(db_session, maker_agent, "no-escrows", gpu_model="A100")
    a.accepted_escrows = []
    _make_listing(db_session, maker_agent, "has-escrows", gpu_model="A100")  # default usdc-stand-in
    db_session.commit()

    async with _raw_client as c:
        loose = await c.get("/listings", params={"token": usdc})
        strict = await c.get(
            "/listings", params={"token": usdc, "strict.token": "true"}
        )
    loose_ids = {it["listing_id"] for it in loose.json()["items"]}
    strict_ids = {it["listing_id"] for it in strict.json()["items"]}
    # Lenient: both listings pass.
    assert "no-escrows" in loose_ids
    assert "has-escrows" in loose_ids
    # Strict: only the listing that actually advertises the token.
    assert "no-escrows" not in strict_ids
    assert "has-escrows" in strict_ids


@pytest.mark.asyncio
async def test_strict_unknown_filter_returns_400(_raw_client, db_session, maker_agent):
    _make_listing(db_session, maker_agent, "x", gpu_model="A100")
    async with _raw_client as c:
        resp = await c.get("/listings", params={"strict.banana": "true"})
    assert resp.status_code == 400
    assert "banana" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_set_form_op_mismatch_returns_400(_raw_client, db_session, maker_agent):
    """``gpu_model`` declares op: in; not_in:[...] in set-form must 400."""
    _make_listing(db_session, maker_agent, "x", gpu_model="A100")
    async with _raw_client as c:
        resp = await c.get("/listings", params={"gpu_model": "not_in:[H100]"})
    assert resp.status_code == 400
    assert "op=" in resp.json()["detail"]
