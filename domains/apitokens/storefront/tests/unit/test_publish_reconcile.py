"""Quota-backed publish and capacity-driven listing reconcile."""

from __future__ import annotations

import json
from datetime import datetime

import httpx
import pytest

from core_storefront.capacity_remote import RemoteCapacityClient


def _quota_remote(available_by_resource: dict[str, int]) -> RemoteCapacityClient:
    """A RemoteCapacityClient whose snapshot is served from a dict."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/capacity/snapshot":
            return httpx.Response(200, json={
                "resources": [
                    {
                        "resource_id": rid,
                        "resource_type": "api_tokens",
                        "total_units": 1000,
                        "available_units": available,
                    }
                    for rid, available in available_by_resource.items()
                ],
            })
        return httpx.Response(404, json={})

    return RemoteCapacityClient(
        "http://tokens:8082", transport=httpx.MockTransport(handler),
    )


@pytest.fixture
async def db(tmp_path):
    from apitokens_storefront.utils.sqlite_client import SQLiteClient

    return SQLiteClient(db_path=str(tmp_path / "publish.db"))


async def _insert_listing(db, listing_id: str, resource_id: str, status: str):
    await db.upsert_listing(
        listing_id=listing_id,
        status=status,
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
        offer_resource={
            "kind": "api_tokens.v1",
            "service_name": "Acme",
            "resource_id": resource_id,
        },
        accepted_escrows=[{
            "chain_name": "anvil",
            "escrow_address": "0x" + "11" * 20,
            "literal_fields": {"token": "0x" + "01" * 20},
            "rates": [{"field": "amount", "per": "token", "value": "100"}],
        }],
        fulfillment_resource=None,
        max_duration_seconds=None,
        seller="http://seller:8002",
    )


async def test_publish_from_quota_requires_registered_sellable_resource(
    db, monkeypatch,
):
    from apitokens_storefront.services import capacity_client as cc_module
    from apitokens_storefront.services.listing_service import ListingService
    from apitokens_storefront.utils import sqlite_client as sqlite_module

    monkeypatch.setattr(sqlite_module, "_sqlite_client", db)
    remote = _quota_remote({"svc-quota": 42, "svc-empty": 0})
    monkeypatch.setattr(
        cc_module, "build_capacity_client", lambda factory: remote,
    )

    svc = ListingService(sqlite_client=db)
    result = await svc.publish_from_quota(
        resource_id="svc-quota",
        service_name="Acme Inference",
        accepted_escrows=[{
            "chain_name": "anvil",
            "escrow_address": "0x" + "11" * 20,
            "literal_fields": {"token": "0x" + "01" * 20},
            "rates": [{"field": "amount", "per": "token", "value": "100"}],
        }],
        openapi_url="https://api.acme.example/openapi.json",
        base_url="https://api.acme.example",
    )
    assert result["status"] == "created"
    # Registry discovery is disabled in tests; the local row is the artifact.
    row = await db.load_listing(listing_id=result["listing_id"])
    assert row["status"] == "open"
    offer = row["offer_resource"]
    offer = json.loads(offer) if isinstance(offer, str) else offer
    assert offer["resource_id"] == "svc-quota"
    assert offer["kind"] == "api_tokens.v1"

    with pytest.raises(ValueError, match="no sellable units"):
        await svc.publish_from_quota(
            resource_id="svc-empty",
            service_name="Empty",
            accepted_escrows=row["accepted_escrows"]
            if isinstance(row["accepted_escrows"], list)
            else json.loads(row["accepted_escrows"]),
        )
    with pytest.raises(ValueError, match="not registered"):
        await svc.publish_from_quota(
            resource_id="svc-unknown",
            service_name="Ghost",
            accepted_escrows=[{"chain_name": "anvil", "escrow_address": "0x" + "11" * 20}],
        )


async def test_capacity_deltas_close_and_reopen_token_listings(db, monkeypatch):
    from apitokens_storefront.services.publication_service import (
        close_token_listings_after_capacity_change,
        reopen_token_listings_after_capacity_change,
    )
    from apitokens_storefront.utils import sqlite_client as sqlite_module

    monkeypatch.setattr(sqlite_module, "_sqlite_client", db)
    await _insert_listing(db, "L-live", "svc-live", "open")
    await _insert_listing(db, "L-dry", "svc-dry", "open")

    remote = _quota_remote({"svc-live": 10, "svc-dry": 0})
    closed = await close_token_listings_after_capacity_change(db, remote)
    assert closed == ["L-dry"]
    assert (await db.load_listing(listing_id="L-dry"))["status"] == "closed"
    assert (await db.load_listing(listing_id="L-live"))["status"] == "open"

    # Quota released → the listing reopens.
    remote = _quota_remote({"svc-live": 10, "svc-dry": 5})
    reopened = await reopen_token_listings_after_capacity_change(db, remote)
    assert reopened == ["L-dry"]
    assert (await db.load_listing(listing_id="L-dry"))["status"] == "open"
