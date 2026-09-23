"""Publication cycles against a real storefront database.

The cycle runs through the real listing service, durable bindings, and the kit
publication runtime. The site projection is supplied as the projection poller
would hold it; the capacity site is the in-memory fake the other storefront
integration suites use. Registry discovery is disabled, so publication records
locally and each assertion is about durable storefront state.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from core_storefront.site_projections import (
    ProjectionCache,
    ProjectionIdentity,
    ProjectionState,
)
from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    build_vm_storefront_registry,
)
from market_storefront.models.listing_models import VmCreateListingRequest
from market_storefront.services import site_projection_cache
from market_storefront.services.listing_service import ListingService
from market_storefront.services.publication_loop import VmPublicationCycle
from market_storefront.utils.sqlite_client import SQLiteClient
from tests._settings_overrides import settings_overrides
from tests.fixtures.publication_cycle import validate_cycle_report
from tests.fake_site import TEST_MARKETPLACE_SIGNER, FakeSite, capacity_runtime_over

pytestmark = pytest.mark.asyncio

SITE = "site-a"
_UNBACKED = {
    "deliverable_modes": [],
    "advertisable_modes": ["vm"],
    "capacity_backing": "unbacked",
}
_BACKED = {
    "deliverable_modes": ["vm"],
    "advertisable_modes": ["vm"],
    "capacity_backing": "backed",
}
# A development escrow shape; never a real address on any public network.
_ESCROW = {
    "chain_name": "anvil",
    "escrow_address": "0x" + "11" * 20,
    "literal_fields": {"token": "0x" + "22" * 20},
    "rates": [{"field": "amount", "per": "hour", "value": "100"}],
}


def _option(rate: str = "100") -> dict:
    return {
        "option_id": "contact-option",
        "mechanism": "contact-exchange.v1",
        "asset": "none",
        "rates": [],
        "params": {"rate_hint": rate},
    }


class _Composition:
    """Settlement composition as the listing service sees it."""

    def __init__(self, *, fulfilment: dict[str, bool]):
        self.mechanism_fulfillment = fulfilment
        self.options = [_option()]

    async def publication_artifacts(self, resources, *, clauses=None):
        return list(resources["accepted_escrows"]), list(self.options), ()


def _pool(pool_id, *, tags, gpu_model="H100", enabled=True, gpu_count=2):
    return {
        "resource_pool_id": pool_id,
        "pool_metadata": {
            "enabled": enabled,
            "policy_tags": {
                **tags,
                "listing_cardinality_mode": "fungible",
                "region": "us-east",
            },
        },
        "resources": [
            {
                "physical_resource_id": f"{pool_id}-res",
                "enabled": True,
                "capacity": {"gpu_count": gpu_count},
                "available": {"gpu_count": gpu_count},
                "attributes": {"gpu_model": gpu_model},
            }
        ],
    }


def _caches(pools: list[dict]):
    resource_pools = ProjectionCache(client=None)
    resource_pools._value = pools
    resource_pools._state = ProjectionState.loaded
    resource_pools._identity = ProjectionIdentity(revision=1, digest="loop")
    return site_projection_cache.SiteProjectionCaches(
        resource_pools=resource_pools,
        capacity_buckets=ProjectionCache(client=None),
    )


def _request(_source, candidate, listing_resource) -> VmCreateListingRequest:
    return VmCreateListingRequest(
        listing_resource=listing_resource,
        capacity_source={
            "site_id": candidate["site_id"],
            "pool_id": candidate.get("pool_id"),
            "resource_id": candidate.get("resource_id"),
            "gpu_count": candidate["gpu_count"],
        },
        accepted_escrows=[_ESCROW],
        max_duration_seconds=3600,
    )


@pytest.fixture
def world(tmp_path):
    registry = build_vm_storefront_registry(build_vm_storefront_domain())
    db = SQLiteClient(db_path=str(tmp_path / "loop.db"), registry=registry)
    capacity = capacity_runtime_over(FakeSite(deliverable_modes={"vm"}), site_name=SITE)
    composition = _Composition(
        fulfilment={"alkahest.v1": True, "contact-exchange.v1": False}
    )
    registration = registry.resolve_mode("vm")
    listings = ListingService(
        registry=registry,
        binding=registration.binding,
        domain=registration.contract,
        capacity_runtime=capacity,
        sqlite_client=db,
        marketplace_signer=TEST_MARKETPLACE_SIGNER,
        alkahest_clients={},
        settlement_composition_provider=lambda: composition,
    )
    pools: list[dict] = []
    with settings_overrides(
        enable_registry_discovery=False,
        registry__urls=[],
        **{"capacity.use_site_projection_for_listings": True},
    ), patch.dict(site_projection_cache._caches, {SITE: _caches(pools)}, clear=True):
        yield {
            "db": db,
            "listings": listings,
            "capacity": capacity,
            "registry": registry,
            "pools": pools,
            "composition": composition,
        }


async def _cycle(world, *, dry_run=False) -> dict:
    report = await _run_cycle(world, dry_run=dry_run)
    validate_cycle_report(report)
    return report


async def _run_cycle(world, *, dry_run=False) -> dict:
    return await VmPublicationCycle(
        sqlite_client=world["db"],
        listing_service=world["listings"],
        capacity_runtime=world["capacity"],
        registry=world["registry"],
        storefront_url="http://seller.test",
        wallet_address="",
        dry_run=dry_run,
        request_builder=_request,
    ).run()


async def _open_listings(db) -> dict[str, dict]:
    rows = await db.list_listings(status="open", limit=100)
    from market_storefront.services.listing_source_check import (
        stored_listing_resource,
    )

    out = {}
    for row in rows:
        listing = await db.load_listing(listing_id=row["listing_id"])
        listing["listing_resource"] = stored_listing_resource(listing)
        out[row["listing_id"]] = listing
    return out


async def test_a_declared_unbacked_pool_publishes_without_any_command(world):
    world["pools"].append(_pool("broker-a", tags=_UNBACKED))

    result = await _cycle(world)

    listings = await _open_listings(world["db"])
    assert result["counts"]["publish"] == 2
    assert len(listings) == 2
    for listing_id, row in listings.items():
        binding = await world["db"].load_listing_binding(listing_id=listing_id)
        assert binding.capacity_backing == "unbacked"
        assert row["listing_resource"]["capacity_backing"] == "unbacked"
        # Alkahest is fulfilled through VM capacity, so an unbacked listing
        # carries only the option that is not.
        assert row["accepted_escrows"] == []
        assert [o["mechanism"] for o in row["settlement_options"]] == [
            "contact-exchange.v1"
        ]


async def test_an_unbacked_source_with_only_capacity_mechanisms_publishes_nothing(
    world,
):
    world["composition"].options = []
    world["pools"].append(_pool("broker-a", tags=_UNBACKED))

    result = await _cycle(world)

    assert await _open_listings(world["db"]) == {}
    assert result["counts"].get("refuse") == 2


async def test_a_dry_run_reports_the_cycle_and_changes_nothing(world):
    world["pools"].append(_pool("broker-a", tags=_UNBACKED))

    first = await _cycle(world, dry_run=True)
    second = await _cycle(world, dry_run=True)

    assert first == second
    assert first["counts"] == {"publish": 2}
    assert await _open_listings(world["db"]) == {}


async def test_a_cycle_after_publication_is_unchanged(world):
    world["pools"].append(_pool("broker-a", tags=_UNBACKED))
    await _cycle(world)
    before = await _open_listings(world["db"])

    result = await _cycle(world)

    assert result["counts"] == {}
    assert await _open_listings(world["db"]) == before


async def test_a_term_change_refreshes_the_open_listing_in_place(world):
    world["pools"].append(_pool("broker-a", tags=_UNBACKED))
    await _cycle(world)
    before = await _open_listings(world["db"])

    world["composition"].options = [_option(rate="250")]
    result = await _cycle(world)

    after = await _open_listings(world["db"])
    assert set(after) == set(before)
    assert result["counts"] == {"refresh": 2}
    assert {row["settlement_options"][0]["params"]["rate_hint"] for row in after.values()} == {
        "250"
    }


async def test_a_changed_model_closes_the_listing_and_publishes_nothing_new(world):
    world["pools"].append(_pool("broker-a", tags=_UNBACKED))
    await _cycle(world)
    published = set(await _open_listings(world["db"]))

    world["pools"][0] = _pool("broker-a", tags=_UNBACKED, gpu_model="A100")
    result = await _cycle(world)

    assert await _open_listings(world["db"]) == {}
    assert result["counts"] == {"close": 2}
    for listing_id in published:
        assert (
            await world["db"].load_listing_closed_by(listing_id=listing_id)
            == "reconciliation"
        )
    # Still diverged: the listings stay closed.
    assert (await _cycle(world))["counts"] == {"refuse": 2}


async def test_a_disabled_pool_closes_its_listings(world):
    world["pools"].append(_pool("broker-a", tags=_UNBACKED))
    await _cycle(world)

    world["pools"][0] = _pool("broker-a", tags=_UNBACKED, enabled=False)
    result = await _cycle(world)

    assert await _open_listings(world["db"]) == {}
    assert result["counts"] == {"close": 2}


async def test_a_seller_close_survives_every_later_cycle(world):
    from market_storefront.services.publication_service import close_order

    world["pools"].append(_pool("broker-a", tags=_UNBACKED, gpu_count=1))
    await _cycle(world)
    (listing_id,) = await _open_listings(world["db"])
    await close_order({"listing_id": listing_id}, sqlite_client=world["db"])

    result = await _cycle(world)

    assert await _open_listings(world["db"]) == {}
    assert result["counts"] == {"skip": 1}
    assert await world["db"].load_listing_closed_by(listing_id=listing_id) == "seller"


async def test_an_unresolvable_pool_is_held_not_closed(world):
    world["pools"].append(_pool("broker-a", tags=_UNBACKED))
    world["pools"].append(_pool("broker-b", tags=_UNBACKED))
    await _cycle(world)

    world["pools"][1] = _pool("broker-b", tags={"deliverable_modes": []})
    result = await _cycle(world)

    assert len(await _open_listings(world["db"])) == 4
    assert {a["pool_id"] for a in result["actions"] if a["action"] == "hold"} == {
        "broker-b"
    }


async def test_a_backed_listing_without_disclosed_backing_is_refreshed(world):
    import json
    import sqlite3

    world["pools"].append(_pool("pool-b", tags=_BACKED, gpu_count=1))
    world["composition"].mechanism_fulfillment = {
        "alkahest.v1": True,
        "contact-exchange.v1": False,
    }
    await _cycle(world)
    (listing_id,) = await _open_listings(world["db"])
    with sqlite3.connect(world["db"].db_path) as conn:
        (raw,) = conn.execute(
            "SELECT listing_resource FROM listings WHERE listing_id=?", (listing_id,)
        ).fetchone()
        resource = json.loads(raw)
        del resource["capacity_backing"]
        conn.execute(
            "UPDATE listings SET listing_resource=? WHERE listing_id=?",
            (json.dumps(resource), listing_id),
        )

    result = await _cycle(world)

    assert result["counts"] == {"refresh": 1}
    listing = (await _open_listings(world["db"]))[listing_id]
    assert listing["listing_resource"]["capacity_backing"] == "backed"


async def test_a_migrated_database_publishes_and_closes_without_the_legacy_table(
    world,
):
    """A database migrated to the common binding refuses writes to its legacy
    mapping table; publication and reconciliation never write it."""
    import sqlite3

    with sqlite3.connect(world["db"].db_path) as conn:
        conn.execute(
            "CREATE TABLE derived_compute_listings (listing_id TEXT PRIMARY KEY)"
        )
        for action in ("INSERT", "UPDATE", "DELETE"):
            conn.execute(
                f"""
                CREATE TRIGGER derived_compute_listings_retired_{action.lower()}
                BEFORE {action} ON derived_compute_listings
                BEGIN
                  SELECT RAISE(ABORT, 'derived_compute_listings is retired');
                END
                """
            )
    world["pools"].append(_pool("broker-a", tags=_UNBACKED))
    assert (await _cycle(world))["counts"] == {"publish": 2}

    world["pools"][0] = _pool("broker-a", tags=_UNBACKED, enabled=False)
    result = await _cycle(world)

    assert result["counts"] == {"close": 2}
    assert "fail" not in result["counts"]


async def test_an_older_producer_is_read_as_backed_and_delivery_authorizes(world):
    """No pool carries either declaration: the site predates them."""
    world["pools"].append(_pool("legacy", tags={"deliverable_modes": ["vm"]}, gpu_count=1))

    result = await _cycle(world)

    assert result["counts"] == {"publish": 1}
    (listing_id,) = await _open_listings(world["db"])
    binding = await world["db"].load_listing_binding(listing_id=listing_id)
    assert binding.capacity_backing == "backed"
    # System status says the site is read under the older producer's rule.
    from domains.vms.listings.reconciler import derivation_reports

    assert derivation_reports()[SITE]["compatibility_rule"] is True


async def test_an_unrecognized_backing_value_holds_its_pool(world):
    world["pools"].append(_pool("broker-a", tags=_UNBACKED, gpu_count=1))
    await _cycle(world)

    world["pools"][0] = _pool(
        "broker-a", tags={**_UNBACKED, "capacity_backing": "Unbacked"}, gpu_count=1
    )
    result = await _cycle(world)

    assert len(await _open_listings(world["db"])) == 1
    assert [a["action"] for a in result["actions"]] == ["hold"]


async def test_a_shrunk_declaration_closes_only_the_slices_it_no_longer_covers(world):
    world["pools"].append(_pool("broker-a", tags=_UNBACKED, gpu_count=4))
    await _cycle(world)
    assert len(await _open_listings(world["db"])) == 4

    world["pools"][0] = _pool("broker-a", tags=_UNBACKED, gpu_count=2)
    result = await _cycle(world)

    remaining = await _open_listings(world["db"])
    assert result["counts"] == {"close": 2}
    assert sorted(row["listing_resource"]["gpu_count"] for row in remaining.values()) == [
        1,
        2,
    ]


async def test_supply_moving_to_a_backed_pool_closes_and_republishes(world):
    world["pools"].append(_pool("broker-a", tags=_UNBACKED, gpu_count=1))
    await _cycle(world)
    (old_id,) = await _open_listings(world["db"])
    old_binding = await world["db"].load_listing_binding(listing_id=old_id)

    world["pools"][0] = _pool("broker-a", tags=_UNBACKED, gpu_count=1, enabled=False)
    world["pools"].append(_pool("pool-b", tags=_BACKED, gpu_count=1))
    await _cycle(world)

    (new_id,) = await _open_listings(world["db"])
    new_binding = await world["db"].load_listing_binding(listing_id=new_id)
    assert new_id != old_id
    assert new_binding.capacity_backing == "backed"
    assert new_binding.derivation_key != old_binding.derivation_key
    assert await world["db"].load_listing_binding(listing_id=old_id) == old_binding


async def test_a_pool_recreated_with_the_opposite_backing_is_refused(world):
    """A site rebuilt from scratch can return a pool ID with the other backing."""
    world["pools"].append(_pool("broker-a", tags=_UNBACKED, gpu_count=1))
    await _cycle(world)
    (listing_id,) = await _open_listings(world["db"])
    binding = await world["db"].load_listing_binding(listing_id=listing_id)

    world["pools"][0] = _pool("broker-a", tags=_BACKED, gpu_count=1)
    first = await _cycle(world)
    second = await _cycle(world)

    assert await _open_listings(world["db"]) == {}
    assert first["counts"] == {"close": 1}
    assert second["counts"] == {"refuse": 1}
    assert await world["db"].load_listing_binding(listing_id=listing_id) == binding


async def test_after_a_cycle_no_listing_lacks_an_explicit_backing(world):
    """Counted over every listing, not sampled."""
    import sqlite3

    world["pools"].append(_pool("broker-a", tags=_UNBACKED, gpu_count=3))
    world["pools"].append(_pool("pool-b", tags=_BACKED, gpu_count=2))
    await _cycle(world)
    with sqlite3.connect(world["db"].db_path) as conn:
        # Every listing as a storefront that predates the field left it.
        conn.execute(
            "UPDATE listings SET listing_resource = json_remove(listing_resource, "
            "'$.capacity_backing')"
        )

    await _cycle(world)

    with sqlite3.connect(world["db"].db_path) as conn:
        rows = conn.execute(
            "SELECT json_extract(l.listing_resource, '$.capacity_backing'), "
            "b.capacity_backing FROM listings l "
            "JOIN storefront_listing_bindings b USING (listing_id)"
        ).fetchall()
    assert len(rows) == 5
    assert all(published == bound for published, bound in rows)
