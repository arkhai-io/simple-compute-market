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
    _SAVED_INSTRUMENT_PROFILES,
    _browser_outcome,
    _lifecycle_environment,
    _payer_return_address,
    _validate_payer_fixture,
    _maintained_account_binding,
    _pay_with_forwarding_paused,
    _prepared_effect,
    _wait_until_reclaim_eligible,
    _terminal_projection,
)
from src.hosted_real_stripe.runtime import LifecycleContractError, ProcessUnavailable


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


def _payer_fixture(**updates: object) -> dict[str, object]:
    fixture: dict[str, object] = {
        "ok": True,
        "available": True,
        "selected_owner_bound": True,
        "historical_owner_recoverable": True,
        "opaque_binding_persisted": True,
        "action_persisted": False,
        "saved_instrument_ready": False,
        "setup_action": None,
        "setup_verification_pending": False,
    }
    fixture.update(updates)
    return fixture


def test_a_setup_awaiting_payer_verification_needs_no_browser_action() -> None:
    """No action is the point, not a missing prerequisite.

    Every saved-instrument setup used to have to hand back an https action, so
    a setup the payer can answer themselves read as one the run could not
    start.
    """

    action = _validate_payer_fixture(
        _payer_fixture(setup_verification_pending=True),
        interaction="saved_instrument",
    )

    assert action is None


def test_a_setup_pending_verification_may_not_also_hand_back_a_browser_action() -> None:
    with pytest.raises(LifecycleContractError):
        _validate_payer_fixture(
            _payer_fixture(
                setup_verification_pending=True,
                setup_action={
                    "kind": "setup",
                    "url": "https://transient.example/action",
                    "expires_at_unix": 4_000_000_000,
                },
            ),
            interaction="saved_instrument",
        )


def test_a_release_without_direct_setup_still_requires_its_browser_action() -> None:
    """The interactive path is untouched for a release that declares nothing."""

    action = _validate_payer_fixture(
        _payer_fixture(
            setup_action={
                "kind": "setup",
                "url": "https://transient.example/action",
                "expires_at_unix": 4_000_000_000,
            },
        ),
        interaction="saved_instrument",
    )

    assert action is not None
    assert action["url"] == "https://transient.example/action"

    with pytest.raises(ProcessUnavailable):
        _validate_payer_fixture(_payer_fixture(), interaction="saved_instrument")


def test_a_push_transfer_profile_holds_no_saved_instrument() -> None:
    assert "us_bank_transfer.v1" not in _SAVED_INSTRUMENT_PROFILES
    assert _SAVED_INSTRUMENT_PROFILES == frozenset({"card.v1", "us_ach_debit.v1"})


class _AddressStripe:
    def __init__(self) -> None:
        self.asked = 0

    def platform_return_address(self) -> str:
        self.asked += 1
        return "account@example.test"


@pytest.mark.parametrize("scenario", ["reclaim", "worker_restart"])
def test_a_push_funded_return_lane_is_given_an_address(scenario: str) -> None:
    """Both lanes that reverse a funded obligation need somewhere to address
    the payer's return, because the authority refuses to mail nowhere."""

    stripe = _AddressStripe()

    address = _payer_return_address(
        stripe,  # type: ignore[arg-type]
        funding_profile="us_bank_transfer.v1",
        scenario=scenario,  # type: ignore[arg-type]
    )

    assert address == "account@example.test"
    assert stripe.asked == 1


@pytest.mark.parametrize(
    ("funding_profile", "scenario"),
    [
        ("card.v1", "reclaim"),
        ("us_ach_debit.v1", "reclaim"),
        ("us_bank_transfer.v1", "collection"),
    ],
)
def test_no_address_is_fetched_where_none_is_needed(
    funding_profile: str, scenario: str
) -> None:
    """A pull-funded profile is credited back to the instrument that funded it,
    and a lane that never reverses has nothing to address at all."""

    stripe = _AddressStripe()

    address = _payer_return_address(
        stripe,  # type: ignore[arg-type]
        funding_profile=funding_profile,  # type: ignore[arg-type]
        scenario=scenario,  # type: ignore[arg-type]
    )

    assert address == ""
    assert stripe.asked == 0


def test_the_lifecycle_environment_omits_an_address_it_was_not_given(
    tmp_path: Path,
) -> None:
    args = SimpleNamespace(
        marketplace_factory="factory",
        storefront_url="https://storefront.example",
        registry_url="https://registry.example",
        provisioning_url="https://provisioning.example",
        authority_url="https://authority.example",
        account_ref="account-1",
        funding_profile="card.v1",
        interaction="interactive",
        scenario="collection",
        run_identity="run-1",
        lifecycle_timeout=180,
    )

    without = _lifecycle_environment(
        args,  # type: ignore[arg-type]
        buyer_config=tmp_path / "buyer.toml",
        marketplace_config=tmp_path / "marketplace.toml",
        manifest_digest="sha256:" + "0" * 64,
    )
    with_address = _lifecycle_environment(
        args,  # type: ignore[arg-type]
        buyer_config=tmp_path / "buyer.toml",
        marketplace_config=tmp_path / "marketplace.toml",
        manifest_digest="sha256:" + "0" * 64,
        return_address="account@example.test",
    )

    assert "HOSTED_SETTLEMENT_E2E_RETURN_ADDRESS" not in without
    assert with_address["HOSTED_SETTLEMENT_E2E_RETURN_ADDRESS"] == "account@example.test"
