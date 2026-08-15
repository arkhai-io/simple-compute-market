from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from market_capacity_publication import (
    BoundListing,
    CapacityBinding,
    CapacityBindingError,
    PublicationCandidate,
    PublicationRuntime,
    ReconciliationPlan,
)


class Repository:
    def __init__(self):
        self.statuses = {}
        self.publications = []

    async def update_listing(self, *, listing_id, status):
        self.statuses[listing_id] = status

    async def load_publications(self, *, listing_id):
        return [row for row in self.publications if row["listing_id"] == listing_id]

    async def upsert_publication(self, **row):
        self.publications.append(row)


class Hooks:
    def __init__(self, bindings):
        self.bindings = bindings
        self.validated = []

    def validate_candidate(self, candidate):
        offer = candidate.payload["offer_resource"]
        if offer["virtualization_type"] != candidate.binding.offering_mode:
            raise CapacityBindingError("advertised offering mode differs from binding")
        self.validated.append(candidate.listing_id)

    async def binding_for_listing(self, listing_id):
        return self.bindings.get(listing_id)


def runtime(repository, hooks):
    return PublicationRuntime(
        repository=repository,
        hooks=hooks,
        enabled=False,
        registry_urls=(),
        registry_client_factory=AsyncMock(),
        listing_request_factory=dict,
        update_listing_request_factory=dict,
        storefront_url="https://seller.example",
    )


def candidate(listing_id="listing-1", binding=None):
    binding = binding or CapacityBinding("site-a", "vm", "pool-a")
    return PublicationCandidate(
        listing_id=listing_id,
        binding=binding,
        payload={
            "listing_id": listing_id,
            "seller_principal": {"scheme": "ed25519", "identifier": "seller"},
            "offer_resource": {"virtualization_type": "vm"},
            "accepted_escrows": [],
            "settlement_options": [],
            "demands": [],
        },
    )


@pytest.mark.asyncio
async def test_publish_requires_exact_durable_site_and_mode_binding():
    repository = Repository()
    expected = CapacityBinding("site-a", "vm", "pool-a")
    hooks = Hooks({"listing-1": expected})

    result = await runtime(repository, hooks).publish(candidate())

    assert result["status"] == "skipped"
    assert hooks.validated == ["listing-1"]

    with pytest.raises(CapacityBindingError, match="does not match"):
        await runtime(repository, hooks).publish(
            candidate(binding=CapacityBinding("site-b", "vm", "pool-a"))
        )


@pytest.mark.asyncio
async def test_candidate_codec_must_project_exact_offering_mode():
    repository = Repository()
    binding = CapacityBinding("site-a", "bare_metal", "pool-a")
    hooks = Hooks({"listing-1": binding})

    with pytest.raises(CapacityBindingError, match="advertised offering mode"):
        await runtime(repository, hooks).publish(candidate(binding=binding))


@pytest.mark.asyncio
async def test_reconciliation_owns_close_then_reopen_mechanics():
    repository = Repository()
    binding = CapacityBinding("site-a", "vm", "pool-a")
    hooks = Hooks({"close-me": binding, "reopen-me": binding})
    publication = runtime(repository, hooks)

    result = await publication.reconcile(
        ReconciliationPlan(
            close=(BoundListing("close-me", binding),),
            reopen=(candidate("reopen-me", binding),),
        )
    )

    assert repository.statuses == {"close-me": "closed", "reopen-me": "open"}
    assert result == {"closed": ("close-me",), "reopened": ("reopen-me",)}


@pytest.mark.asyncio
async def test_reconciliation_rejects_conflicting_plan():
    repository = Repository()
    binding = CapacityBinding("site-a", "vm", "pool-a")
    hooks = Hooks({"listing-1": binding})

    with pytest.raises(ValueError, match="cannot close and reopen"):
        await runtime(repository, hooks).reconcile(
            ReconciliationPlan(
                close=(BoundListing("listing-1", binding),),
                reopen=(candidate(binding=binding),),
            )
        )
