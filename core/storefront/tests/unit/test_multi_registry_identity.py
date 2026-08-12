from __future__ import annotations

import pytest
from market_identity import Ed25519Signer, TrustedIdentitySet

from core_storefront.multi_registry_client import (
    MultiRegistryClient,
    RegistryAuthorityTrust,
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
