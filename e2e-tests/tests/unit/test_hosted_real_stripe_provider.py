from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from src.hosted_real_stripe.stripe_api import (
    ExpectedEffect,
    ProviderInvariantError,
    StripeApi,
    TerminalProjection,
)


def _expected() -> ExpectedEffect:
    return ExpectedEffect(
        operation_ref="market-operation-001",
        amount=1250,
        currency="usd",
        destination_account="acct_protected",
        transfer_group="market-group-001",
        created_after=1_800_000_000,
    )


def _objects() -> dict[str, dict[str, Any]]:
    metadata = {"operation_ref": "market-operation-001"}
    return {
        "/v1/checkout/sessions": {
            "data": [
                {
                    "id": "cs_private",
                    "metadata": metadata,
                    "mode": "payment",
                    "status": "complete",
                    "payment_status": "paid",
                    "amount_total": 1250,
                    "currency": "usd",
                    "payment_intent": "pi_private",
                }
            ],
            "has_more": False,
        },
        "/v1/transfers": {
            "data": [
                {
                    "id": "tr_private",
                    "metadata": metadata,
                    "amount": 1250,
                    "currency": "usd",
                    "destination": "acct_protected",
                    "transfer_group": "market-group-001",
                    "source_transaction": "ch_private",
                }
            ],
            "has_more": False,
        },
        "/v1/payment_intents/pi_private": {"latest_charge": "ch_private"},
        "/v1/refunds": {
            "data": [
                {
                    "id": "re_private",
                    "metadata": metadata,
                    "amount": 1250,
                    "currency": "usd",
                    "status": "succeeded",
                }
            ],
            "has_more": False,
        },
    }


def _client(objects: dict[str, dict[str, Any]]) -> StripeApi:
    def transport(path: str, _params: Mapping[str, str]) -> dict[str, Any]:
        return objects[path]

    return StripeApi("sk_test_private", transport=transport)


def test_collection_requires_exact_checkout_transfer_and_source_relation() -> None:
    terminal = TerminalProjection("collected", "collected", "ready")
    evidence = _client(_objects()).inspect_collection(_expected(), terminal)
    assert evidence.checkout_count == 1
    assert evidence.transfer_count == 1
    assert evidence.destination_matches
    assert evidence.transfer_group_matches
    assert evidence.source_transaction_matches
    assert evidence.operation_metadata_matches


@pytest.mark.parametrize("path", ("/v1/checkout/sessions", "/v1/transfers"))
def test_collection_rejects_duplicate_provider_effect(path: str) -> None:
    objects = _objects()
    objects[path]["data"] = objects[path]["data"] * 2
    with pytest.raises(ProviderInvariantError):
        _client(objects).inspect_collection(
            _expected(), TerminalProjection("collected", "collected", "ready")
        )


def test_collection_rejects_wrong_destination_or_source_transaction() -> None:
    for field, value in (
        ("destination", "acct_other"),
        ("source_transaction", "ch_other"),
    ):
        objects = _objects()
        objects["/v1/transfers"]["data"][0][field] = value
        with pytest.raises(ProviderInvariantError):
            _client(objects).inspect_collection(
                _expected(), TerminalProjection("collected", "collected", "ready")
            )


def test_pretransfer_refund_requires_one_checkout_refund_and_no_transfer() -> None:
    objects = _objects()
    objects["/v1/transfers"]["data"] = []
    evidence = _client(objects).inspect_refund(
        _expected(), TerminalProjection("reclaimed", "refunded", "ready")
    )
    assert evidence.refund_count == 1
    assert evidence.transfer_count == 0


def test_pretransfer_refund_rejects_any_transfer() -> None:
    with pytest.raises(ProviderInvariantError):
        _client(_objects()).inspect_refund(
            _expected(), TerminalProjection("reclaimed", "refunded", "ready")
        )
