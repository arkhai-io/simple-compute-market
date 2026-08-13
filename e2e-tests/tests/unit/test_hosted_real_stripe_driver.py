from __future__ import annotations

from typing import Any

from src.hosted_real_stripe.driver import _drive_lifecycle
from src.hosted_real_stripe.evidence import CollectionEvidence, RefundEvidence


class _Lifecycle:
    def __init__(self) -> None:
        self.actions: list[tuple[str, dict[str, object]]] = []

    def request(self, action: str, **fields: object) -> dict[str, Any]:
        self.actions.append((action, fields))
        if action in {"prepare_collection", "prepare_refund"}:
            suffix = "collection" if action == "prepare_collection" else "refund"
            return {
                "ok": True,
                "available": True,
                "discovered": True,
                "negotiated": True,
                "materialized": True,
                "accepted_mechanism": "fiat.stripe.v1",
                "condition_profile": "portable",
                "operation_ref": f"market-{suffix}",
                "checkout_url": f"https://checkout.stripe.com/c/pay/{suffix}",
                "amount": 1250,
                "currency": "usd",
                "transfer_group": f"group-{suffix}",
            }
        if action == "wait_authoritative_collection":
            return {
                "ok": True,
                "marketplace_state": "collected",
                "authority_state": "collected",
                "fulfillment_state": "ready",
            }
        if action == "wait_authoritative_refund":
            return {
                "ok": True,
                "marketplace_state": "reclaimed",
                "authority_state": "refunded",
                "fulfillment_state": "ready",
            }
        return {"ok": True}


class _Browser:
    def __init__(self) -> None:
        self.completed = 0

    def complete(self, checkout_url: str) -> None:
        assert checkout_url.startswith("https://checkout.stripe.com/")
        self.completed += 1


class _Stripe:
    def __init__(self) -> None:
        self.effects: list[object] = []

    def inspect_collection(self, expected, terminal):
        self.effects.append(expected)
        assert expected.destination_account == "acct_protected"
        assert terminal.authority_state == "collected"
        return CollectionEvidence(
            operation_ref=expected.operation_ref,
            checkout_count=1,
            transfer_count=1,
            amount=expected.amount,
            currency=expected.currency,
            destination_matches=True,
            transfer_group_matches=True,
            source_transaction_matches=True,
            operation_metadata_matches=True,
            marketplace_state=terminal.marketplace_state,
            authority_state=terminal.authority_state,
            fulfillment_state=terminal.fulfillment_state,
        )

    def inspect_refund(self, expected, terminal):
        self.effects.append(expected)
        assert expected.destination_account == "acct_protected"
        assert terminal.authority_state == "refunded"
        return RefundEvidence(
            outcome="passed",
            operation_ref=expected.operation_ref,
            checkout_count=1,
            refund_count=1,
            transfer_count=0,
            amount=expected.amount,
            currency=expected.currency,
            operation_metadata_matches=True,
            marketplace_state=terminal.marketplace_state,
            authority_state=terminal.authority_state,
        )


def test_driver_runs_marketplace_checkout_fulfillment_collection_and_refund() -> None:
    lifecycle = _Lifecycle()
    browser = _Browser()
    stripe = _Stripe()
    collection, refund = _drive_lifecycle(
        lifecycle=lifecycle,
        stripe=stripe,
        browser=browser,
        connected_account_id="acct_protected",
        created_after=1_800_000_000,
        attempt_refund=True,
    )
    assert browser.completed == 2
    assert collection.operation_ref == "market-collection"
    assert refund.operation_ref == "market-refund"
    assert [action for action, _fields in lifecycle.actions] == [
        "prepare_collection",
        "wait_authoritative_funding",
        "complete_portable_vm_fulfillment",
        "wait_authoritative_collection",
        "prepare_refund",
        "wait_authoritative_funding",
        "request_eligible_pretransfer_refund",
        "wait_authoritative_refund",
    ]
