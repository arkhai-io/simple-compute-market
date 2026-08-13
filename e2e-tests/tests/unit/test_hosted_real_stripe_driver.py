from __future__ import annotations

import pytest

from src.hosted_real_stripe.driver import (
    _browser_outcome,
    _prepared_effect,
    _terminal_projection,
)
from src.hosted_real_stripe.runtime import LifecycleContractError


def _prepared() -> dict[str, object]:
    return {
        "ok": True,
        "available": True,
        "discovered": True,
        "negotiated": True,
        "materialized": True,
        "accepted_mechanism": "fiat.stripe.v1",
        "condition_profile": "portable",
        "operation_ref": "market-operation-001",
        "checkout_url": "https://checkout.stripe.com/c/pay/cs_test_private",
        "amount": 1250,
        "currency": "usd",
        "destination_account_ref": "acct_protected",
        "transfer_group": "escrow-protected-001",
        "source_relation": "checkout-charge",
    }


def test_prepared_effect_binds_public_lifecycle_to_exact_checkout_terms() -> None:
    expected, checkout_url = _prepared_effect(_prepared(), connected_account_id="acct_protected")
    assert expected.checkout_session_id == "cs_test_private"
    assert expected.transfer_group == "escrow-protected-001"
    assert expected.destination_account == "acct_protected"
    assert checkout_url.startswith("https://checkout.stripe.com/")


def test_prepared_effect_rejects_incomplete_lifecycle_milestones() -> None:
    with pytest.raises(LifecycleContractError):
        _prepared_effect(
            {**_prepared(), "materialized": False},
            connected_account_id="acct_protected",
        )


def test_scenario_maps_only_to_supported_real_checkout_outcomes() -> None:
    assert _browser_outcome("collection") == "success"
    assert _browser_outcome("decline") == "decline"
    assert _browser_outcome("insufficient_funds") == "insufficient_funds"
    assert _browser_outcome("authentication") == "authentication"


def test_terminal_projection_requires_exact_public_terminal_states() -> None:
    projection = _terminal_projection(
        {
            "ok": True,
            "marketplace_state": "collected",
            "authority_state": "collected",
            "fulfillment_state": "fulfilled",
        },
        collection=True,
    )
    assert projection.fulfillment_state == "fulfilled"
    with pytest.raises(LifecycleContractError):
        _terminal_projection(
            {
                "ok": True,
                "marketplace_state": "pending",
                "authority_state": "collected",
                "fulfillment_state": "fulfilled",
            },
            collection=True,
        )
