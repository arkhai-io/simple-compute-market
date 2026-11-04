"""Shared builders for valid payment terms in kit tests."""

from __future__ import annotations

import json
from typing import Any

from market_core.schemas import Agreement, SettlementOption, derive_settlement_option_id
from market_identity import Ed25519Signer

from market_arkhai_payments import ARKHAI_PAYMENTS_MECHANISM, ArkhaiPaymentsConfig
from market_arkhai_payments.fixtures import dispute_lifecycle

BUYER = "11111111-1111-4111-8111-111111111111"
PAYEE = "22222222-2222-4222-8222-222222222222"
DISPUTE = "33333333-3333-4333-8333-333333333333"
OTHER = "44444444-4444-4444-8444-444444444444"
SERVICE = Ed25519Signer(b"\x07" * 32)
IMPOSTOR = Ed25519Signer(b"\x08" * 32)


def option(
    *, deposit: bool = False, payee: str = PAYEE, window: str = "P7D", dispute: str = DISPUTE
) -> SettlementOption:
    params = {"payee_account": payee, "window": window, "deposit_agreement": deposit}
    return SettlementOption(
        option_id=derive_settlement_option_id(
            price={"asset": "USD/2", "rates": []},
            settlement={"schema": ARKHAI_PAYMENTS_MECHANISM, **(params or {})},
            lifecycle=dispute_lifecycle(dispute),
        ),
        price={"asset": "USD/2", "rates": []},
        settlement={"schema": ARKHAI_PAYMENTS_MECHANISM, **(params or {})},
        lifecycle=dispute_lifecycle(dispute),
    )


def agreement(
    *,
    deposit: bool = False,
    payer: str = BUYER,
    dispute: str = DISPUTE,
    accepted_at: str = "2026-10-07T12:00:00.250000Z",
    start_utc: str = "2026-10-07T12:00:10.500000Z",
    duration_seconds: int = 3600,
    amount: str = "10000",
) -> dict[str, Any]:
    return Agreement(
        negotiation_id="neg-1",
        listing_id="listing-1",
        listing_hash="a" * 64,
        buyer={"scheme": "ed25519", "identifier": "buyer-key"},
        seller={"scheme": "ed25519", "identifier": "seller-key"},
        settlement=option(deposit=deposit, dispute=dispute),
        settlement_params={"payer_account": payer},
        amount=amount,
        asset="USD/2",
        duration_seconds=duration_seconds,
        start_utc=start_utc,
        provision_terms={"kind": "test.v1", "version": 1, "payload": {}},
        accepted_at=accepted_at,
    ).model_dump(mode="json", exclude_none=True)


def agreement_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True).encode()


def config(**overrides: Any) -> ArkhaiPaymentsConfig:
    values: dict[str, Any] = {
        "enabled": True,
        "service_url": "http://127.0.0.1:9",
        "service_identity": SERVICE.identity,
        "fee_bps": 250,
        "development_auth": True,
    }
    values.update(overrides)
    return ArkhaiPaymentsConfig(**values)
