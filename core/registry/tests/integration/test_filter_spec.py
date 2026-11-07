"""Integration test for GET /filter-spec.

Exercises the full HTTP path through the gated router: spec loads from
the shipped YAML, body+ETag are present, and the etag is stable across
two reads. It also queries listings under the shipped spec's GPU filters,
which a listing stating no GPU fails. The loader's structural validation
(invalid YAML, dup filter names, etc.) is covered in
``tests/unit/test_filter_spec.py``.
"""

from __future__ import annotations

import httpx
import pytest
from registry_client import ListingRequest


@pytest.mark.asyncio
async def test_filter_spec_endpoint_returns_loaded_spec(registry_client) -> None:
    from core_registry.main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as raw:
        resp = await raw.get("/filter-spec")
    assert resp.status_code == 200

    body = resp.json()
    assert isinstance(body["version"], int) and body["version"] >= 1
    assert isinstance(body["etag"], str) and len(body["etag"]) == 64  # sha256 hex
    assert resp.headers["etag"].strip('"') == body["etag"]

    assert body["listing_shape"]["type"] == "object"
    required = set(body["listing_shape"].get("required") or [])
    assert {"listing_id", "listing_resource", "storefront_url"} <= required
    settlement_requirements = {
        tuple(branch.get("required") or [])
        for branch in body["listing_shape"].get("anyOf") or []
    }
    assert ("accepted_escrows",) in settlement_requirements
    assert ("settlement_options",) in settlement_requirements

    names = {f["name"] for f in body["filters"]}
    assert {"gpu_model", "region", "ram_gb_min", "token"} <= names

    # Numeric-min filters are sugared with alias_kind so URL parsing layer
    # in (a1b)'s filter eval can map `?ram_gb_min=16` → range form.
    ram_min = next(f for f in body["filters"] if f["name"] == "ram_gb_min")
    assert ram_min["op"] == "range"
    assert ram_min["alias_kind"] == "lower_bound"

    # The token filter must be underreport-friendly — sellers advertising no
    # tokens shouldn't be invisible to a `?token=...` query.
    token = next(f for f in body["filters"] if f["name"] == "token")
    assert token["on_missing"] == "pass"

    # The shipped spec declares its schema identity; the buyer matches
    # plugins to registries on this id.
    assert body["schema"]["id"] == "compute.market"
    assert body["schema"]["version"] >= 1


def _listing(listing_id: str, **resource: object) -> ListingRequest:
    return ListingRequest(
        listing_id=listing_id,
        listing_resource={"region": "us-west", "offering_mode": "vm", **resource},
        accepted_escrows=[
            {
                "chain_name": "anvil",
                # Development fixture addresses; never used on a public network.
                "escrow_address": "0x" + "11" * 20,
                "literal_fields": {"token": "0x" + "22" * 20},
            }
        ],
        storefront_url="http://seller",
    )


async def _ids(registry_client, **filters) -> set[str]:
    page = await registry_client.list_listings(limit=100, **filters)
    return {str(row.id) for row in page.listings}


@pytest.mark.asyncio
async def test_gpu_filters_exclude_a_listing_stating_no_gpu(registry_client) -> None:
    """A GPU filter fails on a missing value, so a listing stating no GPU is
    found only by queries that bound no GPU field."""
    await registry_client.publish_listing(_listing("cpu-only", vcpu_count=16, ram_gb=64))
    await registry_client.publish_listing(
        _listing("gpu", gpu_model="H100", gpu_count=1, vcpu_count=16, ram_gb=64)
    )

    assert await _ids(registry_client, gpu_count_min=1) == {"gpu"}
    assert await _ids(registry_client, gpu_model="H100") == {"gpu"}
    assert await _ids(registry_client, vcpu_count_min=16) == {"cpu-only", "gpu"}


@pytest.mark.asyncio
async def test_filter_spec_etag_stable_across_requests(registry_client) -> None:
    from core_registry.main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as raw:
        r1 = await raw.get("/filter-spec")
        r2 = await raw.get("/filter-spec")
    assert r1.headers["etag"] == r2.headers["etag"]
    assert r1.json()["etag"] == r2.json()["etag"]
