from __future__ import annotations

import base64
import json
from types import SimpleNamespace
from pathlib import Path
import pytest
from hosted_settlement_client import (
    AccountOwnerAdmission,
    verify_account_owner_admission,
)

from src.hosted_real_stripe.driver import (
    _browser_outcome,
    _maintained_account_binding,
    _pay_with_forwarding_paused,
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
        "accepted_funding_profile": "card.v1",
        "condition_profile": "portable",
        "parties_authoritative": True,
        "funding_authorization_bound": True,
        "funding_authorization_operation_scoped": True,
        "accepted_negotiation_id": "negotiation-001",
        "obligation_id": "obligation-001",
        "accepted_condition_hash": "condition-hash-001",
        "operation_ref": "hosted-operation-001",
        "marketplace_operation_id": "market-operation-001",
        "payer_action": {
            "kind": "payment",
            "url": "https://checkout.stripe.com/c/pay/cs_test_private",
        },
        "amount": 1250,
        "currency": "usd",
        "destination_account_ref": "seller-account",
        "transfer_group": "escrow-protected-001",
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


class _Forwarder:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def pause(self) -> None:
        self._events.append("pause")

    def resume(self) -> None:
        self._events.append("resume")


class _Browser:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def pay(
        self,
        _checkout_url: str,
        *,
        outcome: str,
        funding_profile: str = "card.v1",
    ) -> SimpleNamespace:
        self._events.append(f"pay:{funding_profile}:{outcome}")
        return SimpleNamespace(checkout_session_id="cs_test_private", outcome=outcome)


def test_missed_webhook_resumes_forwarding_after_checkout() -> None:
    events: list[str] = []

    result = _pay_with_forwarding_paused(
        _Forwarder(events),
        _Browser(events),
        "https://checkout.stripe.com/c/pay/cs_test_private",
        outcome="success",
    )

    assert result.checkout_session_id == "cs_test_private"
    assert events == ["pause", "pay:card.v1:success", "resume"]


def test_prepared_effect_binds_public_lifecycle_to_exact_profile_terms() -> None:
    expected, action_kind, action_url = _prepared_effect(
        _prepared(),
        connected_account_id="acct_protected",
        account_ref="seller-account",
        funding_profile="card.v1",
    )
    assert expected.checkout_session_id is None
    assert expected.marketplace_operation_id == "market-operation-001"
    assert expected.transfer_group == "escrow-protected-001"
    assert expected.destination_account == "acct_protected"
    assert action_kind == "payment"
    assert action_url is not None and action_url.startswith("https://checkout.stripe.com/")


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
            account_ref="seller-account",
            funding_profile="card.v1",
        )
    with pytest.raises(LifecycleContractError):
        _prepared_effect(
            {**_prepared(), "instrument_ref": "must-not-cross"},
            connected_account_id="acct_protected",
            account_ref="seller-account",
            funding_profile="card.v1",
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
            "effect_operation_ref": "collect-operation-001",
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
                "effect_operation_ref": "collect-operation-001",
            },
            collection=True,
        )
