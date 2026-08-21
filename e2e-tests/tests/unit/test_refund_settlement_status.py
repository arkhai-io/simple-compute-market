"""A refund still settling is this run arriving early, not a broken authority."""

from __future__ import annotations

from typing import Any

import pytest

from src.hosted_real_stripe.stripe_api import (
    ExpectedEffect,
    ProviderInvariantError,
    ProviderNotConverged,
    StripeApi,
    TerminalProjection,
)

_EXPECTED = ExpectedEffect(
    operation_ref="op-1",
    marketplace_operation_id="mkt-op-1",
    funding_profile="us_ach_debit.v1",
    checkout_session_id=None,
    amount=2000,
    currency="usd",
    destination_account="acct-destination",
    transfer_group="group-1",
)
_TERMINAL = TerminalProjection(
    marketplace_state="reclaimed",
    authority_state="refunded",
    fulfillment_state="unfulfilled",
    effect_operation_ref="op-1",
)
_METADATA = {
    "operation_ref": "op-1",
    "marketplace_operation_id": "mkt-op-1",
    "funding_profile": "us_ach_debit.v1",
    "funding_authorization_ref": "auth-1",
}


def _api(monkeypatch: pytest.MonkeyPatch, refund_status: str) -> StripeApi:
    """A real StripeApi with only its transport-backed lookups stood in for."""

    api = StripeApi.__new__(StripeApi)
    payment_intent: dict[str, Any] = {
        "id": "pi-1",
        "livemode": False,
        "amount_received": 2000,
        "currency": "usd",
        "metadata": dict(_METADATA),
    }
    refund: dict[str, Any] = {
        "id": "re-1",
        "amount": 2000,
        "currency": "usd",
        "status": refund_status,
        "metadata": dict(_METADATA),
    }
    monkeypatch.setattr(
        StripeApi, "_exact_funding", lambda _self, _e: (None, payment_intent)
    )
    monkeypatch.setattr(StripeApi, "_charge", lambda _self, _pi: {"id": "ch-1"})
    monkeypatch.setattr(StripeApi, "_list_all", lambda _self, _p, _q: [refund])
    monkeypatch.setattr(StripeApi, "_related_transfers", lambda _self, _e, _r: [])
    return api


@pytest.mark.parametrize("status", ["pending", "requires_action"])
def test_settling_refund_is_polled_again(
    monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    """ProviderNotConverged is the only class the surrounding wait retries, so
    an ACH refund mid-settlement must raise that and not an invariant error."""

    api = _api(monkeypatch, status)

    with pytest.raises(ProviderNotConverged):
        api.inspect_refund(_EXPECTED, _TERMINAL)


@pytest.mark.parametrize("status", ["failed", "canceled"])
def test_finished_unsuccessful_refund_is_an_invariant(
    monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    api = _api(monkeypatch, status)

    with pytest.raises(ProviderInvariantError) as raised:
        api.inspect_refund(_EXPECTED, _TERMINAL)

    assert status in str(raised.value)


def test_succeeded_refund_yields_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _api(monkeypatch, "succeeded")

    evidence = api.inspect_refund(_EXPECTED, _TERMINAL)

    assert (evidence.refund_count, evidence.transfer_count) == (1, 0)
    assert evidence.amount == 2000


def test_mismatched_amount_names_the_field(monkeypatch: pytest.MonkeyPatch) -> None:
    """The invariant must say which of its clauses differed."""

    api = _api(monkeypatch, "succeeded")
    monkeypatch.setattr(
        StripeApi,
        "_exact_funding",
        lambda _self, _e: (
            None,
            {
                "id": "pi-1",
                "livemode": False,
                "amount_received": 1500,
                "currency": "usd",
                "metadata": dict(_METADATA),
            },
        ),
    )

    with pytest.raises(ProviderInvariantError) as raised:
        api.inspect_refund(_EXPECTED, _TERMINAL)

    assert "funding received 1500" in str(raised.value)
