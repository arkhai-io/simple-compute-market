"""A seller's close and an administrator's resume of a bare-metal listing.

Application integration: the real app and its lifespan over a real database, its
loops held, publishing under the production composition to a recorded registry;
the listings come from a stepped publication cycle, and every call goes through
the canonical ``StorefrontClient``. Spec requirement "A seller's close is
durable".
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient
from market_identity import TrustedIdentitySet
from storefront_client import StorefrontClient
from storefront_client.client import StorefrontClientError

from test_http_system import (
    ADMIN_SIGNER,
    SELLER_SIGNER,
    _admin_client,
    _app,
    _derivation_runtime,
)
from test_publication_cycle import Site, member, pool

pytestmark = pytest.mark.asyncio


def _client(app, signer, role: str) -> StorefrontClient:
    return StorefrontClient(
        "http://seller",
        signer=signer,
        caller_role=role,
        # The storefront signs every response; a seller-role client also lists
        # itself among the publishers it accepts.
        expected_publishers=TrustedIdentitySet(
            identities=tuple(dict.fromkeys((SELLER_SIGNER.identity, signer.identity)))
        ),
        transport=httpx.ASGITransport(app=app),
    )


async def _published(admin: StorefrontClient) -> str:
    await admin.admin_run_lifecycle_cycle("publication")
    (listing,) = (await admin.list_listings(status="open")).listings
    return listing.listing_id


async def test_a_sellers_close_is_durable_and_a_resume_relists_it(tmp_path, monkeypatch):
    """The seller's close holds through the next publication cycle, whose
    source still supports the listing; an administrator's resume reopens it
    locally and at the registry."""
    site = Site(pool("pool-1", member("r1", "pool-1")))
    runtime = _derivation_runtime(tmp_path, monkeypatch, {"site-a": site})
    registry = runtime.registry_configuration.recording
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        async with _admin_client(app) as admin, _client(
            app, SELLER_SIGNER, "seller"
        ) as seller:
            listing_id = await _published(admin)
            closed = await seller.close_listing(listing_id)
            cycle = await admin.admin_run_lifecycle_cycle("publication")
            after_cycle = await admin.get_listing(listing_id)
            resumed = await admin.resume_listing(listing_id)
            reopened = await admin.get_listing(listing_id)

    assert (closed.status, closed.listing_id) == ("closed", listing_id)
    assert after_cycle.status == "closed"
    assert after_cycle.extra["closed_by"] == "seller"
    assert {"action": "skip", "listing_id": listing_id, "reason": "closed_by_seller"} in cycle[
        "actions"
    ]
    assert (resumed.paused, resumed.registry_status) == (False, "published")
    assert reopened.status == "open"
    assert [operation for operation, _ in registry.operations()] == [
        "publish",
        "closed",
        "publish",
        "open",
    ]


async def test_a_listing_reconciliation_closed_is_not_resumed(tmp_path, monkeypatch):
    site = Site(pool("pool-1", member("r1", "pool-1")))
    runtime = _derivation_runtime(tmp_path, monkeypatch, {"site-a": site})
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        async with _admin_client(app) as admin:
            listing_id = await _published(admin)
            site.serve(pool("pool-1", member("r1", "pool-1", enabled=False)))
            await admin.admin_run_lifecycle_cycle("site-projections")
            await admin.admin_run_lifecycle_cycle("publication")
            with pytest.raises(StorefrontClientError) as refused:
                await admin.resume_listing(listing_id)
            listing = await admin.get_listing(listing_id)

    assert refused.value.status_code == 409
    assert "listing_closed_by_reconciliation" in str(refused.value)
    assert listing.status == "closed"


async def test_only_the_seller_closes_a_listing(tmp_path, monkeypatch):
    site = Site(pool("pool-1", member("r1", "pool-1")))
    runtime = _derivation_runtime(tmp_path, monkeypatch, {"site-a": site})
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        async with _admin_client(app) as admin, _client(
            app, ADMIN_SIGNER, "seller"
        ) as impostor:
            listing_id = await _published(admin)
            with pytest.raises(StorefrontClientError) as refused:
                await impostor.close_listing(listing_id)
            listing = await admin.get_listing(listing_id)

    assert refused.value.status_code == 403
    assert listing.status == "open"

    # Rejection path: an unsigned request is refused before anything changes.
    with TestClient(app) as client:
        assert client.post(f"/api/v1/listings/{listing_id}/close").status_code == 401


async def test_closing_an_unknown_listing_is_not_found(tmp_path, monkeypatch):
    runtime = _derivation_runtime(tmp_path, monkeypatch, {"site-a": Site(pool("pool-0"))})
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        async with _client(app, SELLER_SIGNER, "seller") as seller:
            with pytest.raises(StorefrontClientError) as missing:
                await seller.close_listing("no-such-listing")

    assert missing.value.status_code == 404
