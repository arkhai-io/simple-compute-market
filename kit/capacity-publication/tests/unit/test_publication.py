from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from market_capacity_publication import (
    BoundListing,
    CapacityBinding,
    CapacityBindingError,
    UnbackedBinding,
    PublicationCandidate,
    PublicationRuntime,
    ReconciliationPlan,
)


class Repository:
    def __init__(self):
        self.statuses = {}
        self.closed_by = {}
        self.publications = []

    async def update_listing(self, *, listing_id, status, closed_by=None):
        self.statuses[listing_id] = status
        self.closed_by[listing_id] = closed_by

    async def load_publications(self, *, listing_id):
        return [row for row in self.publications if row["listing_id"] == listing_id]

    async def upsert_publication(self, **row):
        self.publications.append(row)


class Hooks:
    def __init__(self, bindings):
        self.bindings = bindings
        self.validated = []

    def validate_candidate(self, candidate):
        listing_resource = candidate.payload["listing_resource"]
        if listing_resource["offering_mode"] != candidate.binding.offering_mode:
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
            "listing_resource": {"offering_mode": "vm"},
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

    assert result["status"] == "disabled"
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
    assert repository.closed_by == {"close-me": "reconciliation", "reopen-me": None}
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


@pytest.mark.asyncio
async def test_unbacked_listing_publishes_under_its_own_binding():
    repository = Repository()
    binding = UnbackedBinding("site-a", "vm", "pool-a")
    hooks = Hooks({"listing-1": binding})

    await runtime(repository, hooks).publish(candidate(binding=binding))

    assert hooks.validated == ["listing-1"]


@pytest.mark.asyncio
async def test_backing_mismatch_with_durable_binding_is_refused():
    repository = Repository()
    hooks = Hooks({"listing-1": UnbackedBinding("site-a", "vm", "pool-a")})

    with pytest.raises(CapacityBindingError, match="does not match"):
        await runtime(repository, hooks).publish(
            candidate(binding=CapacityBinding("site-a", "vm", "pool-a"))
        )


@pytest.mark.asyncio
async def test_seller_close_records_its_reason():
    repository = Repository()
    binding = CapacityBinding("site-a", "vm", "pool-a")
    hooks = Hooks({"listing-1": binding})

    await runtime(repository, hooks).close(
        BoundListing("listing-1", binding), closed_by="seller"
    )

    assert repository.closed_by == {"listing-1": "seller"}


@pytest.mark.asyncio
@pytest.mark.parametrize("closed_by", [None, "", "operator"])
async def test_close_without_a_known_reason_is_refused_before_any_write(closed_by):
    repository = Repository()
    binding = CapacityBinding("site-a", "vm", "pool-a")
    hooks = Hooks({"listing-1": binding})

    with pytest.raises(ValueError, match="closed_by"):
        await runtime(repository, hooks).close(
            BoundListing("listing-1", binding), closed_by=closed_by
        )

    assert repository.statuses == {}


class _RecordingRegistry:
    urls = ("https://registry.example",)

    def __init__(self):
        self.published = []
        self.updates = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def publish_listing_per_registry(self, *, payloads):
        self.published.extend(payloads.values())
        return [
            {"registry_url": url, "success": True, "response": {"ok": True}}
            for url in payloads
        ]

    async def update_listing_per_registry(self, *, listing_id, payloads):
        self.updates.extend((listing_id, request) for request in payloads.values())
        return [
            {"registry_url": url, "success": True, "response": {"ok": True}}
            for url in payloads
        ]


@pytest.mark.asyncio
async def test_reopen_marks_the_listing_open_at_every_registry():
    """A registry keeps a republished listing's status, so reopen sets it."""
    repository = Repository()
    binding = CapacityBinding("site-a", "vm", "pool-a")
    hooks = Hooks({"listing-1": binding})
    registry = _RecordingRegistry()
    publication = PublicationRuntime(
        repository=repository,
        hooks=hooks,
        enabled=True,
        registry_urls=registry.urls,
        registry_client_factory=lambda: registry,
        listing_request_factory=dict,
        update_listing_request_factory=dict,
        storefront_url="https://seller.example",
    )
    listing = candidate(binding=binding)
    listing.payload["storefront_url"] = "https://seller.example"

    result = await publication.reopen(listing)

    assert result["status"] == "published"
    assert repository.statuses == {"listing-1": "open"}
    assert registry.updates == [("listing-1", {"updates": {"status": "open"}})]
