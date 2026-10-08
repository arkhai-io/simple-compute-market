"""API-credit negotiation hooks that need no database: term decoding and the
accepted-artifact assembly.

The negotiation lifecycle against a real SQLite database is in
``tests/integration/test_sync_negotiation.py``.
"""

from __future__ import annotations

import pytest
from apicredits_storefront.domain_runtime import get_market_domain_contract
from apicredits_storefront.negotiation_runtime import _decode_terms
from market_core.schemas import ProvisionTerms
from market_identity import Ed25519Signer

_DOMAIN = get_market_domain_contract()
# Deterministic development keys for tests only; never used on any network.
_BUYER_PRINCIPAL = Ed25519Signer(bytes.fromhex("11" * 32)).identity
_SELLER_PRINCIPAL = Ed25519Signer(bytes.fromhex("22" * 32)).identity
_ESCROW = "0x" + "11" * 20


def test_decode_api_credits_message_terms_uses_domain_runtime() -> None:
    normalized = _decode_terms(
        _DOMAIN,
        ProvisionTerms(
            kind="api_credits.v1",
            version=1,
            payload={
                "quantity": "5",
                "key": {"mode": "existing", "key_id": "ak_existing"},
            },
        ),
    )

    assert normalized.decoded.quantity == 5
    assert normalized.decoded.key_mode == "existing"
    assert normalized.decoded.key_id == "ak_existing"


def test_normalize_api_credits_message_terms_rejects_foreign_terms() -> None:
    terms = ProvisionTerms(
        kind="compute.v1",
        version=1,
        payload={"duration_seconds": 60},
    )
    with pytest.raises(ValueError, match=r"api_credits\.v1"):
        _decode_terms(_DOMAIN, terms)


def test_normalize_api_credits_terms_rejects_unsupported_version() -> None:
    terms = ProvisionTerms(
        kind="api_credits.v1",
        version=2,
        payload={"quantity": 1, "key": {"mode": "new"}},
    )
    with pytest.raises(ValueError, match="version"):
        _decode_terms(_DOMAIN, terms)


def test_accepted_artifacts_stamp_the_seller_recipient(monkeypatch):
    """The accepted escrow artifacts must carry the seller's wallet as
    the escrow recipient — without it the buyer can't materialize a
    funded escrow ("must carry ... a recipient fallback"). Regression
    guard: the assembly once passed seller_wallet_address=None.
    """
    import apicredits_storefront.negotiation_runtime as sn

    captured: dict = {}

    def _fake_artifacts(**kwargs):
        captured.update(kwargs)
        return {"proposal": {}, "accepted_escrow_proposal": {}}

    monkeypatch.setattr(sn, "accepted_escrow_artifacts_from_proposal", _fake_artifacts)
    monkeypatch.setattr(sn, "_seller_wallet_address", lambda: "0xSeLLeR0000")

    sn.build_api_credit_accepted_artifacts(
        buyer_principal=_BUYER_PRINCIPAL,
        seller_principal=_SELLER_PRINCIPAL,
        proposal={"chain_name": "anvil", "escrow_address": _ESCROW},
        agreed_amount=300,
    )
    assert captured["seller_wallet_address"] == "0xSeLLeR0000"
