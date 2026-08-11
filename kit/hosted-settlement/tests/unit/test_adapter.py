from __future__ import annotations

from typing import Any

import pytest
from hosted_settlement_client import (
    BuyerAction,
    ConditionState,
    EscrowResult,
    FinancialState,
    OperationReceipt,
)
from market_hosted_settlement import HostedConditionalEscrowClient


class FakeClient:
    def __init__(self) -> None:
        self.materialize_request: Any = None

    async def materialize(self, request: Any) -> EscrowResult:
        self.materialize_request = request
        return EscrowResult(
            escrow_ref="escrow-public",
            financial_state=FinancialState.AWAITING_PAYMENT,
            condition_state=ConditionState.PENDING,
            action=BuyerAction(
                url="https://checkout.example/secret-session",
                expires_at_unix=2_000_000_100,
            ),
            condition_anchor="0x" + "66" * 32,
            expiration_unix=2_000_003_600,
        )

    async def get_status(self, escrow_ref: str, *, request_id: str) -> EscrowResult:
        return await self.materialize(None)

    async def collect(self, escrow_ref: str, request: Any) -> OperationReceipt:
        return OperationReceipt(
            escrow_ref=escrow_ref,
            operation_ref=request.request_id,
            financial_state=FinancialState.COLLECTED,
            receipt="sha256:" + "77" * 32,
        )


def _obligation(**updates: Any) -> dict[str, Any]:
    value = {
        "payer": "buyer",
        "claimant": "seller",
        "amount": 1200,
        "asset": "usd",
        "expiration_unix": 2_000_003_600,
        "conditions": [],
        "mechanism": "fiat.stripe.v1",
        "params": {
            "account_ref": "account-1",
            "payer_address": "0x" + "11" * 20,
            "claimant_address": "0x" + "22" * 20,
            "funds_flow": "separate_charges_transfers",
            "payment_method_types": ["card"],
            "condition": {
                "protocol": "arkhai.condition.v1",
                "condition_id": "condition-1",
                "evaluator": {
                    "kind": "builtin.v1",
                    "version": "trivial.v1",
                    "params": {"kind": "trivial"},
                },
                "demand": {"encoding": "application/jcs+json", "value": True},
            },
        },
    }
    value.update(updates)
    return value


@pytest.mark.asyncio
async def test_adapter_maps_materialization_without_persisting_checkout_url() -> None:
    client = FakeClient()
    adapter = HostedConditionalEscrowClient(client)  # type: ignore[arg-type]
    result = await adapter.materialize(
        _obligation(), operation_ref="arkhai:settlement:obligation-1:materialize"
    )
    assert result.status == "requires_action"
    assert result.mechanism_ref == "escrow-public"
    assert result.buyer_action == {"kind": "redirect", "expires_at_unix": 2_000_000_100}
    assert "checkout.example" not in str(result.model_dump())
    assert client.materialize_request.amount == 1200
    assert client.materialize_request.currency == "usd"


@pytest.mark.parametrize(
    "updates, message",
    [
        ({"amount": 0}, "positive integer"),
        ({"asset": "USD"}, "lowercase ISO 4217"),
        ({"payer": "seller"}, "buyer-funded"),
        ({"mechanism": "alkahest.v1"}, "requires mechanism"),
    ],
)
def test_adapter_rejects_invalid_hosted_obligation(
    updates: dict[str, Any], message: str
) -> None:
    adapter = HostedConditionalEscrowClient(FakeClient())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=message):
        import asyncio

        asyncio.run(
            adapter.materialize(_obligation(**updates), operation_ref="operation-1")
        )
