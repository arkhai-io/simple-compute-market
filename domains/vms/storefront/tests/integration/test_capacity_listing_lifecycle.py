"""Capacity-feed standing offers, through the real storefront lifecycle API."""

from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest

import market_storefront.container as container
from market_storefront.services.capacity_client import capacity_binding_for_listing
from market_storefront.services.vm_job_spec_service import compute_capacity_claim_from_order
from market_capacity_publication.capacity_remote import reset_site_event_cursors
from market_storefront.services import site_projection_cache
from market_storefront.utils.sqlite_client import SQLiteClient
from tests.fake_site import capacity_runtime_over_sites
from tests.publication_app import SITE, _projection_caches, pool, publication_app


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["fungible", "specific_resource"])
async def test_capacity_feed_converges_standing_offer_across_quiet_cycles_and_restart(
    tmp_path, mode,
):
    async with publication_app(tmp_path, registries=True) as world:
        capacity = {"gpu_count": 8, "vcpu_count": 64, "ram_gb": 512, "disk_gb": 1600}
        claim = {"gpu_count": 1, "vcpu_count": 8, "ram_gb": 64, "disk_gb": 200}
        world.pools.append(pool(
            "standing", backing="backed", capacity=capacity,
            listing_cardinality_mode=mode,
            listing_shapes={"vm": [{
                "gpu": {"count": 1, "model": "H100"}, "cpu": {"count": 8},
                "memory": {"gib": 64}, "storage": {"gib": 200},
            }]},
        ))
        world.site.add_resource(
            "standing-res", 8, capacity=capacity,
            attributes={"gpu_model": "H100", "region": "us-east"},
        )
        await world.client.admin_run_lifecycle_cycle("publication")
        (listing,) = (await world.client.list_listings()).listings
        listing_id = listing.listing_id
        original = await world.db.load_listing(listing_id=listing_id)
        runtime = container.resolved_capacity_runtime
        binding = await capacity_binding_for_listing(world.db, listing_id)
        reservation_claim = compute_capacity_claim_from_order(original)
        await world.client.admin_run_lifecycle_cycle("capacity-events")
        reservations = []
        registry_a, registry_b = world.registries.urls

        for index in range(8):
            if index == 7:
                world.registries.failing.add(("closed", registry_b))
            reservation = await runtime.reserve(binding, claim=reservation_claim, ttl_seconds=0)
            assert reservation is not None
            reservations.append(reservation["capacity_reservation_id"])
            assert world.site.reservations[reservations[-1]]["dimensions"] == claim
            # Transport effects emit no local callback: settlement never waits
            # for registry delivery, even when the registry is unavailable.
            assert (await world.client.get_listing(listing_id)).status == "open"
            await world.client.admin_run_lifecycle_cycle("capacity-events")
            row = await world.client.get_listing(listing_id)
            assert row.status == ("open" if index < 7 else "closed")

        assert (await world.db.load_listing(listing_id=listing_id))["closed_by"] == "reconciliation"
        publications = await world.db.load_publications(listing_id=listing_id)
        assert {r["registry_url"]: r["status"] for r in publications} == {
            registry_a: "unpublished", registry_b: "failed",
        }
        world.registries.failing.clear()
        world.registries.sent.clear()
        await world.client.admin_run_lifecycle_cycle("capacity-events")
        assert [(op, url, body) for op, url, _, body in world.registries.sent] == [
            ("update", registry_b, {"status": "closed"}),
        ]

        world.registries.failing.add(("open", registry_b))
        released = await runtime.release(binding, capacity_reservation_id=reservations[0])
        assert released is not None
        # A failed refresh must not reopen from last-good values or lose work.
        world.projection.failing = True
        await world.client.admin_run_lifecycle_cycle("capacity-events")
        assert (await world.client.get_listing(listing_id)).status == "closed"
        world.projection.failing = False
        await world.client.admin_run_lifecycle_cycle("capacity-events")
        assert (await world.client.get_listing(listing_id)).status == "open"
        publications = await world.db.load_publications(listing_id=listing_id)
        assert {r["registry_url"]: r["status"] for r in publications} == {
            registry_a: "published", registry_b: "failed",
        }

        # Reconstruct process-local runtime/cursor state over the same SQLite
        # file. No queued in-memory event or publication runtime is retained.
        world.registries.failing.clear()
        world.registries.sent.clear()
        restarted_db = SQLiteClient(db_path=world.db.db_path, registry=container.resolved_domain_registry)
        restarted = capacity_runtime_over_sites({SITE: world.site}, sqlite_client_factory=lambda: restarted_db)
        container.resolved_capacity_runtime = restarted
        reset_site_event_cursors()
        # A missing delivery row is also outstanding work, not evidence of
        # success. Simulate an acknowledgement that was never recorded.
        with sqlite3.connect(world.db.db_path) as conn:
            conn.execute("DELETE FROM publications WHERE listing_id = ? AND registry_url = ?",
                         (listing_id, registry_b))
        with patch.dict(site_projection_cache._caches, {SITE: _projection_caches(world.projection)}, clear=True):
            await world.client.admin_run_lifecycle_cycle("capacity-events")
        assert [(op, url) for op, url, _, _ in world.registries.sent] == [
            ("publish", registry_b), ("update", registry_b),
        ]
        recovered = await world.db.load_listing(listing_id=listing_id)
        assert recovered["listing_resource"] == original["listing_resource"]
        assert recovered["accepted_escrows"] == original["accepted_escrows"]
        assert recovered["settlement_options"] == original["settlement_options"]
        (same,) = (await world.client.list_listings()).listings
        assert same.listing_id == listing_id
        await world.seller.close_listing(listing_id)
        await world.client.admin_run_lifecycle_cycle("capacity-events")
        assert (await world.client.get_listing(listing_id)).status == "closed"
