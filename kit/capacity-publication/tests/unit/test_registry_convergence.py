"""Registries converge on each listing's local status.

A registry that misses a close or a reopen is recorded as failed, and the next
``converge`` resends what the local listing implies to that registry alone.
"""

from __future__ import annotations

import pytest

from market_capacity_publication import (
    BoundListing,
    CapacityBinding,
    PublicationCandidate,
    PublicationRuntime,
)

_A = "https://registry-a.example"
_B = "https://registry-b.example"
_STOREFRONT = "https://seller.example"
_BINDING = CapacityBinding("site-a", "vm", "pool-a")


class _Repository:
    """Listings and the latest record per listing and registry, with the
    divergence rule the storefront's persistence applies."""

    def __init__(self):
        self.listings = {}
        self.records = {}

    async def update_listing(self, *, listing_id, status, closed_by=None, reopened_by=None):
        self.listings[listing_id]["status"] = status

    async def load_listing(self, *, listing_id):
        return dict(self.listings[listing_id])

    async def load_publications(self, *, listing_id):
        return [
            {"listing_id": listing, "registry_url": url, "status": status}
            for (listing, url), status in self.records.items()
            if listing == listing_id
        ]

    async def upsert_publication(self, *, listing_id, registry_url, status, **_):
        self.records[(listing_id, registry_url)] = status

    async def list_publication_divergence(self, *, registry_urls):
        wanted = {"open": "published", "closed": "unpublished"}
        return [
            {
                "listing_id": listing,
                "listing_status": self.listings[listing]["status"],
                "registry_url": url,
            }
            for (listing, url), status in sorted(self.records.items())
            if url in registry_urls
            and self.listings[listing]["status"] in wanted
            and status != wanted[self.listings[listing]["status"]]
        ]


class _Registries:
    """Two registries; ``failing`` names (operation, url) pairs that fail."""

    urls = (_A, _B)

    def __init__(self):
        self.failing = set()
        self.sent = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def _results(self, operation, payloads):
        results = []
        for url in payloads:
            self.sent.append((operation, url))
            ok = (operation, url) not in self.failing
            results.append(
                {"registry_url": url, "success": ok, "response": {"ok": ok} if ok else None,
                 "error": None if ok else "unreachable"}
            )
        return results

    async def publish_listing_per_registry(self, *, payloads):
        return self._results("publish", payloads)

    async def update_listing_per_registry(self, *, listing_id, payloads):
        status = next(iter(payloads.values()))["status"]
        return self._results(status, payloads)


class _Hooks:
    async def binding_for_listing(self, listing_id):
        return _BINDING

    def validate_candidate(self, candidate):
        return None


def _runtime(repository, registries):
    return PublicationRuntime(
        repository=repository,
        hooks=_Hooks(),
        enabled=True,
        registry_urls=registries.urls,
        registry_client_factory=lambda: registries,
        listing_request_factory=dict,
        update_listing_request_factory=lambda *, updates: dict(updates),
        storefront_url=_STOREFRONT,
    )


def _listing(listing_id="listing-1", status="open"):
    return {
        "listing_id": listing_id,
        "status": status,
        "listing_resource": {"offering_mode": "vm"},
        "accepted_escrows": [],
        "settlement_options": [],
        "demands": [],
        "storefront_url": _STOREFRONT,
    }


def _candidate(repository, listing_id="listing-1"):
    return PublicationCandidate(listing_id, _BINDING, repository.listings[listing_id])


@pytest.fixture
def world():
    repository, registries = _Repository(), _Registries()
    runtime = _runtime(repository, registries)
    repository.listings["listing-1"] = _listing()
    return repository, registries, runtime


@pytest.mark.asyncio
async def test_a_registry_that_missed_a_close_is_sent_the_close_alone(world):
    repository, registries, runtime = world
    await runtime.publish(_candidate(repository))
    registries.failing = {("closed", _B)}

    await runtime.close(BoundListing("listing-1", _BINDING), closed_by="seller")

    (divergence,) = await runtime.publication_divergence()
    assert (divergence.listing_status, divergence.registry_urls) == ("closed", (_B,))
    registries.failing.clear()
    registries.sent.clear()

    result = await runtime.converge()

    assert registries.sent == [("closed", _B)]
    assert result == {"repaired": ("listing-1",), "unrepaired": ()}
    assert await runtime.publication_divergence() == ()


@pytest.mark.asyncio
async def test_a_registry_left_closed_by_a_failed_reopen_is_republished_and_reopened(world):
    repository, registries, runtime = world
    await runtime.publish(_candidate(repository))
    await runtime.close(BoundListing("listing-1", _BINDING), closed_by="reconciliation")
    registries.failing = {("open", _B)}

    await runtime.reopen(_candidate(repository), reopened_by="reconciliation")

    (divergence,) = await runtime.publication_divergence()
    assert (divergence.listing_status, divergence.registry_urls) == ("open", (_B,))
    registries.failing.clear()
    registries.sent.clear()

    result = await runtime.converge()

    assert registries.sent == [("publish", _B), ("open", _B)]
    assert result == {"repaired": ("listing-1",), "unrepaired": ()}


@pytest.mark.asyncio
async def test_a_registry_still_unreachable_stays_diverged_for_the_next_pass(world):
    repository, registries, runtime = world
    await runtime.publish(_candidate(repository))
    registries.failing = {("closed", _B)}
    await runtime.close(BoundListing("listing-1", _BINDING), closed_by="seller")

    result = await runtime.converge()

    assert result == {"repaired": (), "unrepaired": ("listing-1",)}
    assert repository.records[("listing-1", _B)] == "failed"
    assert repository.records[("listing-1", _A)] == "unpublished"
