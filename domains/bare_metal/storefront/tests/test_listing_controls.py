"""A seller's close and an administrator's resume of a bare-metal listing.

Application integration: the real app and its lifespan over a real database, its
loops held, publishing under the production composition to a recorded registry;
the listings come from a stepped publication cycle, and every call goes through
the canonical ``StorefrontClient``. Spec requirement "A seller's close is
durable".
"""

from __future__ import annotations

import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient
from market_identity import TrustedIdentitySet
from storefront_client import StorefrontClient
from storefront_client.client import StorefrontClientError

from arkhai_bare_metal_storefront.listing_controls import (
    ListingControlError,
    close_listing_as_seller,
)
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


async def test_a_paused_listing_stays_paused_through_a_cycle_until_resumed(
    tmp_path, monkeypatch
):
    """A pause leaves the listing open and published; a publication cycle
    neither clears the pause nor sends the listing again; a resume clears it
    and republishes."""
    site = Site(pool("pool-1", member("r1", "pool-1")))
    runtime = _derivation_runtime(tmp_path, monkeypatch, {"site-a": site})
    registry = runtime.registry_configuration.recording
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        async with _admin_client(app) as admin:
            listing_id = await _published(admin)
            paused = await admin.pause_listing(listing_id)
            cycle = await admin.admin_run_lifecycle_cycle("publication")
            while_paused = await admin.get_listing(listing_id)
            sent_while_paused = list(registry.operations())
            resumed = await admin.resume_listing(listing_id)
            after = await admin.get_listing(listing_id)

    assert paused.paused is True
    assert cycle["counts"].get("publish") is None
    assert cycle["counts"].get("refresh") is None
    assert (while_paused.status, while_paused.paused) == ("open", True)
    assert sent_while_paused == [("publish", listing_id)]
    assert (resumed.paused, resumed.registry_status) == (False, "published")
    assert (after.status, after.paused) == ("open", False)
    assert registry.operations() == [("publish", listing_id), ("publish", listing_id)]


async def test_resuming_an_open_listing_republishes_it(tmp_path, monkeypatch):
    site = Site(pool("pool-1", member("r1", "pool-1")))
    runtime = _derivation_runtime(tmp_path, monkeypatch, {"site-a": site})
    registry = runtime.registry_configuration.recording
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        async with _admin_client(app) as admin:
            listing_id = await _published(admin)
            resumed = await admin.resume_listing(listing_id)
            listing = await admin.get_listing(listing_id)

    assert resumed.registry_status == "published"
    assert listing.status == "open"
    assert registry.operations() == [("publish", listing_id), ("publish", listing_id)]


async def test_a_seller_closing_a_listing_reconciliation_closed_records_the_seller(
    tmp_path, monkeypatch
):
    """Once the seller closes it too, the listing is the seller's to re-list,
    and its source returning does not reopen it."""
    site = Site(pool("pool-1", member("r1", "pool-1")))
    runtime = _derivation_runtime(tmp_path, monkeypatch, {"site-a": site})
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        async with _admin_client(app) as admin, _client(
            app, SELLER_SIGNER, "seller"
        ) as seller:
            listing_id = await _published(admin)
            site.serve(pool("pool-1", member("r1", "pool-1", enabled=False)))
            await admin.admin_run_lifecycle_cycle("site-projections")
            await admin.admin_run_lifecycle_cycle("publication")
            reconciled = await admin.get_listing(listing_id)
            closed = await seller.close_listing(listing_id)
            site.serve(pool("pool-1", member("r1", "pool-1")))
            await admin.admin_run_lifecycle_cycle("site-projections")
            await admin.admin_run_lifecycle_cycle("publication")
            after = await admin.get_listing(listing_id)

    assert reconciled.extra["closed_by"] == "reconciliation"
    assert closed.status == "closed"
    assert (after.status, after.extra["closed_by"]) == ("closed", "seller")


async def test_a_close_the_database_cannot_take_is_refused_as_retryable(
    tmp_path, monkeypatch
):
    """Another process holding the storefront's database locked past the busy
    timeout leaves the close undone and refuses it as 503
    ``listing_close_incomplete``, as VM's close does.

    The close is called directly, over the running app's runtime and real
    database: the lock would also stop the route's request authentication,
    whose replay reservation is a write, before the close was reached."""
    site = Site(pool("pool-1", member("r1", "pool-1")))
    runtime = _derivation_runtime(tmp_path, monkeypatch, {"site-a": site})
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        async with _admin_client(app) as admin:
            listing_id = await _published(admin)
            holder = sqlite3.connect(runtime.db.db_path, isolation_level=None)
            try:
                holder.execute("BEGIN EXCLUSIVE")
                with pytest.raises(ListingControlError) as refused:
                    await close_listing_as_seller(runtime, listing_id)
            finally:
                holder.close()
            listing = await admin.get_listing(listing_id)

    assert refused.value.status_code == 503
    assert refused.value.detail["error"] == "listing_close_incomplete"
    assert listing.status == "open"
