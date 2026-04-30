"""Unit tests for the pure refund-parameter derivation.

`derive_refund_params` sits between the HTTP endpoint and the on-chain
transfer. It encodes the policy decisions (required fields, default
amount, required token lookup) and returns a structured outcome that
the endpoint translates into an HTTP status + body.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from market_storefront.utils.refund import derive_refund_params


_MOCK_TOKEN = {
    "symbol": "MOCK",
    "name": "MockERC20",
    "contract_address": "0xMOCKTOKENADDR0000000000000000000000000000",
    "decimals": 18,
    "chain_id": 31337,
}


def _fake_resolver(registry: dict[str, dict]):
    def _resolve(ident: str) -> dict:
        if ident.startswith("0x"):
            for meta in registry.values():
                if meta["contract_address"].lower() == ident.lower():
                    return dict(meta)
            raise ValueError(f"unknown address: {ident}")
        if ident.upper() not in registry:
            raise ValueError(f"unknown symbol: {ident}")
        return dict(registry[ident.upper()])
    return _resolve


def _order(
    *,
    listing_id: str = "ord-1",
    status: str = "open",
    demand: dict | None = None,
    duration_hours: int = 3,
    escrow_uid: str | None = "0xescrow-1",
) -> dict:
    return {
        "listing_id": listing_id,
        "status": status,
        "demand_resource": json.dumps(demand or {"token": _MOCK_TOKEN, "amount": 1_000_000_000_000_000_000}),
        "duration_hours": duration_hours,
        "escrow_uid": escrow_uid,
    }


@pytest.fixture
def resolver():
    return _fake_resolver({"MOCK": _MOCK_TOKEN})


def test_happy_path_uses_order_defaults(resolver):
    order = _order(duration_hours=3)
    payload = {"listing_id": "ord-1", "buyer_address": "0x" + "a" * 40}
    tag, params = derive_refund_params(order=order, payload=payload, resolve_token=resolver)

    assert tag == "ok"
    assert params["listing_id"] == "ord-1"
    assert params["buyer_address"] == "0x" + "a" * 40
    assert params["token_address"] == _MOCK_TOKEN["contract_address"]
    assert params["decimals"] == 18
    # Demand 1e18 (1 MOCK raw) × duration 3 = 3e18 raw
    assert params["amount_raw"] == 3 * 10**18
    assert params["escrow_uid"] == "0xescrow-1"


def test_order_not_found_returns_404(resolver):
    payload = {"listing_id": "nope", "buyer_address": "0x" + "a" * 40}
    tag, status, body = derive_refund_params(order=None, payload=payload, resolve_token=resolver)
    assert tag == "error"
    assert status == 404
    assert "not found" in body["error"].lower()


def test_already_refunded_returns_409(resolver):
    order = _order(status="refunded")
    payload = {"listing_id": "ord-1", "buyer_address": "0x" + "a" * 40}
    tag, status, body = derive_refund_params(order=order, payload=payload, resolve_token=resolver)
    assert tag == "error"
    assert status == 409
    assert body["status"] == "refunded"


def test_missing_buyer_address_is_value_error(resolver):
    order = _order()
    with pytest.raises(ValueError, match="buyer_address"):
        derive_refund_params(order=order, payload={"listing_id": "ord-1"}, resolve_token=resolver)


def test_malformed_buyer_address_is_value_error(resolver):
    order = _order()
    with pytest.raises(ValueError, match="0x-prefixed"):
        derive_refund_params(
            order=order,
            payload={"listing_id": "ord-1", "buyer_address": "not-an-address"},
            resolve_token=resolver,
        )


def test_missing_order_id_is_value_error(resolver):
    with pytest.raises(ValueError, match="listing_id"):
        derive_refund_params(order=None, payload={"buyer_address": "0x" + "a" * 40}, resolve_token=resolver)


def test_explicit_amount_overrides_order_default(resolver):
    order = _order(duration_hours=99)  # big duration that would otherwise inflate default
    payload = {
        "listing_id": "ord-1",
        "buyer_address": "0x" + "b" * 40,
        "amount": "2.5",  # human units, 18 decimals → 2.5e18 raw
    }
    tag, params = derive_refund_params(order=order, payload=payload, resolve_token=resolver)
    assert tag == "ok"
    assert params["amount_raw"] == int(Decimal("2.5") * 10**18)


def test_explicit_token_symbol_is_resolved(resolver):
    # Order demand has a fully-spelled token dict; operator overrides with symbol lookup
    order = _order(demand={"token": dict(_MOCK_TOKEN), "amount": 500})
    payload = {
        "listing_id": "ord-1",
        "buyer_address": "0x" + "c" * 40,
        "token": "MOCK",
        "amount": "0.001",
    }
    tag, params = derive_refund_params(order=order, payload=payload, resolve_token=resolver)
    assert tag == "ok"
    assert params["token_address"] == _MOCK_TOKEN["contract_address"]
    assert params["amount_raw"] == 10**15  # 0.001 * 10^18


def test_amount_with_too_many_decimals_is_value_error(resolver):
    order = _order()
    payload = {
        "listing_id": "ord-1",
        "buyer_address": "0x" + "d" * 40,
        "amount": "0.0000000000000000001",  # 19 decimals > 18 → not representable
    }
    with pytest.raises(ValueError, match="more decimals"):
        derive_refund_params(order=order, payload=payload, resolve_token=resolver)


def test_zero_amount_returns_400(resolver):
    order = _order(demand={"token": _MOCK_TOKEN, "amount": 0})
    payload = {"listing_id": "ord-1", "buyer_address": "0x" + "e" * 40}
    tag, status, body = derive_refund_params(order=order, payload=payload, resolve_token=resolver)
    assert tag == "error"
    assert status == 400
    assert "positive" in body["error"]


def test_demand_with_string_token_symbol_resolves(resolver):
    order = _order(demand={"token": "MOCK", "amount": 100})
    payload = {"listing_id": "ord-1", "buyer_address": "0x" + "f" * 40}
    tag, params = derive_refund_params(order=order, payload=payload, resolve_token=resolver)
    assert tag == "ok"
    assert params["token_address"] == _MOCK_TOKEN["contract_address"]
    # 100 raw × duration 3 = 300 raw
    assert params["amount_raw"] == 300


def test_demand_with_no_token_and_no_override_returns_400(resolver):
    order = _order(demand={"amount": 100})
    payload = {"listing_id": "ord-1", "buyer_address": "0x" + "a" * 40}
    tag, status, body = derive_refund_params(order=order, payload=payload, resolve_token=resolver)
    assert tag == "error"
    assert status == 400
    assert "token" in body["error"].lower()
