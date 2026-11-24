"""A storefront retires registry listings it does not hold open.

The registries are a fake holding each registry's open listings under the
storefront's principal; the repository holds the storefront's own listings. A
pass closes, at each registry it can read to the end, every open listing of an
offering mode the storefront serves that it does not hold open, and a preview
reports those closes without making them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from core_storefront.multi_registry_client import RegistryListings
from market_resource_pools_contracts.backing import BACKED

from market_capacity_publication import (
    NOT_HELD,
    PublicationBinding,
    PublicationCycleReport,
    PublicationRuntime,
    retire_unheld_listings,
)

_A = "https://registry-a.example"
_B = "https://registry-b.example"
_STOREFRONT = "https://seller.example"
_PUBLISHER = object()


@dataclass(frozen=True)
class _Listing:
    """What the sweep reads of a registry listing: its ID and resource."""

    id: str
    listing_resource: dict[str, Any] = field(default_factory=dict)


def _vm(listing_id: str) -> _Listing:
    return _Listing(listing_id, {"offering_mode": "vm"})


def _bare_metal(listing_id: str) -> _Listing:
    return _Listing(listing_id, {"offering_mode": "bare_metal"})


class _Repository:
    """The storefront's listings by status, with no publication record kept."""

    def __init__(self, statuses: dict[str, str] | None = None):
        self.statuses = dict(statuses or {})

    async def open_listing_ids(self):
        return {listing for listing, status in self.statuses.items() if status == "open"}


class _Registries:
    """Each registry's open listings; ``unreachable`` registries fail their read,
    and ``refusing`` ones refuse the close."""

    def __init__(self, listings: dict[str, list[_Listing]]):
        self.listings = {url: list(items) for url, items in listings.items()}
        self.urls = tuple(self.listings)
        self.unreachable: set[str] = set()
        self.refusing: set[str] = set()
        self.publishers: list[Any] = []
        self.closes: list[tuple[str, str]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def list_publisher_listings_per_registry(self, principal):
        self.publishers.append(principal)
        return [
            RegistryListings(url, None, "unavailable")
            if url in self.unreachable
            else RegistryListings(url, tuple(self.listings[url]))
            for url in self.urls
        ]

    async def update_listing_per_registry(self, *, listing_id, payloads):
        results = []
        for url, request in payloads.items():
            assert request == {"status": "closed"}
            ok = url not in self.refusing
            if ok:
                self.closes.append((url, listing_id))
                self.listings[url] = [
                    item for item in self.listings[url] if item.id != listing_id
                ]
            results.append(
                {"registry_url": url, "success": ok, "error": None if ok else "refused"}
            )
        return results

    def open_at(self, url: str) -> list[str]:
        return [item.id for item in self.listings[url]]


class _Hooks:
    def __init__(self, modes=("vm",)):
        self.modes = modes

    async def binding_for_listing(self, listing_id):
        return PublicationBinding("site-a", "vm", "pool-a", BACKED)

    def validate_candidate(self, candidate):
        return None

    def registry_publisher(self):
        return _PUBLISHER

    def served_offering_modes(self):
        return self.modes


def _runtime(repository, registries, *, hooks=None, enabled=True):
    return PublicationRuntime(
        repository=repository,
        hooks=hooks or _Hooks(),
        enabled=enabled,
        registry_urls=registries.urls,
        registry_client_factory=lambda: registries,
        listing_request_factory=dict,
        update_listing_request_factory=lambda *, updates: dict(updates),
        storefront_url=_STOREFRONT,
    )


async def _pass(runtime, *, dry_run=False) -> PublicationCycleReport:
    report = PublicationCycleReport(dry_run=dry_run)
    await retire_unheld_listings(runtime, report)
    return report


@pytest.mark.asyncio
async def test_an_open_listing_the_storefront_has_no_record_of_is_closed():
    registries = _Registries({_A: [_vm("unknown-1")]})

    report = await _pass(_runtime(_Repository(), registries))

    assert registries.closes == [(_A, "unknown-1")]
    assert registries.publishers == [_PUBLISHER]
    assert report.of("close") == [
        {"action": "close", "listing_id": "unknown-1", "registry": _A, "reason": NOT_HELD}
    ]


@pytest.mark.asyncio
async def test_a_listing_closed_locally_but_open_at_a_registry_is_closed_there():
    """The repository keeps no publication record of it at that registry, so
    convergence would never send the close."""
    registries = _Registries({_A: [_vm("closed-locally")]})

    await _pass(_runtime(_Repository({"closed-locally": "closed"}), registries))

    assert registries.closes == [(_A, "closed-locally")]


@pytest.mark.asyncio
async def test_another_offering_mode_and_a_held_listing_stay_open():
    """``held-in-outage`` is open locally, as a listing the storefront holds
    through its site's outage stays; the sweep reads only the local status, so
    no registry closes it. The outage itself is driven in the VM storefront's
    publication-loop tests."""
    registries = _Registries(
        {_A: [_bare_metal("bare-metal-1"), _vm("held-in-outage"), _vm("unknown-1")]}
    )

    report = await _pass(_runtime(_Repository({"held-in-outage": "open"}), registries))

    assert registries.open_at(_A) == ["bare-metal-1", "held-in-outage"]
    assert [item["listing_id"] for item in report.of("close")] == ["unknown-1"]


@pytest.mark.asyncio
async def test_a_storefront_serving_two_modes_sweeps_both():
    registries = _Registries({_A: [_bare_metal("bare-metal-1"), _vm("vm-1")]})

    await _pass(
        _runtime(_Repository(), registries, hooks=_Hooks(modes=("vm", "bare_metal")))
    )

    assert sorted(registries.closes) == [(_A, "bare-metal-1"), (_A, "vm-1")]


@pytest.mark.asyncio
async def test_an_unreachable_registry_is_left_and_the_others_are_swept():
    registries = _Registries({_A: [_vm("unknown-1")], _B: [_vm("unknown-1")]})
    registries.unreachable = {_A}

    report = await _pass(_runtime(_Repository(), registries))

    assert registries.closes == [(_B, "unknown-1")]
    assert registries.open_at(_A) == ["unknown-1"]
    assert report.of("skip") == [
        {"action": "skip", "registry": _A, "reason": "registry_unreachable"}
    ]


@pytest.mark.asyncio
async def test_a_preview_reports_each_close_and_makes_none():
    registries = _Registries({_A: [_vm("unknown-1")], _B: [_vm("unknown-1")]})

    report = await _pass(_runtime(_Repository(), registries), dry_run=True)

    assert registries.closes == []
    assert report.of("close") == [
        {"action": "close", "listing_id": "unknown-1", "registry": _A, "reason": NOT_HELD},
        {"action": "close", "listing_id": "unknown-1", "registry": _B, "reason": NOT_HELD},
    ]


@pytest.mark.asyncio
async def test_a_close_a_registry_refuses_is_reported_and_found_again_next_pass():
    registries = _Registries({_A: [_vm("unknown-1")]})
    registries.refusing = {_A}
    runtime = _runtime(_Repository(), registries)

    report = await _pass(runtime)

    assert report.of("fail") == [
        {
            "action": "fail",
            "listing_id": "unknown-1",
            "registry": _A,
            "reason": "registry_close_failed",
            "error": "refused",
        }
    ]
    registries.refusing.clear()
    await _pass(runtime)
    assert registries.closes == [(_A, "unknown-1")]


@pytest.mark.asyncio
async def test_publication_turned_off_sweeps_nothing():
    registries = _Registries({_A: [_vm("unknown-1")]})

    report = await _pass(_runtime(_Repository(), registries, enabled=False))

    assert registries.publishers == []
    assert report.actions == []
