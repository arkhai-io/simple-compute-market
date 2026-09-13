"""Publication lifecycle integration through the authenticated registry client."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from core_storefront.auth import REQUEST_ID_HEADER, signed_response_headers
from core_storefront.multi_registry_client import (
    MultiRegistryClient,
    RegistryAuthorityTrust,
)
from market_identity import Ed25519Signer, TrustedIdentitySet
from registry_client import ListingRequest, RegistryClient, UpdateListingRequest

from market_capacity_publication import (
    CapacityBinding,
    DisabledPublicationPolicy,
    PublicationCandidate,
    PublicationRuntime,
    PublicationTransition,
)

_URL = "https://registry.example"
_STOREFRONT_URL = "https://storefront.example"
_LISTING_ID = "listing-fixture-1"


class _Repository:
    def __init__(self, binding: CapacityBinding) -> None:
        self.binding = binding
        self.publications: list[dict[str, Any]] = []

    async def load_listing_binding(self, *, listing_id: str) -> CapacityBinding:
        assert listing_id == _LISTING_ID
        return self.binding

    async def update_listing(self, *, listing_id: str, status: str) -> None:
        raise AssertionError("the domain commit hook owns lifecycle mutation")

    async def load_publications(self, *, listing_id: str) -> list[dict[str, Any]]:
        return []

    async def upsert_publication(self, **row: Any) -> None:
        self.publications.append(row)


class _Hooks:
    def __init__(self, repository: _Repository) -> None:
        self.repository = repository
        self.commits: list[PublicationTransition] = []

    def validate_candidate(self, candidate: PublicationCandidate[dict]) -> None:
        assert candidate.binding == self.repository.binding

    async def binding_for_listing(self, listing_id: str) -> CapacityBinding:
        return await self.repository.load_listing_binding(listing_id=listing_id)

    async def validate_lifecycle(
        self,
        candidate: PublicationCandidate[dict],
        transition: PublicationTransition,
        *,
        previous_local_committed: bool,
    ) -> None:
        assert previous_local_committed is False
        assert candidate.listing_id == _LISTING_ID
        assert transition is PublicationTransition.REOPEN

    def disabled_publication_policy(
        self,
        transition: PublicationTransition,
    ) -> DisabledPublicationPolicy:
        return DisabledPublicationPolicy.SKIP_LOCAL

    async def commit_candidate(
        self,
        candidate: PublicationCandidate[dict],
        transition: PublicationTransition,
    ) -> None:
        self.commits.append(transition)


@pytest.mark.asyncio
async def test_reopen_uses_typed_authenticated_same_target_readback(monkeypatch):
    seller = Ed25519Signer(bytes.fromhex("41" * 32))
    registry = Ed25519Signer(bytes.fromhex("42" * 32))
    trusted_registry = TrustedIdentitySet(identities=(registry.identity,))
    request_methods: list[str] = []
    record = {
        "listing_id": _LISTING_ID,
        "status": "closed",
        "publisher_principals": {
            "identities": [seller.identity.model_dump(mode="json")]
        },
        "storefront_url": _STOREFRONT_URL,
        "offer_resource": {"virtualization_type": "bare_metal", "generation": 1},
        "accepted_escrows": [],
        "settlement_options": [],
        "demands": [],
        "max_duration_seconds": 3600,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer fixture-write-token"
        request_methods.append(request.method)
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["status"] == "open"
            record.update(body)
            response_body = {"listing_id": _LISTING_ID, "status": "open"}
            operation = "listing.publish"
            resource = "listings"
            status = 201
        else:
            response_body = dict(record)
            operation = "listing.get"
            resource = _LISTING_ID
            status = 200
        headers = signed_response_headers(
            signer=registry,
            role="registry",
            method=request.method,
            operation=operation,
            resource=resource,
            request_id=request.headers[REQUEST_ID_HEADER],
            status=status,
            body=response_body,
        )
        return httpx.Response(status, json=response_body, headers=headers)

    class _TransportRegistryClient(RegistryClient):
        def __init__(self, base_url: str, **kwargs: Any) -> None:
            super().__init__(
                base_url,
                transport=httpx.MockTransport(handler),
                **kwargs,
            )

    monkeypatch.setattr(
        "core_storefront.multi_registry_client.RegistryClient",
        _TransportRegistryClient,
    )
    binding = CapacityBinding("site-a", "bare_metal", "resource-a")
    repository = _Repository(binding)
    hooks = _Hooks(repository)
    runtime = PublicationRuntime(
        repository=repository,
        hooks=hooks,
        enabled=True,
        registry_urls=(_URL,),
        registry_client_factory=lambda: MultiRegistryClient(
            [_URL],
            signer=seller,
            caller_role="seller",
            expected_registries={
                _URL: RegistryAuthorityTrust(
                    authority="registry-fixture",
                    principals=trusted_registry,
                )
            },
            auth={_URL: "fixture-write-token"},
        ),
        listing_request_factory=ListingRequest,
        update_listing_request_factory=UpdateListingRequest,
        storefront_url=_STOREFRONT_URL,
    )
    candidate = PublicationCandidate(
        _LISTING_ID,
        binding,
        {
            "listing_id": _LISTING_ID,
            "storefront_url": _STOREFRONT_URL,
            "offer_resource": {
                "virtualization_type": "bare_metal",
                "generation": 2,
            },
            "accepted_escrows": [],
            "settlement_options": [],
            "demands": [],
            "max_duration_seconds": 3600,
        },
    )

    result = await runtime.reopen(candidate)

    assert result.status == "published"
    assert result.local_committed is True
    assert request_methods == ["GET", "POST", "GET"]
    assert hooks.commits == [PublicationTransition.REOPEN]
    assert repository.publications[0]["status"] == "published"
    assert record["offer_resource"]["generation"] == 2
