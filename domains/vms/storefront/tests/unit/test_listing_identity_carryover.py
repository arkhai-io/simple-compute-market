"""A seller's close or pause carries onto the listing succeeding a pre-shape one."""

from __future__ import annotations

import sqlite3

import pytest

from core_storefront.domain_registry import (
    StorefrontListingBinding,
    build_storefront_derivation_key,
)
from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    build_vm_storefront_registry,
)
from market_storefront.publication_binding import prepare_vm_listing_binding
from market_storefront.services.listing_identity_carryover import (
    carry_over_seller_state,
    carryover_report,
)
from market_storefront.utils.sqlite_client import SQLiteClient
from tests.fake_site import TEST_MARKETPLACE_SIGNER

pytestmark = pytest.mark.asyncio


@pytest.fixture
def repository(tmp_path):
    return SQLiteClient(
        db_path=str(tmp_path / "carryover.db"),
        registry=build_vm_storefront_registry(build_vm_storefront_domain()),
    )


def _pre_shape_binding(repository, listing_id: str, *, pool_id: str, gpu_count: int):
    """A binding as it was written before shapes: version 1, a GPU count, no shape."""
    registration = repository.domain_registry.resolve_mode("vm")
    source = {
        "kind": "compute.listing_source",
        "schema_version": 1,
        "payload": {"site_id": "site-a", "pool_id": pool_id, "resource_id": None,
                    "gpu_count": gpu_count},
    }
    return StorefrontListingBinding.from_source_envelope(
        listing_id=listing_id,
        site_id="site-a",
        binding=registration.binding,
        derivation_key=build_storefront_derivation_key(
            site_id="site-a",
            offering_mode=registration.binding.offering_mode,
            binding=registration.binding,
            source_identity=source,
        ),
        source_envelope=source,
        last_reconciled_at="2026-01-01T00:00:00Z",
        capacity_backing="backed",
        pool_id=pool_id,
    )


async def _seed(repository, listing_id, *, status="open", closed_by=None, paused=False,
                gpu_count=2):
    await repository.upsert_listing_with_binding(
        binding=_pre_shape_binding(repository, listing_id, pool_id="gpu", gpu_count=gpu_count),
        status=status,
        closed_by=closed_by,
        paused=paused,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
        listing_resource={
            "pool_id": "gpu", "gpu_model": "H100", "gpu_count": gpu_count,
            "region": "us-east", "sla": 99.0, "offering_mode": "vm",
            "capacity_backing": "backed",
        },
        fulfillment_resource=None,
        max_duration_seconds=3600,
        storefront_url="http://seller",
        seller_principal=TEST_MARKETPLACE_SIGNER.identity,
    )


def _successor_key(gpu_count: int) -> str:
    return prepare_vm_listing_binding(
        listing_id="probe",
        candidate={"site_id": "site-a", "pool_id": "gpu", "capacity_backing": "backed",
                   "listing_shape": {"gpu": {"count": gpu_count, "model": "H100"}}},
    ).derivation_key


def _listing_count(repository) -> int:
    conn = sqlite3.connect(repository.db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    finally:
        conn.close()


async def test_a_seller_closed_listing_gets_a_seller_closed_successor(repository):
    await _seed(repository, "old", status="closed", closed_by="seller", gpu_count=2)

    report = await carry_over_seller_state(repository)

    successor_id = report.successors["old"]
    bound = await repository.load_listing_binding_by_derivation(derivation_key=_successor_key(2))
    assert bound is not None and bound.listing_id == successor_id
    successor = await repository.load_listing(listing_id=successor_id)
    assert (successor["status"], successor["closed_by"]) == ("closed", "seller")


async def test_a_paused_listing_gets_a_paused_successor(repository):
    await _seed(repository, "old", paused=True, gpu_count=1)

    report = await carry_over_seller_state(repository)

    successor = await repository.load_listing(listing_id=report.successors["old"])
    assert (successor["status"], successor["paused"]) == ("open", True)


async def test_reconciliation_closed_and_open_listings_are_left_to_publication(repository):
    await _seed(repository, "closed", status="closed", closed_by="reconciliation")
    await _seed(repository, "open", gpu_count=3)

    report = await carry_over_seller_state(repository)

    assert report.successors == {}
    assert _listing_count(repository) == 2


async def test_carrying_over_again_binds_nothing_new(repository):
    await _seed(repository, "old", status="closed", closed_by="seller")
    first = await carry_over_seller_state(repository)
    count = _listing_count(repository)

    second = await carry_over_seller_state(repository)

    assert second.successors == first.successors
    assert _listing_count(repository) == count
    assert carryover_report() == {
        "carried": 1, "successors": first.successors, "not_carried": {},
    }
