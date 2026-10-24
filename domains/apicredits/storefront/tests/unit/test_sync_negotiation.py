"""API-credit negotiation hooks that need no database: term decoding and the
accepted-artifact assembly.

The negotiation lifecycle against a real SQLite database is in
``tests/integration/test_sync_negotiation.py``.
"""

from __future__ import annotations

import apicredits_storefront.settlement_stages as settlement_stages
import pytest
from apicredits_storefront.domain_runtime import get_market_domain_contract
from arkhai_api_selling.negotiation import decode_terms as _decode_terms
from market_alkahest.proposals import ReleaseConditionError
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


def test_accepted_artifacts_settle_under_the_listings_condition(monkeypatch):
    """The accepted escrow is materialized against the listing, whose
    authorized release condition the kit materializes it under."""
    captured: dict = {}

    def _fake_artifacts(**kwargs):
        captured.update(kwargs)
        return {"proposal": {}}

    monkeypatch.setattr(
        settlement_stages, "accepted_escrow_artifacts_from_proposal", _fake_artifacts
    )

    condition = {
        "chain_name": "anvil",
        "arbiter": "0x" + "44" * 20,
        "demand_data": {"recipient": "0x" + "55" * 20},
    }

    settlement_stages.build_api_credit_accepted_artifacts(
        buyer_principal=_BUYER_PRINCIPAL,
        seller_principal=_SELLER_PRINCIPAL,
        proposal={
            "chain_name": "anvil",
            "escrow_address": _ESCROW,
            "expiration_unix": 1_800_000_000,
        },
        agreed_amount=300,
        listing={"demands": [condition]},
    )
    assert captured["listing"] == {"demands": [condition]}
    assert captured["proposal"]["escrow_address"] == _ESCROW


def test_accepted_artifacts_refuse_a_listing_authorizing_no_condition():
    with pytest.raises(ReleaseConditionError, match="release_condition_not_advertised"):
        settlement_stages.build_api_credit_accepted_artifacts(
            buyer_principal=_BUYER_PRINCIPAL,
            seller_principal=_SELLER_PRINCIPAL,
            proposal={
                "chain_name": "anvil",
                "escrow_address": _ESCROW,
                "expiration_unix": 1_800_000_000,
            },
            agreed_amount=300,
            listing={"demands": []},
        )
