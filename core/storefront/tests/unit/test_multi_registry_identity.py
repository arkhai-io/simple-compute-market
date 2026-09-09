from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest
from market_identity import Ed25519Signer, TrustedIdentitySet
from registry_client import RegistryClientError

from core_storefront.multi_registry_client import (
    MultiRegistryClient,
    RegistryAuthorityTrust,
    RegistryTargetIdentity,
)


def test_multi_registry_requires_exact_authority_pin_per_normalized_url() -> None:
    signer = Ed25519Signer(bytes(range(32)))
    authority = Ed25519Signer(bytes(range(1, 33))).identity
    trust = RegistryAuthorityTrust(
        authority="registry-a",
        principals=TrustedIdentitySet(identities=(authority,)),
    )

    client = MultiRegistryClient(
        ["HTTPS://REGISTRY.EXAMPLE/"],
        signer=signer,
        caller_role="seller",
        expected_registries={"https://registry.example": trust},
    )
    assert client.urls == ["HTTPS://REGISTRY.EXAMPLE/"]

    with pytest.raises(ValueError, match="missing expected registry authority"):
        MultiRegistryClient(
            ["https://registry.example"],
            signer=signer,
            caller_role="seller",
            expected_registries={},
        )
    with pytest.raises(ValueError, match="must be 'seller'"):
        MultiRegistryClient(
            ["https://registry.example"],
            signer=signer,
            caller_role="buyer",
            expected_registries={"https://registry.example": trust},
        )


def test_multi_registry_rejects_ambiguous_normalized_configuration() -> None:
    signer = Ed25519Signer(bytes(range(32)))
    authority = Ed25519Signer(bytes(range(1, 33))).identity
    trust = RegistryAuthorityTrust(
        authority="registry-a",
        principals=TrustedIdentitySet(identities=(authority,)),
    )

    with pytest.raises(ValueError, match="duplicate expected registry authority"):
        MultiRegistryClient(
            ["https://registry.example"],
            signer=signer,
            caller_role="seller",
            expected_registries={
                "https://registry.example": trust,
                "HTTPS://REGISTRY.EXAMPLE/": trust,
            },
        )


def test_public_identity_metadata_is_ordered_immutable_and_credential_free() -> None:
    signer = Ed25519Signer(bytes(range(32)))
    authority_a = Ed25519Signer(bytes(range(1, 33))).identity
    authority_b = Ed25519Signer(bytes(range(2, 34))).identity
    trust_a = RegistryAuthorityTrust(
        authority="registry-a",
        principals=TrustedIdentitySet(identities=(authority_a,)),
    )
    trust_b = RegistryAuthorityTrust(
        authority="registry-b",
        principals=TrustedIdentitySet(identities=(authority_b,)),
    )
    secret = "PRIVATE_AUTH_MARKER"

    client = MultiRegistryClient(
        ["HTTPS://R1.EXAMPLE/", "https://r2.example/"],
        signer=signer,
        caller_role="seller",
        expected_registries={
            "https://r1.example": trust_a,
            "https://r2.example": trust_b,
        },
        auth={"https://r1.example": secret},
    )

    assert client.publisher_identity == signer.identity
    assert client.registry_targets == (
        RegistryTargetIdentity(
            configured_url="HTTPS://R1.EXAMPLE/",
            normalized_url="https://r1.example",
            authority="registry-a",
            principals=trust_a.principals,
        ),
        RegistryTargetIdentity(
            configured_url="https://r2.example/",
            normalized_url="https://r2.example",
            authority="registry-b",
            principals=trust_b.principals,
        ),
    )
    assert isinstance(client.registry_targets, tuple)
    with pytest.raises(AttributeError):
        setattr(client.registry_targets[0], "authority", "replacement")
    assert client.registry_targets[0].authority == "registry-a"
    assert secret not in repr(client.publisher_identity)
    assert secret not in repr(client.registry_targets)


def test_exact_target_read_uses_that_registrys_auth_and_trust() -> None:
    signer = Ed25519Signer(bytes(range(32)))
    authority_a = Ed25519Signer(bytes(range(1, 33))).identity
    authority_b = Ed25519Signer(bytes(range(2, 34))).identity
    trust_a = RegistryAuthorityTrust(
        authority="registry-a",
        principals=TrustedIdentitySet(identities=(authority_a,)),
    )
    trust_b = RegistryAuthorityTrust(
        authority="registry-b",
        principals=TrustedIdentitySet(identities=(authority_b,)),
    )
    expected_listing = object()
    clients: dict[str, Any] = {}

    class RegistrySpy:
        def __init__(self, url: str, **kwargs: Any) -> None:
            self.url = url
            self.kwargs = kwargs
            self.get_calls: list[str] = []
            self.error: BaseException | None = None
            clients[url] = self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def get_listing(self, listing_id: str):
            self.get_calls.append(listing_id)
            if self.error is not None:
                raise self.error
            return expected_listing

        async def publish_listing(self, listing: Any):
            if self.error is not None:
                raise self.error
            return {"listing_id": "listing-1"}

    async def run():
        with patch(
            "core_storefront.multi_registry_client.RegistryClient",
            RegistrySpy,
        ):
            async with MultiRegistryClient(
                ["https://r1.example", "https://r2.example"],
                signer=signer,
                caller_role="seller",
                expected_registries={
                    "https://r1.example": trust_a,
                    "https://r2.example": trust_b,
                },
                auth={"https://r2.example": "fixture-token-r2"},
            ) as client:
                result = await client.get_listing_from_registry(
                    registry_url="HTTPS://R2.EXAMPLE/",
                    listing_id="listing-1",
                )
                clients["https://r2.example"].error = RegistryClientError(
                    "GET",
                    "/listings/listing-2",
                    401,
                    "authentication failed",
                )
                with pytest.raises(RegistryClientError) as read_error:
                    await client.get_listing_from_registry(
                        registry_url="https://r2.example",
                        listing_id="listing-2",
                    )
                with pytest.raises(ValueError, match="not configured"):
                    await client.get_listing_from_registry(
                        registry_url="https://unconfigured.example",
                        listing_id="listing-3",
                    )
                write_results = await client.publish_listing_per_registry(
                    payloads={"https://r2.example": object()},
                )
                return result, read_error.value, write_results

    result, read_error, write_results = asyncio.run(run())

    assert result is expected_listing
    assert clients["https://r1.example"].get_calls == []
    assert clients["https://r2.example"].get_calls == ["listing-1", "listing-2"]
    assert read_error.status_code == 401
    assert clients["https://r2.example"].kwargs["api_key"] == "fixture-token-r2"
    assert clients["https://r2.example"].kwargs["expected_registries"] == (
        trust_b.principals
    )
    assert clients["https://r2.example"].kwargs["registry_authority"] == "registry-b"
    assert write_results[0]["success"] is False
    assert write_results[0]["error_type"] == "RegistryClientError"
    assert write_results[0]["status_code"] == 401
    assert "fixture-token-r2" not in repr(write_results)
