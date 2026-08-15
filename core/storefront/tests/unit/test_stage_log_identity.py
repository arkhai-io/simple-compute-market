from __future__ import annotations

import pytest
from market_identity import Ed25519Signer

from core_storefront.stage_log import _public_value


def test_run_log_serializes_only_public_principal() -> None:
    signer = Ed25519Signer(bytes(range(32)))

    assert _public_value({"buyer_principal": signer.identity}) == {
        "buyer_principal": signer.identity.model_dump(mode="json")
    }
    with pytest.raises(ValueError, match="signers cannot"):
        _public_value({"seller": signer})
    with pytest.raises(ValueError, match="binary signing material"):
        _public_value({"opaque": bytes(range(32))})


@pytest.mark.parametrize(
    "secret_key",
    [
        "credential",
        "Identity-Credential",
        "private_key",
        "buyerPrivateKey",
        "seller_private_key",
        "seed_phrase",
        "signing-key",
    ],
)
def test_run_log_rejects_nested_secret_material(secret_key: str) -> None:
    with pytest.raises(ValueError, match="private signing material"):
        _public_value({"operation": {"nested": {secret_key: "must-not-leak"}}})
