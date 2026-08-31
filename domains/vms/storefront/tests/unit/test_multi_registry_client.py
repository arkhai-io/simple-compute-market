"""Unit tests for MultiRegistryClient.

Each underlying RegistryClient is replaced with a fake — these tests
verify the fan-in / fan-out semantics on top of those fakes (dedupe,
error swallowing, race for first hit) without booting any HTTP transport.
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest

from registry_client import RegistryClientError
from core_storefront.multi_registry_client import (
    MultiRegistryClient,
    RegistryAuthorityTrust,
)
from market_identity import Ed25519Signer, TrustedIdentitySet

_SIGNER = Ed25519Signer(b"\x71" * 32)
_REGISTRY = Ed25519Signer(b"\x72" * 32).identity
_REGISTRY_TRUST = RegistryAuthorityTrust(
    authority="registry-test",
    principals=TrustedIdentitySet(identities=(_REGISTRY,)),
)


def _client(urls: list[str], **kwargs: Any) -> MultiRegistryClient:
    return MultiRegistryClient(
        urls,
        signer=_SIGNER,
        caller_role="seller",
        expected_registries={url: _REGISTRY_TRUST for url in urls},
        **kwargs,
    )

from registry_client.models import (
    ListingListResponse,
    ListingSummary,
)


# Patch the RegistryClient *symbol* used inside MultiRegistryClient so
# every constructed wrapper gets fakes back from its __aenter__.
def _summary(listing_id: str, **overrides: Any) -> ListingSummary:
    base = dict(
        id=listing_id,
        status="open",
        publisher_id=1,
        publisher_principals=TrustedIdentitySet(identities=(_SIGNER.identity,)),
        storefront_url="http://seller:8001",
        offer={},
        accepted_escrows=[],
        max_duration_seconds=3600,
        created_at=None,
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

    def __init__(
        self,
        url: str,
        *,
        api_key: str | None = None,
        signer: Ed25519Signer,
        caller_role: str,
        expected_registries: TrustedIdentitySet,
        registry_authority: str,
    ) -> None:
        self.url = url
        self.api_key = api_key
        self.signer = signer
        self.caller_role = caller_role
        self.expected_registries = expected_registries
        self.registry_authority = registry_authority

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

    async def publish_listing(self, listing, **_kwargs):
        action = self.responses.get(self.url, {}).get("publish_listing")
        if isinstance(action, BaseException):
            raise action
        return action or {"ok": True, "url": self.url}

    async def update_listing(self, listing_id, request, **_kwargs):
        action = self.responses.get(self.url, {}).get("update_listing")
        if isinstance(action, BaseException):
            raise action
        return action or {"ok": True, "url": self.url}

    async def delete_listing(self, listing_id, **_kwargs):
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
        "core_storefront.multi_registry_client.RegistryClient",
        _FakeRegistry,
    ):
        yield


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

class TestListListings:
    @pytest.mark.asyncio
    async def test_merges_unique_listings_across_registries(self):
        from core_storefront.multi_registry_client import MultiRegistryClient
        _FakeRegistry.responses = {
            "http://r1": {"list_listings": ListingListResponse(listings=[_summary("a"), _summary("b")])},
            "http://r2": {"list_listings": ListingListResponse(listings=[_summary("c")])},
        }
        async with _client(["http://r1", "http://r2"]) as rc:
            result = await rc.list_listings(status="open")
        ids = sorted(str(l.id) for l in result.listings)
        assert ids == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_dedupes_collisions_on_listing_id(self):
        """Same listing_id appearing in two registries is one row in
        the merged output — first registry seen wins."""
        from core_storefront.multi_registry_client import MultiRegistryClient
        first = _summary("dup", storefront_url="http://r1-seller")
        second = _summary("dup", storefront_url="http://r2-seller")
        _FakeRegistry.responses = {
            "http://r1": {"list_listings": ListingListResponse(listings=[first])},
            "http://r2": {"list_listings": ListingListResponse(listings=[second])},
        }
        async with _client(["http://r1", "http://r2"]) as rc:
            result = await rc.list_listings()
        assert len(result.listings) == 1
        assert result.listings[0].storefront_url == "http://r1-seller"

    @pytest.mark.asyncio
    async def test_swallows_per_registry_failure(self):
        """One registry returning an error doesn't gate the merge."""
        from core_storefront.multi_registry_client import MultiRegistryClient
        _FakeRegistry.responses = {
            "http://r1": {"list_listings": RuntimeError("registry 1 down")},
            "http://r2": {"list_listings": ListingListResponse(listings=[_summary("only-from-r2")])},
        }
        async with _client(["http://r1", "http://r2"]) as rc:
            result = await rc.list_listings()
        assert [str(l.id) for l in result.listings] == ["only-from-r2"]

    @pytest.mark.asyncio
    async def test_empty_url_list_returns_empty(self):
        from core_storefront.multi_registry_client import MultiRegistryClient
        async with _client([]) as rc:
            result = await rc.list_listings()
        assert result.listings == []


class TestGetListing:
    @pytest.mark.asyncio
    async def test_returns_first_hit(self):
        from core_storefront.multi_registry_client import MultiRegistryClient
        _FakeRegistry.responses = {
            "http://r1": {"get_listing": _summary("found")},
            "http://r2": {"get_listing": _summary("found")},
        }
        async with _client(["http://r1", "http://r2"]) as rc:
            result = await rc.get_listing("found")
        assert str(result.id) == "found"

    @pytest.mark.asyncio
    async def test_falls_back_past_404(self):
        """404 from one registry doesn't kill the lookup — we use the
        other registry's hit."""
        from core_storefront.multi_registry_client import MultiRegistryClient
        _FakeRegistry.responses = {
            "http://r1": {"get_listing": RegistryClientError("GET", "/listings/x", 404, "missing")},
            "http://r2": {"get_listing": _summary("x")},
        }
        async with _client(["http://r1", "http://r2"]) as rc:
            result = await rc.get_listing("x")
        assert str(result.id) == "x"

    @pytest.mark.asyncio
    async def test_raises_404_when_every_registry_404s(self):
        from core_storefront.multi_registry_client import MultiRegistryClient
        _FakeRegistry.responses = {
            "http://r1": {"get_listing": RegistryClientError("GET", "/listings/x", 404, "missing")},
            "http://r2": {"get_listing": RegistryClientError("GET", "/listings/x", 404, "missing")},
        }
        async with _client(["http://r1", "http://r2"]) as rc:
            with pytest.raises(RegistryClientError) as exc_info:
                await rc.get_listing("x")
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

class TestDiscoveryTimeout:
    @pytest.mark.asyncio
    async def test_slow_registry_is_skipped_at_deadline(self):
        """A registry that takes longer than the configured timeout
        is logged and skipped — the merge still returns whoever beat
        the deadline."""
        from core_storefront.multi_registry_client import MultiRegistryClient

        async def slow_list(**kwargs):
            await asyncio.sleep(1.0)
            return ListingListResponse(listings=[_summary("slow")])

        async def fast_list(**kwargs):
            return ListingListResponse(listings=[_summary("fast")])

        # Patch the fake's list_listings per-URL to use the slow/fast
        # bodies. We attach as bound methods on a fresh subclass so the
        # async nature is preserved.
        class _SlowFake(_FakeRegistry):
            async def list_listings(self, **kwargs):
                return await slow_list(**kwargs)

        class _FastFake(_FakeRegistry):
            async def list_listings(self, **kwargs):
                return await fast_list(**kwargs)

        def _factory(url, **kwargs):
            fake_type = _SlowFake if url == "http://slow" else _FastFake
            return fake_type(url, **kwargs)

        with patch(
            "core_storefront.multi_registry_client.RegistryClient",
            _factory,
        ):
            async with _client(["http://slow", "http://fast"], timeout=0.05,) as rc:
                result = await rc.list_listings()
        assert [str(l.id) for l in result.listings] == ["fast"]

    @pytest.mark.asyncio
    async def test_timeout_none_leaves_calls_unbounded(self):
        """``timeout=None`` means rely on the underlying client's
        timeouts — no asyncio.wait_for wrapping."""
        from core_storefront.multi_registry_client import MultiRegistryClient
        _FakeRegistry.responses = {

            "http://r1": {"list_listings": ListingListResponse(listings=[_summary("a")])},
        }
        async with _client(["http://r1"], timeout=None) as rc:
            result = await rc.list_listings()
        assert [str(l.id) for l in result.listings] == ["a"]


class TestRegistryTrustRequirements:
    def test_missing_registry_authority_is_rejected(self):
        with pytest.raises(ValueError, match="missing expected registry authority"):
            MultiRegistryClient(
                ["http://registry"],
                signer=_SIGNER,
                caller_role="seller",
                expected_registries={},
            )

class TestPerRegistryAuth:
    @pytest.mark.asyncio
    async def test_api_key_passed_per_url_to_registry_client(self):
        """Each underlying RegistryClient is constructed with the
        api_key matching its URL — URLs without an entry get
        api_key=None."""
        from core_storefront.multi_registry_client import MultiRegistryClient

        seen: dict[str, _SpyFake] = {}

        class _SpyFake(_FakeRegistry):
            def __init__(self, url, **kwargs):
                super().__init__(url, **kwargs)
                seen[url] = self

        with patch(
            "core_storefront.multi_registry_client.RegistryClient",
            _SpyFake,
        ):
            async with _client(
                ["http://public", "http://private"],
                auth={"http://private": "secret123"},
            ):
                pass
        assert {url: client.api_key for url, client in seen.items()} == {
            "http://public": None,
            "http://private": "secret123",
        }
        for client in seen.values():
            assert client.signer is _SIGNER
            assert client.caller_role == "seller"
            assert client.expected_registries == _REGISTRY_TRUST.principals
            assert client.registry_authority == _REGISTRY_TRUST.authority


class TestPublishListing:
    @pytest.mark.asyncio
    async def test_succeeds_when_at_least_one_registry_accepts(self):
        from core_storefront.multi_registry_client import MultiRegistryClient
        _FakeRegistry.responses = {
            "http://r1": {"publish_listing": RuntimeError("registry 1 down")},
            "http://r2": {"publish_listing": {"ok": True, "url": "http://r2"}},
        }
        async with _client(["http://r1", "http://r2"]) as rc:
            from registry_client.models import ListingRequest
            result = await rc.publish_listing(
                listing=ListingRequest(
                    listing_id="x",
                    offer={},
                    accepted_escrows=[],
                    max_duration_seconds=None,
                ),
            )
        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_raises_when_all_registries_fail(self):
        from core_storefront.multi_registry_client import MultiRegistryClient
        _FakeRegistry.responses = {
            "http://r1": {"publish_listing": RuntimeError("r1 down")},
            "http://r2": {"publish_listing": RuntimeError("r2 down")},
        }
        async with _client(["http://r1", "http://r2"]) as rc:
            from registry_client.models import ListingRequest
            with pytest.raises(RuntimeError, match="failed for all 2"):
                await rc.publish_listing(
                    listing=ListingRequest(
                        listing_id="x",
                        offer={},
                        accepted_escrows=[],
                        max_duration_seconds=None,
                    ),
                )


# ---------------------------------------------------------------------------
# Per-registry writes (publications-table feeders)
# ---------------------------------------------------------------------------

class TestPublishListingPerRegistry:
    """``publish_listing_per_registry`` returns one result per registry,
    including explicit failure outcomes that callers can persist.
    """

    @pytest.mark.asyncio
    async def test_returns_result_per_registry(self):
        from core_storefront.multi_registry_client import MultiRegistryClient
        from registry_client.models import ListingRequest
        _FakeRegistry.responses = {
            "http://r1": {"publish_listing": {"listing_id": "r1-id"}},
            "http://r2": {"publish_listing": {"listing_id": "r2-id"}},
        }
        async with _client(["http://r1", "http://r2"]) as rc:
            payloads = {
                "http://r1": ListingRequest(
                    listing_id="x", offer={"variant": "r1"}, accepted_escrows=[],
                    max_duration_seconds=None,
                ),
                "http://r2": ListingRequest(
                    listing_id="x", offer={"variant": "r2"}, accepted_escrows=[],
                    max_duration_seconds=None,
                ),
            }
            results = await rc.publish_listing_per_registry(
                payloads=payloads,
            )
        assert [r["registry_url"] for r in results] == ["http://r1", "http://r2"]
        assert all(r["success"] for r in results)
        # registry_assigned_id is extracted from the response's listing_id key.
        assert [r["registry_assigned_id"] for r in results] == ["r1-id", "r2-id"]
        # The per-registry payload is preserved on the result so the
        # caller can persist it without re-deriving. ListingRequest's
        # to_dict serialises offer→offer_resource (the registry-wire key).
        assert results[0]["payload"]["offer_resource"] == {"variant": "r1"}
        assert results[1]["payload"]["offer_resource"] == {"variant": "r2"}

    @pytest.mark.asyncio
    async def test_failures_are_reported_not_swallowed(self):
        """Each rejected registry write remains visible in its result."""
        from core_storefront.multi_registry_client import MultiRegistryClient
        from registry_client.models import ListingRequest
        _FakeRegistry.responses = {
            "http://r1": {"publish_listing": RuntimeError("r1 down")},
            "http://r2": {"publish_listing": {"listing_id": "r2-id"}},
        }
        async with _client(["http://r1", "http://r2"]) as rc:
            payloads = {
                url: ListingRequest(
                    listing_id="x", offer={}, accepted_escrows=[], max_duration_seconds=None,
                )
                for url in ("http://r1", "http://r2")
            }
            results = await rc.publish_listing_per_registry(
                payloads=payloads,
            )
        assert results[0]["success"] is False
        assert "r1 down" in (results[0]["error"] or "")
        assert results[1]["success"] is True

    @pytest.mark.asyncio
    async def test_unknown_url_marked_failed_without_call(self):
        """Payload aimed at a URL the client wasn't constructed with —
        result is a synthetic failure, no network call is made."""
        from core_storefront.multi_registry_client import MultiRegistryClient
        from registry_client.models import ListingRequest
        _FakeRegistry.responses = {
            "http://r1": {"publish_listing": {"listing_id": "r1-id"}},
        }
        async with _client(["http://r1"]) as rc:
            payloads = {
                "http://r1": ListingRequest(
                    listing_id="x", offer={}, accepted_escrows=[], max_duration_seconds=None,
                ),
                "http://stranger": ListingRequest(
                    listing_id="x", offer={}, accepted_escrows=[], max_duration_seconds=None,
                ),
            }
            results = await rc.publish_listing_per_registry(
                payloads=payloads,
            )
        stranger = [r for r in results if r["registry_url"] == "http://stranger"][0]
        assert stranger["success"] is False
        assert stranger["error"] == "registry not configured"


class TestUpdateListingPerRegistry:
    @pytest.mark.asyncio
    async def test_distinct_updates_per_registry(self):
        from core_storefront.multi_registry_client import MultiRegistryClient
        from registry_client import UpdateListingRequest
        _FakeRegistry.responses = {
            "http://r1": {"update_listing": {"updated": "r1"}},
            "http://r2": {"update_listing": {"updated": "r2"}},
        }
        async with _client(["http://r1", "http://r2"]) as rc:
            payloads = {
                "http://r1": UpdateListingRequest(
                    updates={"status": "closed"},
                ),
                "http://r2": UpdateListingRequest(
                    updates={"status": "closed"},
                ),
            }
            results = await rc.update_listing_per_registry(
                listing_id="x",
                payloads=payloads,
            )
        assert all(r["success"] for r in results)
        assert results[0]["response"] == {"updated": "r1"}


class TestDeleteListingPerRegistry:
    @pytest.mark.asyncio
    async def test_targets_only_listed_urls(self):
        """The delete-per-registry variant takes a URL subset so callers
        consulting ``publications`` only delete from registries the
        listing actually went to."""
        from core_storefront.multi_registry_client import MultiRegistryClient
        _FakeRegistry.responses = {
            "http://r1": {"delete_listing": None},
            "http://r2": {"delete_listing": None},
        }
        async with _client(["http://r1", "http://r2"]) as rc:
            # Only target r1 — r2 should not receive a call.
            results = await rc.delete_listing_per_registry(
                listing_id="x",
                registry_urls=["http://r1"],
            )
        assert [r["registry_url"] for r in results] == ["http://r1"]
        assert results[0]["success"] is True


class TestUniformWrites:
    """Uniform writes retain the first successful registry response."""

    @pytest.mark.asyncio
    async def test_publish_returns_first_ok(self):
        from core_storefront.multi_registry_client import MultiRegistryClient
        from registry_client.models import ListingRequest
        _FakeRegistry.responses = {
            "http://r1": {"publish_listing": RuntimeError("nope")},
            "http://r2": {"publish_listing": {"ok": True}},
        }
        async with _client(["http://r1", "http://r2"]) as rc:
            result = await rc.publish_listing(
                listing=ListingRequest(
                    listing_id="x",
                    offer={},
                    accepted_escrows=[],
                    max_duration_seconds=None,
                ),
            )
        assert result == {"ok": True}


class TestLegacyAuthenticationArgumentsRejected:
    @pytest.mark.asyncio
    async def test_publish_rejects_positional_private_key(self):
        from registry_client.models import ListingRequest

        listing = ListingRequest(
            listing_id="x",
            offer={},
            accepted_escrows=[],
            max_duration_seconds=None,
        )
        async with _client(["http://r1"]) as rc:
            with pytest.raises(TypeError):
                await rc.publish_listing(listing, "0xlegacy")

    def test_update_request_rejects_embedded_private_key(self):
        from registry_client import UpdateListingRequest

        with pytest.raises(TypeError):
            UpdateListingRequest(
                updates={"status": "closed"},
                private_key="0xlegacy",
            )
