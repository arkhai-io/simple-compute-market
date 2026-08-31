"""Quota-backed publish and capacity-driven listing reconcile."""

from __future__ import annotations

import json
from datetime import datetime

import httpx
import pytest

from core_storefront.auth import signed_response_headers
from market_site_client import SiteCapacityClient
from market_identity import Ed25519Signer, TrustedIdentitySet

_SELLER_SIGNER = Ed25519Signer(bytes.fromhex("22" * 32))
_AUTHORITY_SIGNER = Ed25519Signer(bytes.fromhex("33" * 32))
SELLER_PRINCIPAL = _SELLER_SIGNER.identity


def _quota_remote(available_by_resource: dict[str, int]) -> SiteCapacityClient:
    """A SiteCapacityClient whose snapshot is served from a dict."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/capacity/snapshot":
            body = {
                "resources": [
                    {
                        "resource_id": rid,
                        "resource_type": "api_credits",
                        "total_units": 1000,
                        "available_units": available,
                    }
                    for rid, available in available_by_resource.items()
                ],
            }
            headers = signed_response_headers(
                signer=_AUTHORITY_SIGNER,
                role="service",
                method=request.method,
                operation="capacity_snapshot",
                resource="",
                request_id=request.headers["X-Market-Request-ID"],
                status=200,
                body=body,
            )
            return httpx.Response(200, json=body, headers=headers)
        return httpx.Response(404, json={})

    return SiteCapacityClient(
        "http://tokens:8082",
        signer=_SELLER_SIGNER,
        expected_authorities=TrustedIdentitySet(
            identities=(_AUTHORITY_SIGNER.identity,),
        ),
        transport=httpx.MockTransport(handler),
    )


class _QuotaRuntime:
    def __init__(self, values: dict[str, int]) -> None:
        self._values = values

    async def availability(self) -> dict[tuple[str, str], int]:
        return {
            ("tokens", resource_id): units
            for resource_id, units in self._values.items()
        }


class _SettlementComposition:
    async def readiness(self) -> tuple[()]:
        return ()

    async def publication_artifacts(
        self,
        _facts,
        _clauses,
    ) -> tuple[list[dict], list[dict], tuple[()]]:
        return [], [], ()


@pytest.fixture
async def db(tmp_path):
    from apicredits_storefront.utils.sqlite_client import SQLiteClient

    return SQLiteClient(db_path=str(tmp_path / "publish.db"))


async def _insert_listing(db, listing_id: str, resource_id: str, status: str):
    await db.upsert_listing(
        listing_id=listing_id,
        status=status,
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
        offer_resource={
            "kind": "api_credits.v1",
            "service_name": "Acme",
            "resource_id": resource_id,
            "capacity_site_id": "tokens",
            "offering_mode": "api_credits",
        },
        accepted_escrows=[
            {
                "chain_name": "anvil",
                "escrow_address": "0x" + "11" * 20,
                "literal_fields": {"token": "0x" + "01" * 20},
                "rates": [{"field": "amount", "per": "token", "value": "100"}],
            }
        ],
        fulfillment_resource=None,
        max_duration_seconds=None,
        storefront_url="http://seller:8002",
        seller_principal=SELLER_PRINCIPAL,
    )


async def test_publish_from_quota_requires_registered_sellable_resource(
    db,
    monkeypatch,
):
    from apicredits_storefront.services import capacity_client as cc_module
    from apicredits_storefront.services.listing_service import ListingService
    from apicredits_storefront.utils import sqlite_client as sqlite_module

    monkeypatch.setattr(sqlite_module, "_sqlite_client", db)
    runtime = _QuotaRuntime({"svc-quota": 42, "svc-empty": 0})
    monkeypatch.setattr(
        cc_module,
        "build_capacity_runtime",
        lambda factory: runtime,
    )

    svc = ListingService(
        sqlite_client=db,
        seller_principal=SELLER_PRINCIPAL,
        settlement_composition=_SettlementComposition(),
    )
    result = await svc.publish_from_quota(
        resource_id="svc-quota",
        service_name="Acme Inference",
        accepted_escrows=[
            {
                "chain_name": "anvil",
                "escrow_address": "0x" + "11" * 20,
                "literal_fields": {"token": "0x" + "01" * 20},
                "rates": [{"field": "amount", "per": "token", "value": "100"}],
            }
        ],
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
    assert offer["capacity_site_id"] == "tokens"
    assert offer["offering_mode"] == "api_credits"
    assert offer["kind"] == "api_credits.v1"
    assert offer["service_name"] == "Acme Inference"
    assert offer["description"] is None

    with pytest.raises(ValueError, match="no sellable units"):
        await svc.publish_from_quota(
            resource_id="svc-empty",
            service_name="Empty",
            accepted_escrows=row["accepted_escrows"]
            if isinstance(row["accepted_escrows"], list)
            else json.loads(row["accepted_escrows"]),
        )
    with pytest.raises(ValueError, match="exactly one"):
        await svc.publish_from_quota(
            resource_id="svc-unknown",
            service_name="Ghost",
            accepted_escrows=[
                {"chain_name": "anvil", "escrow_address": "0x" + "11" * 20}
            ],
        )


async def test_publish_from_quota_validates_listing_through_domain_runtime(
    db,
    monkeypatch,
):
    from apicredits_storefront.services import capacity_client as cc_module
    from apicredits_storefront.services.listing_service import ListingService

    runtime = _QuotaRuntime({"svc-quota": 42})
    monkeypatch.setattr(
        cc_module,
        "build_capacity_runtime",
        lambda factory: runtime,
    )

    svc = ListingService(
        sqlite_client=db,
        seller_principal=SELLER_PRINCIPAL,
        settlement_composition=_SettlementComposition(),
    )
    with pytest.raises(ValueError, match="service_name"):
        await svc.publish_from_quota(
            resource_id="svc-quota",
            service_name=" ",
            accepted_escrows=[
                {
                    "chain_name": "anvil",
                    "escrow_address": "0x" + "11" * 20,
                    "literal_fields": {"token": "0x" + "01" * 20},
                    "rates": [{"field": "amount", "per": "token", "value": "100"}],
                }
            ],
        )


async def test_capacity_deltas_close_and_reopen_token_listings(db, monkeypatch):
    from apicredits_storefront.services.publication_service import (
        close_token_listings_after_capacity_change,
        reopen_token_listings_after_capacity_change,
    )
    from apicredits_storefront.utils import sqlite_client as sqlite_module

    monkeypatch.setattr(sqlite_module, "_sqlite_client", db)
    await _insert_listing(db, "L-live", "svc-live", "open")
    await _insert_listing(db, "L-dry", "svc-dry", "open")

    availability = await _QuotaRuntime({"svc-live": 10, "svc-dry": 0}).availability()
    closed = await close_token_listings_after_capacity_change(db, availability)
    assert closed == ["L-dry"]
    assert (await db.load_listing(listing_id="L-dry"))["status"] == "closed"
    assert (await db.load_listing(listing_id="L-live"))["status"] == "open"

    # Quota released → the listing reopens.
    availability = await _QuotaRuntime({"svc-live": 10, "svc-dry": 5}).availability()
    reopened = await reopen_token_listings_after_capacity_change(db, availability)
    assert reopened == ["L-dry"]
    assert (await db.load_listing(listing_id="L-dry"))["status"] == "open"
