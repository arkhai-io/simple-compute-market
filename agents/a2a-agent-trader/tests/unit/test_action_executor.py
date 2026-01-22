"""Unit tests for action executor helpers."""

import json

import pytest

from app.schema.pydantic_models import (
    ComputeResource,
    ERC20TokenMetadata,
    GPUModel,
    Region,
    TokenResource,
)
from app.utils import action_executor


USDT_METADATA = ERC20TokenMetadata(
    symbol="USDT",
    contract_address="0xdac17f958d2ee523a2206206994597c13d831ec7",
    decimals=6,
)


def _compute_resource() -> ComputeResource:
    return ComputeResource(
        gpu_model=GPUModel.H200,
        quantity=1,
        sla=99.0,
        region=Region.CALIFORNIA_US,
    )


def _token_rate(amount: int) -> TokenResource:
    return TokenResource(token=USDT_METADATA, amount=amount)


def test_encode_compute_lease_uses_rate_times_duration_token_instance():
    """Test encoding compute lease with TokenResource instance."""
    rate = 1_500_000
    duration_hours = 3
    lease_bytes = action_executor.encode_compute_lease(
        compute_resource=_compute_resource(),
        token_resource=_token_rate(rate),
        duration_hours=duration_hours,
    )
    payload = json.loads(lease_bytes.decode("utf-8"))

    assert payload["duration_hours"] == duration_hours
    assert payload["total_price_int"] == rate * duration_hours
    assert payload["price_per_hour_decimal"] == pytest.approx(rate / 10**USDT_METADATA.decimals)
    assert payload["total_price_decimal"] == pytest.approx((rate * duration_hours) / 10**USDT_METADATA.decimals)


def test_encode_compute_lease_uses_rate_times_duration_token_dict():
    """Test encoding compute lease with token resource as dict."""
    rate = 2_000_000
    duration_hours = 2
    token_dict = {
        "token": {
            "symbol": USDT_METADATA.symbol,
            "contract_address": USDT_METADATA.contract_address,
            "decimals": USDT_METADATA.decimals,
        },
        "amount": rate,
    }
    lease_bytes = action_executor.encode_compute_lease(
        compute_resource=_compute_resource().model_dump(mode="json"),
        token_resource=token_dict,
        duration_hours=duration_hours,
    )
    payload = json.loads(lease_bytes.decode("utf-8"))

    assert payload["total_price_int"] == rate * duration_hours
    assert payload["price_per_hour_decimal"] == pytest.approx(rate / 10**USDT_METADATA.decimals)
    assert payload["total_price_decimal"] == pytest.approx((rate * duration_hours) / 10**USDT_METADATA.decimals)


class _FakeEscrow:
    def __init__(self, records: dict) -> None:
        self._records = records

    async def create(self, price_data, arbiter_data, expiration):
        self._records["price_data"] = price_data
        self._records["arbiter_data"] = arbiter_data
        self._records["expiration"] = expiration
        return {"log": {"uid": "escrow123"}}


class _FakeClient:
    def __init__(self, records: dict) -> None:
        class _Util:
            async def approve(self, *_args, **_kwargs):
                return "approved"

        class _NonTierable:
            def __init__(self, recs: dict) -> None:
                self._recs = recs

            async def create(self, price_data, arbiter_data, expiration):
                return await _FakeEscrow(self._recs).create(price_data, arbiter_data, expiration)

        class _Escrow:
            def __init__(self, recs: dict) -> None:
                self.non_tierable = _NonTierable(recs)

        class _ERC20:
            def __init__(self, recs: dict) -> None:
                self.escrow = _Escrow(recs)
                self.util = _Util()

        self.erc20 = _ERC20(records)


@pytest.mark.asyncio
async def test_buy_compute_with_erc20_approves_total_and_creates_total(monkeypatch):
    """Test buying compute with ERC20 approves total payment and creates escrow with total price."""
    records: dict = {}
    rate = 1_250_000
    duration_hours = 4

    async def fake_approve_token_escrow(payment, *, alkahest_client):
        records["approved_payment"] = payment
        return "approved"

    monkeypatch.setattr(action_executor, "approve_token_escrow", fake_approve_token_escrow)

    await action_executor.buy_compute_with_erc20(
        compute_resource=_compute_resource(),
        token_resource=_token_rate(rate),
        duration_hours=duration_hours,
        oracle_address="0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
        client=_FakeClient(records),
    )

    assert records["approved_payment"].amount == rate * duration_hours
    assert records["price_data"]["value"] == rate * duration_hours


@pytest.mark.asyncio
async def test_accept_offer_passes_duration_and_hourly_rate(monkeypatch):
    """Test accept_offer passes duration_hours and hourly rate to buy_compute_with_erc20."""
    records: dict = {}
    rate = 1_000_000
    duration_hours = 5
    order_dict = {
        "order_id": "order-123",
        "order_maker": "seller",
        "offer_resource": _compute_resource().model_dump(mode="json"),
        "demand_resource": _token_rate(rate).model_dump(mode="json"),
        "duration_hours": duration_hours,
    }

    async def fake_buy_compute_with_erc20(
        compute_resource,
        token_resource,
        duration_hours,
        oracle_address,
        client,
    ):
        records["token_resource"] = token_resource
        records["duration_hours"] = duration_hours
        return {"log": {"uid": "escrow123"}}

    monkeypatch.setattr(action_executor, "buy_compute_with_erc20", fake_buy_compute_with_erc20)

    await action_executor.accept_offer(
        alkahest_client=_FakeClient(records),
        ctx=None,
        parameters={"order": order_dict},
    )

    assert records["duration_hours"] == duration_hours
    token_payload = records["token_resource"]
    if isinstance(token_payload, dict):
        token_payload = TokenResource.model_validate(token_payload)
    assert token_payload.amount == rate
