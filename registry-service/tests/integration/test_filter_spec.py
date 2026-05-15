"""Integration test for GET /filter-spec.

Exercises the full HTTP path through the gated router: spec loads from
the shipped YAML, body+ETag are present, and the etag is stable across
two reads.  The loader's structural validation (invalid YAML, dup filter
names, etc.) is covered in ``tests/unit/test_filter_spec.py``.
"""

from __future__ import annotations

import httpx
import pytest


@pytest.mark.asyncio
async def test_filter_spec_endpoint_returns_loaded_spec(registry_client) -> None:
    from src.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as raw:
        resp = await raw.get("/filter-spec")
    assert resp.status_code == 200

    body = resp.json()
    assert isinstance(body["version"], int) and body["version"] >= 1
    assert isinstance(body["etag"], str) and len(body["etag"]) == 64  # sha256 hex
    assert resp.headers["etag"].strip('"') == body["etag"]

    assert body["listing_shape"]["type"] == "object"
    required = set(body["listing_shape"].get("required") or [])
    assert {"listing_id", "seller", "offer_resource", "accepted_escrows"} <= required

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


@pytest.mark.asyncio
async def test_filter_spec_etag_stable_across_requests(registry_client) -> None:
    from src.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as raw:
        r1 = await raw.get("/filter-spec")
        r2 = await raw.get("/filter-spec")
    assert r1.headers["etag"] == r2.headers["etag"]
    assert r1.json()["etag"] == r2.json()["etag"]
