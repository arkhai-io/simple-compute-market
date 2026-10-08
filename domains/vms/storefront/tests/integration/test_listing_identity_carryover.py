"""A seller's close or pause carries onto the listing succeeding a pre-shape one."""

from __future__ import annotations

import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

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
from tests._settings_overrides import settings_overrides
from tests.fake_site import TEST_MARKETPLACE_SIGNER

pytestmark = pytest.mark.asyncio

_REGISTRY_URL = "http://registry.test"


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


async def _bound_successor(repository, gpu_count, *, status="open", closed_by=None):
    """A successor bound before the carry-over ran, as after a partial upgrade."""
    binding = prepare_vm_listing_binding(
        listing_id=f"successor-{gpu_count}",
        candidate={"site_id": "site-a", "pool_id": "gpu", "capacity_backing": "backed",
                   "listing_shape": {"gpu": {"count": gpu_count, "model": "H100"}}},
    )
    await repository.upsert_listing_with_binding(
        binding=binding,
        status=status,
        closed_by=closed_by,
        created_at="2026-01-02T00:00:00",
        updated_at="2026-01-02T00:00:00",
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
    return binding.listing_id


def _registry_double():
    """Registries are an external service: doubled where the storefront wraps them."""
    client = MagicMock()
    client.urls = [_REGISTRY_URL]
    client.delete_listing_per_registry = AsyncMock(return_value=[])
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=None)
    return context, client


async def test_an_existing_open_successor_is_closed_as_its_seller(repository):
    await _seed(repository, "old", status="closed", closed_by="seller", gpu_count=2)
    successor_id = await _bound_successor(repository, 2)
    context, registry = _registry_double()

    with settings_overrides(**{"registry.urls": [_REGISTRY_URL]}), patch(
        "market_storefront.services.publication_service._make_registry_client",
        return_value=context,
    ):
        report = await carry_over_seller_state(repository)

    assert report.successors == {"old": successor_id}
    successor = await repository.load_listing(listing_id=successor_id)
    assert (successor["status"], successor["closed_by"]) == ("closed", "seller")


async def test_an_existing_open_successor_of_a_paused_listing_is_paused(repository):
    await _seed(repository, "old", paused=True, gpu_count=1)
    successor_id = await _bound_successor(repository, 1)

    await carry_over_seller_state(repository)

    successor = await repository.load_listing(listing_id=successor_id)
    assert (successor["status"], successor["paused"]) == ("open", True)


async def test_a_successor_reconciliation_closed_is_reported(repository):
    await _seed(repository, "old", status="closed", closed_by="seller", gpu_count=2)
    await _bound_successor(repository, 2, status="closed", closed_by="reconciliation")

    report = await carry_over_seller_state(repository)

    assert report.not_carried == {"old": "successor already closed by reconciliation"}
