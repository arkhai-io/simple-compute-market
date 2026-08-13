from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

import pytest

from src.hosted_real_stripe.stripe_api import (
    ExpectedEffect,
    ProviderInvariantError,
    StripeApi,
    TerminalProjection,
)

ESCROW = "escrow-protected-001"
SESSION = "cs_private"


def _ref(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x00".join(parts).encode()).hexdigest()
    return f"{prefix}_{digest[:40]}"


def _expected() -> ExpectedEffect:
    return ExpectedEffect(
        operation_ref="market-operation-001",
        checkout_session_id=SESSION,
        amount=1250,
        currency="usd",
        destination_account="acct_protected",
        transfer_group=ESCROW,
    )


def _transport(*, duplicate: bool = False, wrong_destination: bool = False):
    checkout_metadata = {"escrow_ref": ESCROW, "operation_ref": _ref("checkout", ESCROW)}
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
        "amount_received": 1250,
        "currency": "usd",
        "metadata": checkout_metadata,
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
        "client_reference_id": ESCROW,
        "metadata": checkout_metadata,
        "payment_intent": intent,
    }
    transfer = {
        "id": "tr_private",
        "livemode": False,
        "amount": 1250,
        "currency": "usd",
        "destination": "acct_wrong" if wrong_destination else "acct_protected",
        "source_transaction": "ch_private",
        "transfer_group": ESCROW,
        "metadata": {"operation_ref": _ref("collect", ESCROW)},
    }

    def request(path: str, params: Mapping[str, str]) -> dict[str, Any]:
        if path == f"/v1/checkout/sessions/{SESSION}":
            return session
        if path == "/v1/checkout/sessions/search":
            assert params["query"] == f"metadata['operation_ref']:'{_ref('checkout', ESCROW)}'"
            data = [session]
            if duplicate:
                data.append({**session, "id": "cs_duplicate"})
            return {"data": data, "has_more": False}
        if path == "/v1/transfers":
            assert params["transfer_group"] == ESCROW
            return {"data": [transfer], "has_more": False}
        raise AssertionError(f"unexpected retrieval: {path}")

    return request


def test_collection_retrieves_exact_checkout_and_metadata_related_transfer() -> None:
    evidence = StripeApi("rk_test_secret", transport=_transport()).inspect_collection(
        _expected(),
        TerminalProjection(
            marketplace_state="collected",
            authority_state="collected",
            fulfillment_state="fulfilled",
        ),
    )
    assert evidence.checkout_count == 1
    assert evidence.payment_intent_count == 1
    assert evidence.charge_count == 1
    assert evidence.transfer_count == 1
    assert evidence.operation_metadata_matches is True


def test_exact_retrieval_rejects_duplicate_checkout_or_wrong_destination() -> None:
    terminal = TerminalProjection("collected", "collected", "fulfilled")
    with pytest.raises(ProviderInvariantError, match="multiple Checkout"):
        StripeApi("rk_test_secret", transport=_transport(duplicate=True)).inspect_collection(
            _expected(), terminal
        )
    with pytest.raises(ProviderInvariantError, match="accepted terms"):
        StripeApi(
            "rk_test_secret", transport=_transport(wrong_destination=True)
        ).inspect_collection(_expected(), terminal)
