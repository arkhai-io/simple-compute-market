"""The cross-registry client's per-registry read of a publisher's listings.

Each registry's client is a fake built by the injected client factory, holding
the open listings one registry would serve, page by page. The read must keep
each registry's result apart, read every page, and turn a failure on any page
into an unreachable result for that registry alone.
"""

from __future__ import annotations

from typing import Any

import pytest
from market_identity import Ed25519Signer, TrustedIdentitySet
from registry_client import RegistryClientError
from registry_client.models import ListingListResponse, ListingSummary

from core_storefront.multi_registry_client import (
    MultiRegistryClient,
    RegistryAuthorityTrust,
)

_SIGNER = Ed25519Signer(b"\x41" * 32)
_TRUST = RegistryAuthorityTrust(
    authority="registry-test",
    principals=TrustedIdentitySet(identities=(Ed25519Signer(b"\x42" * 32).identity,)),
)
_A = "https://registry-a.example"
_B = "https://registry-b.example"


class _PagedRegistry:
    """One registry's open listings, served ``limit`` at a time from ``offset``.

    ``fail_at_offset`` makes the page starting there fail, as a registry that
    drops partway through a read does.
    """

    def __init__(self, listing_ids: list[str], *, fail_at_offset: int | None = None):
        self.listing_ids = listing_ids
        self.fail_at_offset = fail_at_offset
        self.reads: list[tuple[Any, str | None, int, int]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    async def list_listings_for_publisher(self, principal, *, status, limit, offset):
        self.reads.append((principal, status, limit, offset))
        if offset == self.fail_at_offset:
            raise RegistryClientError("GET", "/listings", 503, "unavailable")
        page = self.listing_ids[offset : offset + limit]
        return ListingListResponse(
            listings=[ListingSummary(id=listing_id, status="open") for listing_id in page]
        )


def _client(registries: dict[str, _PagedRegistry]) -> MultiRegistryClient:
    return MultiRegistryClient(
        list(registries),
        signer=_SIGNER,
        caller_role="seller",
        expected_registries={url: _TRUST for url in registries},
        client_factory=lambda url, **_kwargs: registries[url],
    )


def _ids(result) -> list[str] | None:
    return None if result.listings is None else [str(item.id) for item in result.listings]


@pytest.mark.asyncio
async def test_each_registry_keeps_its_own_listings_in_configured_order():
    registries = {_A: _PagedRegistry(["a1", "a2"]), _B: _PagedRegistry(["b1"])}

    async with _client(registries) as client:
        results = await client.list_publisher_listings_per_registry(_SIGNER.identity)

    assert [(r.registry_url, _ids(r), r.reachable) for r in results] == [
        (_A, ["a1", "a2"], True),
        (_B, ["b1"], True),
    ]
    assert registries[_A].reads[0][:2] == (_SIGNER.identity, "open")


@pytest.mark.asyncio
async def test_every_page_is_read():
    registry = _PagedRegistry([f"listing-{n}" for n in range(5)])

    async with _client({_A: registry}) as client:
        (result,) = await client.list_publisher_listings_per_registry(
            _SIGNER.identity, page_size=2
        )

    assert _ids(result) == [f"listing-{n}" for n in range(5)]
    assert [offset for *_rest, offset in registry.reads] == [0, 2, 4]


@pytest.mark.asyncio
async def test_a_full_last_page_is_followed_by_an_empty_one():
    registry = _PagedRegistry(["l1", "l2", "l3", "l4"])

    async with _client({_A: registry}) as client:
        (result,) = await client.list_publisher_listings_per_registry(
            _SIGNER.identity, page_size=2
        )

    assert _ids(result) == ["l1", "l2", "l3", "l4"]
    assert [offset for *_rest, offset in registry.reads] == [0, 2, 4]


@pytest.mark.asyncio
async def test_a_failure_on_a_later_page_makes_that_registry_unreachable_alone():
    registries = {
        _A: _PagedRegistry(["a1", "a2", "a3"], fail_at_offset=2),
        _B: _PagedRegistry(["b1", "b2", "b3"]),
    }

    async with _client(registries) as client:
        results = await client.list_publisher_listings_per_registry(
            _SIGNER.identity, page_size=2
        )

    by_url = {result.registry_url: result for result in results}
    # The first page answered, but a partial set is no set: nothing is kept.
    assert by_url[_A].listings is None
    assert not by_url[_A].reachable
    assert "503" in (by_url[_A].error or "")
    assert _ids(by_url[_B]) == ["b1", "b2", "b3"]


@pytest.mark.asyncio
async def test_a_page_size_below_one_is_refused():
    async with _client({_A: _PagedRegistry([])}) as client:
        with pytest.raises(ValueError, match="page_size"):
            await client.list_publisher_listings_per_registry(
                _SIGNER.identity, page_size=0
            )
