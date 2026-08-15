from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

import pytest

from src.hosted_real_stripe.stripe_api import (
    ExpectedEffect,
    ProviderInvariantError,
    StripeApi,
    StripeUnavailable,
    TerminalProjection,
)

OPERATION = "hosted-operation-001"
MARKET_OPERATION = "market-operation-001"
GROUP = "settlement-group-001"
SESSION = "cs_private"
EFFECT = "effect-operation-001"


def _expected(*, checkout: bool = True) -> ExpectedEffect:
    return ExpectedEffect(
        operation_ref=OPERATION,
        marketplace_operation_id=MARKET_OPERATION,
        funding_profile="card.v1",
        checkout_session_id=SESSION if checkout else None,
        amount=1250,
        currency="usd",
        destination_account="acct_protected",
        transfer_group=GROUP,
    )


def _transport(
    *,
    duplicate: bool = False,
    wrong_destination: bool = False,
    refund: bool = False,
):
    funding_metadata = {
        "operation_ref": OPERATION,
        "marketplace_operation_id": MARKET_OPERATION,
        "funding_profile": "card.v1",
        "funding_authorization_ref": "authorization-private",
    }
    charge = {
        "id": "ch_private",
        "amount_captured": 1250,
        "currency": "usd",
        "paid": True,
    }
    intent = {
        "id": "pi_private",
        "livemode": False,
        "status": "succeeded",
        "amount": 1250,
        "amount_received": 1250,
        "currency": "usd",
        "transfer_group": GROUP,
        "metadata": funding_metadata,
        "latest_charge": charge,
    }
    session = {
        "id": SESSION,
        "livemode": False,
        "mode": "payment",
        "status": "complete",
        "payment_status": "paid",
        "amount_total": 1250,
        "currency": "usd",
        "client_reference_id": OPERATION,
        "metadata": funding_metadata,
        "payment_intent": intent,
    }
    transfer = {
        "id": "tr_private",
        "livemode": False,
        "amount": 1250,
        "currency": "usd",
        "destination": "acct_wrong" if wrong_destination else "acct_protected",
        "source_transaction": "ch_private",
        "transfer_group": GROUP,
        "metadata": {"operation_ref": EFFECT, "funding_profile": "card.v1"},
    }
    refunded = {
        "id": "re_private",
        "amount": 1250,
        "currency": "usd",
        "status": "succeeded",
        "metadata": {
            "operation_ref": EFFECT,
            "funding_profile": "card.v1",
        },
    }

    def request(path: str, params: Mapping[str, str]) -> dict[str, Any]:
        if path == f"/v1/checkout/sessions/{SESSION}":
            return session
        if path == "/v1/payment_intents":
            data = [intent]
            if duplicate:
                data.append({**intent, "id": "pi_duplicate"})
            return {"data": data, "has_more": False}
        if path == "/v1/refunds":
            assert params["charge"] == charge["id"]
            return {"data": [refunded] if refund else [], "has_more": False}
        if path == "/v1/transfers":
            assert params["transfer_group"] == GROUP
            return {"data": [] if refund else [transfer], "has_more": False}
        raise AssertionError(f"unexpected retrieval: {path}")

    return request


def test_collection_retrieves_exact_checkout_and_metadata_related_transfer() -> None:
    evidence = StripeApi("rk_test_secret", transport=_transport()).inspect_collection(
        _expected(),
        TerminalProjection(
            marketplace_state="collected",
            authority_state="collected",
            fulfillment_state="fulfilled",
            effect_operation_ref=EFFECT,
        ),
    )
    assert evidence.checkout_count == 1
    assert evidence.payment_intent_count == 1
    assert evidence.charge_count == 1
    assert evidence.transfer_count == 1
    assert evidence.operation_metadata_matches is True

def test_push_transfer_funds_exact_customer_cash_balance_in_test_mode() -> None:
    expected = ExpectedEffect(
        operation_ref=OPERATION,
        marketplace_operation_id=MARKET_OPERATION,
        funding_profile="us_bank_transfer.v1",
        checkout_session_id=None,
        amount=1250,
        currency="usd",
        destination_account="acct_protected",
        transfer_group=GROUP,
    )
    metadata = {
        "operation_ref": OPERATION,
        "marketplace_operation_id": MARKET_OPERATION,
        "funding_profile": "us_bank_transfer.v1",
        "funding_authorization_ref": "authorization-private",
    }
    intent = {
        "id": "pi_private",
        "livemode": False,
        "amount": 1250,
        "currency": "usd",
        "customer": "cus_private",
        "transfer_group": GROUP,
        "metadata": metadata,
    }
    mutations: list[tuple[str, Mapping[str, str]]] = []

    def retrieve(path: str, _params: Mapping[str, str]) -> dict[str, Any]:
        assert path == "/v1/payment_intents"
        return {"data": [intent], "has_more": False}

    def mutate(path: str, params: Mapping[str, str]) -> dict[str, Any]:
        mutations.append((path, params))
        return {"livemode": False, "amount": 1250, "currency": "usd"}

    StripeApi(
        "rk_test_secret",
        transport=retrieve,
        mutation_transport=mutate,
    ).fund_test_cash_balance(expected)

    assert mutations == [
        (
            "/v1/test_helpers/customers/cus_private/fund_cash_balance",
            {"amount": "1250", "currency": "usd"},
        )
    ]


def test_refund_accepts_released_refund_shape_without_livemode() -> None:
    evidence = StripeApi(
        "rk_test_secret",
        transport=_transport(refund=True),
    ).inspect_refund(
        _expected(),
        TerminalProjection(
            marketplace_state="reclaimed",
            authority_state="refunded",
            fulfillment_state="completed",
            effect_operation_ref=EFFECT,
        ),
    )

    assert evidence.refund_count == 1
    assert evidence.transfer_count == 0
    assert evidence.operation_metadata_matches is True


def test_exact_retrieval_rejects_duplicate_funding_or_wrong_destination() -> None:
    terminal = TerminalProjection("collected", "collected", "fulfilled", EFFECT)
    with pytest.raises(ProviderInvariantError, match="multiple funding"):
        StripeApi("rk_test_secret", transport=_transport(duplicate=True)).inspect_collection(
            _expected(checkout=False), terminal
        )
    with pytest.raises(ProviderInvariantError, match="accepted terms"):
        StripeApi(
            "rk_test_secret", transport=_transport(wrong_destination=True)
        ).inspect_collection(_expected(), terminal)


def test_collection_wait_retries_transient_stripe_unavailability() -> None:
    ready = _transport()
    attempts = 0

    def transient(path: str, params: Mapping[str, str]) -> dict[str, Any]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise StripeUnavailable("transient provider retrieval")
        return ready(path, params)

    evidence = StripeApi("rk_test_secret", transport=transient).wait_for_collection(
        _expected(),
        TerminalProjection("collected", "collected", "fulfilled", EFFECT),
        timeout=1,
        poll_interval=0.001,
    )

    assert evidence.transfer_count == 1
    assert attempts > 1
