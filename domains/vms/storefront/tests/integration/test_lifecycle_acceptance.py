"""Hosted VM acceptance retains both exact signed negotiation envelopes."""

import json

import pytest
from market_arkhai_payments import PaymentSellerStage
from market_arkhai_payments.fixtures import FakePaymentsClient
from market_core.schemas import SettlementOption, derive_settlement_option_id

from market_storefront import container
from tests.integration.test_negotiate_controller import (
    _RUNTIME_BUILDERS,
    _upsert_bound_listing,
    _vm_provision,
)
from tests.integration.test_negotiate_controller import client as client
from tests.integration.test_negotiate_controller import db as db
from tests.integration.test_payment_settlement import PAYER, _config, _option


@pytest.mark.asyncio
async def test_hosted_acceptance_stores_original_request_and_signed_acceptance(client, db):
    buyer, _ = client
    await _upsert_bound_listing(db, "hosted", demands=[])
    body = _option(deposit=False).model_dump(mode="json", exclude={"option_id"})
    body["price"]["rates"] = [{"field": "amount", "per": "hour", "value": "100"}]
    option = SettlementOption(option_id=derive_settlement_option_id(**body), **body)
    await db.update_listing(listing_id="hosted", settlement_options=[option.model_dump(mode="json")])
    container.resolved_negotiation_runtime = _RUNTIME_BUILDERS[0](
        arkhai_payments_stage=PaymentSellerStage(_config(), client_for_owner=FakePaymentsClient()),
        accepted_obligation_dispatch={"arkhai.payments.v1": None},
    )
    accepted = await buyer.negotiate_new(
        listing_id="hosted", initial_amount=100, provision_terms=_vm_provision(),
        settlement_selection={"option_id": option.option_id, "settlement": {
            "schema": "arkhai.payments.v1", "payer_account": PAYER,
        }, "expiration_unix": 1_900_000_000},
        selection_only=True,
    )
    assert accepted["action"] == "accept"
    lifecycle = container.resolved_settlement_composition.lifecycle
    kept = await lifecycle.evidence.read(accepted["negotiation_id"])
    assert len(kept.items) == 2
    assert any(json.loads(item.body) == accepted and any(
        key.lower() == "x-market-signature" for key in item.headers
    ) for item in kept.items)
    opening = next(item for item in kept.items if item.context["role"] == "buyer")
    assert json.loads(opening.body)["settlement_selection"]["option_id"] == option.option_id
    assert any(key.lower() == "x-market-signature" for key in opening.headers)
    assert kept.acceptance_expires_at is not None
