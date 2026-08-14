from __future__ import annotations

import base64
import json
from pathlib import Path
import pytest
from hosted_settlement_client import (
    AccountOwnerAdmission,
    verify_account_owner_admission,
)

from src.hosted_real_stripe.driver import (
    _browser_outcome,
    _maintained_account_binding,
    _prepared_effect,
    _wait_until_reclaim_eligible,
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
        "reclaim_eligible_at_unix": 2_000_000_000,
    }


def test_maintained_account_binding_is_owner_signed_for_opaque_reference(
    monkeypatch,
) -> None:
    credential = base64.urlsafe_b64encode(bytes([17]) * 32).decode().rstrip("=")
    monkeypatch.setenv(
        "HOSTED_SETTLEMENT_E2E_STOREFRONT_IDENTITY_CREDENTIAL",
        credential,
    )
    monkeypatch.setattr("src.hosted_real_stripe.driver.time.time", lambda: 2_000_000_000)
    config = Path(__file__).resolve().parents[2] / "config" / "hosted-storefront.toml"

    raw = _maintained_account_binding(
        storefront_config=config,
        authority_id="hosted-test",
        account_ref="seller-account",
        provider_account_id="acct_private",
        run_identity="run-identity-001",
    )

    payload = json.loads(raw)
    assert payload["provider_account_id"] == "acct_private"
    admission = AccountOwnerAdmission.model_validate(payload["admission"])
    assert admission.account_ref == "seller-account"
    verify_account_owner_admission(
        admission,
        authority_id="hosted-test",
        now_unix=2_000_000_000,
    )


def test_prepared_effect_binds_public_lifecycle_to_exact_checkout_terms() -> None:
    expected, checkout_url = _prepared_effect(_prepared(), connected_account_id="acct_protected")
    assert expected.checkout_session_id == "cs_test_private"
    assert expected.transfer_group == "escrow-protected-001"
    assert expected.destination_account == "acct_protected"
    assert checkout_url.startswith("https://checkout.stripe.com/")


def test_refund_eligibility_wait_happens_outside_lifecycle_request(monkeypatch) -> None:
    delays: list[float] = []
    monkeypatch.setattr("src.hosted_real_stripe.driver.time.time", lambda: 100.0)
    monkeypatch.setattr("src.hosted_real_stripe.driver.time.sleep", delays.append)

    _wait_until_reclaim_eligible({"reclaim_eligible_at_unix": 120})

    assert delays == [21.0]


def test_refund_eligibility_requires_public_deadline() -> None:
    with pytest.raises(LifecycleContractError):
        _wait_until_reclaim_eligible({})


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
