"""Unit tests for MultiRegistryClient.

Each underlying RegistryClient is replaced with a fake — these tests
verify the fan-in / fan-out semantics on top of those fakes (dedupe,
error swallowing, race for first hit, FIRST_COMPLETED on
wait_for_agent_indexed) without booting any HTTP transport.
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest

from registry_client import RegistryClientError
from registry_client.models import (
    AgentIndexedResponse,
    ListingListResponse,
    ListingSummary,
)


# Patch the RegistryClient *symbol* used inside MultiRegistryClient so
# every constructed wrapper gets fakes back from its __aenter__.
def _summary(listing_id: str, **overrides: Any) -> ListingSummary:
    base = dict(
        id=listing_id, status="open", maker_agent_id="http://seller:8001",
        offer={}, demand={}, max_duration_seconds=3600, created_at=None,
    )
    base.update(overrides)
    return ListingSummary(**base)


class _FakeRegistry:
    """Stand-in for ``RegistryClient`` used by MultiRegistryClient.

    Each instance is constructed with ``url`` (positional, matches the
    real client) and exposes async methods that return whatever was
    pre-loaded onto the per-URL ``responses`` map at module level.
    """
    responses: dict[str, dict[str, Any]] = {}

    def __init__(self, url: str) -> None:
        self.url = url

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def list_listings(self, **kwargs):
        action = self.responses.get(self.url, {}).get("list_listings")
        if isinstance(action, BaseException):
            raise action
        return action  # ListingListResponse

    async def get_listing(self, listing_id: str):
        action = self.responses.get(self.url, {}).get("get_listing")
        if callable(action):
            return action(listing_id)
        if isinstance(action, BaseException):
            raise action
        return action

    async def wait_for_agent_indexed(self, agent_id, *, timeout=60.0):
        action = self.responses.get(self.url, {}).get("wait_for_agent_indexed")
        if callable(action):
            return await action()
        if isinstance(action, BaseException):
            raise action
        return action

    async def publish_listing(self, agent_id, listing, private_key):
        action = self.responses.get(self.url, {}).get("publish_listing")
        if isinstance(action, BaseException):
            raise action
        return action or {"ok": True, "url": self.url}

    async def update_listing(self, listing_id, request):
        action = self.responses.get(self.url, {}).get("update_listing")
        if isinstance(action, BaseException):
            raise action
        return action or {"ok": True, "url": self.url}

    async def delete_listing(self, listing_id, private_key):
        action = self.responses.get(self.url, {}).get("delete_listing")
        if isinstance(action, BaseException):
            raise action
        return None


@pytest.fixture(autouse=True)
def _patch_registry_client():
    """Replace ``RegistryClient`` inside ``multi_registry_client`` with
    the fake for every test in this module."""
    _FakeRegistry.responses = {}
    with patch(
        "market_storefront.utils.multi_registry_client.RegistryClient",
        _FakeRegistry,
    ):
        yield


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

class TestListListings:
    @pytest.mark.asyncio
    async def test_merges_unique_listings_across_registries(self):
        from market_storefront.utils.multi_registry_client import MultiRegistryClient
        _FakeRegistry.responses = {
            "http://r1": {"list_listings": ListingListResponse(listings=[_summary("a"), _summary("b")])},
            "http://r2": {"list_listings": ListingListResponse(listings=[_summary("c")])},
        }
        async with MultiRegistryClient(["http://r1", "http://r2"]) as rc:
            result = await rc.list_listings(status="open")
        ids = sorted(str(l.id) for l in result.listings)
        assert ids == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_dedupes_collisions_on_listing_id(self):
        """Same listing_id appearing in two registries is one row in
        the merged output — first registry seen wins."""
        from market_storefront.utils.multi_registry_client import MultiRegistryClient
        first = _summary("dup", maker_agent_id="http://r1-seller")
        second = _summary("dup", maker_agent_id="http://r2-seller")
        _FakeRegistry.responses = {
            "http://r1": {"list_listings": ListingListResponse(listings=[first])},
            "http://r2": {"list_listings": ListingListResponse(listings=[second])},
        }
        async with MultiRegistryClient(["http://r1", "http://r2"]) as rc:
            result = await rc.list_listings()
        assert len(result.listings) == 1
        assert result.listings[0].maker_agent_id == "http://r1-seller"

    @pytest.mark.asyncio
    async def test_swallows_per_registry_failure(self):
        """One registry returning an error doesn't gate the merge."""
        from market_storefront.utils.multi_registry_client import MultiRegistryClient
        _FakeRegistry.responses = {
            "http://r1": {"list_listings": RuntimeError("registry 1 down")},
            "http://r2": {"list_listings": ListingListResponse(listings=[_summary("only-from-r2")])},
        }
        async with MultiRegistryClient(["http://r1", "http://r2"]) as rc:
            result = await rc.list_listings()
        assert [str(l.id) for l in result.listings] == ["only-from-r2"]

    @pytest.mark.asyncio
    async def test_empty_url_list_returns_empty(self):
        from market_storefront.utils.multi_registry_client import MultiRegistryClient
        async with MultiRegistryClient([]) as rc:
            result = await rc.list_listings()
        assert result.listings == []


class TestGetListing:
    @pytest.mark.asyncio
    async def test_returns_first_hit(self):
        from market_storefront.utils.multi_registry_client import MultiRegistryClient
        _FakeRegistry.responses = {
            "http://r1": {"get_listing": _summary("found")},
            "http://r2": {"get_listing": _summary("found")},
        }
        async with MultiRegistryClient(["http://r1", "http://r2"]) as rc:
            result = await rc.get_listing("found")
        assert str(result.id) == "found"

    @pytest.mark.asyncio
    async def test_falls_back_past_404(self):
        """404 from one registry doesn't kill the lookup — we use the
        other registry's hit."""
        from market_storefront.utils.multi_registry_client import MultiRegistryClient
        _FakeRegistry.responses = {
            "http://r1": {"get_listing": RegistryClientError("GET", "/listings/x", 404, "missing")},
            "http://r2": {"get_listing": _summary("x")},
        }
        async with MultiRegistryClient(["http://r1", "http://r2"]) as rc:
            result = await rc.get_listing("x")
        assert str(result.id) == "x"

    @pytest.mark.asyncio
    async def test_raises_404_when_every_registry_404s(self):
        from market_storefront.utils.multi_registry_client import MultiRegistryClient
        _FakeRegistry.responses = {
            "http://r1": {"get_listing": RegistryClientError("GET", "/listings/x", 404, "missing")},
            "http://r2": {"get_listing": RegistryClientError("GET", "/listings/x", 404, "missing")},
        }
        async with MultiRegistryClient(["http://r1", "http://r2"]) as rc:
            with pytest.raises(RegistryClientError) as exc_info:
                await rc.get_listing("x")
        assert exc_info.value.status_code == 404


class TestWaitForAgentIndexed:
    @pytest.mark.asyncio
    async def test_returns_first_indexed_true(self):
        from market_storefront.utils.multi_registry_client import MultiRegistryClient

        async def slow_indexed():
            await asyncio.sleep(0.05)
            return AgentIndexedResponse(indexed=True, agent_id="a", elapsed_ms=50)

        async def fast_not_indexed():
            return AgentIndexedResponse(indexed=False, agent_id="a", elapsed_ms=1)

        _FakeRegistry.responses = {
            "http://r1": {"wait_for_agent_indexed": fast_not_indexed},
            "http://r2": {"wait_for_agent_indexed": slow_indexed},
        }
        async with MultiRegistryClient(["http://r1", "http://r2"]) as rc:
            result = await rc.wait_for_agent_indexed("a", timeout=1.0)
        assert result.indexed is True

    @pytest.mark.asyncio
    async def test_returns_first_seen_when_no_registry_confirms(self):
        from market_storefront.utils.multi_registry_client import MultiRegistryClient
        _FakeRegistry.responses = {
            "http://r1": {"wait_for_agent_indexed": AgentIndexedResponse(indexed=False, agent_id="a", elapsed_ms=10)},
            "http://r2": {"wait_for_agent_indexed": AgentIndexedResponse(indexed=False, agent_id="a", elapsed_ms=10)},
        }
        async with MultiRegistryClient(["http://r1", "http://r2"]) as rc:
            result = await rc.wait_for_agent_indexed("a", timeout=1.0)
        assert result.indexed is False


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

class TestPublishListing:
    @pytest.mark.asyncio
    async def test_succeeds_when_at_least_one_registry_accepts(self):
        from market_storefront.utils.multi_registry_client import MultiRegistryClient
        _FakeRegistry.responses = {
            "http://r1": {"publish_listing": RuntimeError("registry 1 down")},
            "http://r2": {"publish_listing": {"ok": True, "url": "http://r2"}},
        }
        async with MultiRegistryClient(["http://r1", "http://r2"]) as rc:
            from registry_client.models import ListingRequest
            result = await rc.publish_listing(
                "agent-1",
                ListingRequest(listing_id="x", offer={}, demand={}, max_duration_seconds=None),
                "0xkey",
            )
        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_raises_when_all_registries_fail(self):
        from market_storefront.utils.multi_registry_client import MultiRegistryClient
        _FakeRegistry.responses = {
            "http://r1": {"publish_listing": RuntimeError("r1 down")},
            "http://r2": {"publish_listing": RuntimeError("r2 down")},
        }
        async with MultiRegistryClient(["http://r1", "http://r2"]) as rc:
            from registry_client.models import ListingRequest
            with pytest.raises(RuntimeError, match="failed for all 2"):
                await rc.publish_listing(
                    "agent-1",
                    ListingRequest(listing_id="x", offer={}, demand={}, max_duration_seconds=None),
                    "0xkey",
                )
