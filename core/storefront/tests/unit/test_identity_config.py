from __future__ import annotations

import pytest
from market_identity import Ed25519Signer

from core_storefront.identity_config import IdentityConfig, resolve_storefront_signer


def test_secret_bound_signer_must_own_public_principal() -> None:
    expected = Ed25519Signer(bytes(range(32)))
    other_credential = bytes(range(1, 33))
    config = IdentityConfig(
        scheme=expected.identity.scheme,
        identifier=expected.identity.identifier,
    )

    signer = resolve_storefront_signer(config, bytes(range(32)))
    assert signer.identity == expected.identity
    assert "credential" not in repr(config).lower()

    with pytest.raises(ValueError, match="does not match"):
        resolve_storefront_signer(config, other_credential)
