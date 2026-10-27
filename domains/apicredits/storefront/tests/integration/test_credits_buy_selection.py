"""`market credits buy` opens at the selected payment option's rate.

The listing advertises a legacy escrow at 100 per token beside an Arkhai
payments option at 70 per credit. The buyer selects the payment option, so
its opening and the agreed amount are priced from that option's rate, not
from the escrow advertised first. The real command runs against the real
negotiation routes, authentication middleware and API-credit negotiation
runtime, served on loopback: the buyer negotiates through the production
signed client in `core_buyer`, as it does in service. Registry discovery, the
buyer's identity and configuration, the quota hold, and payment settlement
after agreement are controlled at the seams they resolve through.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from arkhai_api_buying import buy as buy_cli
from arkhai_api_buying import settlement_composition
from arkhai_api_buying_arkhai_payments import payments
from arkhai_api_buying_arkhai_payments import stage as settlement_stages
from arkhai_apicredits_buyer.cli import app as buyer_app
from core_buyer import BuyResult, orchestration
from core_buyer.buyer_config import ResolvedBuyerIdentity
from core_buyer.registry_config import RegistryAuthority
from fastapi import FastAPI
from market_arkhai_payments import (
    ARKHAI_PAYMENTS_MECHANISM,
    ArkhaiPaymentsConfig,
    servicing_stage,
)
from market_arkhai_payments.fixtures import FakePaymentsClient
from market_identity import TrustedIdentitySet
from typer.testing import CliRunner

import apicredits_storefront.container as container
from apicredits_storefront.controllers.negotiate_controller import (
    router as negotiate_router,
)
from apicredits_storefront.domain_runtime import get_market_domain_contract
from apicredits_storefront.server import build_api_credit_negotiation_runtime
from apicredits_storefront.container import SELLER_STAGES
from tests._settings_overrides import settings_overrides
from tests.integration.credit_negotiation import (
    BUYER_SIGNER,
    DISPUTE_ACCOUNT,
    ESCROW,
    LISTING_ID,
    PAYER_ACCOUNT,
    PAYMENTS_SERVICE,
    SELLER_SIGNER,
    TOKEN,
    QuotaHolds,
    payment_option,
)
from tests.loopback import serving

_DOMAIN = get_market_domain_contract()
_IDENTITY = ResolvedBuyerIdentity(
    profile_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
    principal=BUYER_SIGNER.identity,
    signer=BUYER_SIGNER,
    source="primary",
)
_QUANTITY = 3
_PAYMENT_RATE = 70
_ESCROW_ENTRY = {
    "chain_name": "anvil",
    "escrow_address": ESCROW,
    "literal_fields": {"token": TOKEN},
    "rates": [{"field": "amount", "per": "token", "value": "100"}],
}


@pytest.fixture
async def storefront(db, fake_capacity, key_records, monkeypatch):
    """The served negotiation routes of a storefront advertising both options."""
    stage = servicing_stage(
        ArkhaiPaymentsConfig(
            enabled=True,
            service_url="http://127.0.0.1:9",
            service_identity=PAYMENTS_SERVICE.identity,
            fee_bps=250,
            dispute_authority=DISPUTE_ACCOUNT,
            development_auth=True,
        ),
        client_for_owner=FakePaymentsClient(),
    )
    composition = SimpleNamespace(servicing={ARKHAI_PAYMENTS_MECHANISM: stage})
    runtime = build_api_credit_negotiation_runtime(
        _DOMAIN,
        accepted_obligation_dispatch={ARKHAI_PAYMENTS_MECHANISM: None},
        settlement_artifacts_builder=lambda agreement: SELLER_STAGES[
            agreement["settlement"]["mechanism"]
        ].agreement_artifacts(agreement, composition),
    )
    holds = QuotaHolds()
    monkeypatch.setattr(
        container.QUOTA_CAPACITY, "runtime", lambda _factory: holds
    )
    monkeypatch.setattr(container, "resolved_sqlite_client", db)
    monkeypatch.setattr(container, "resolved_negotiation_runtime", runtime)
    monkeypatch.setattr(container, "resolved_marketplace_signer", SELLER_SIGNER)
    await db.update_listing(
        listing_id=LISTING_ID,
        accepted_escrows=[dict(_ESCROW_ENTRY)],
        settlement_options=[payment_option(_PAYMENT_RATE).model_dump(mode="json")],
    )
    app = FastAPI()
    app.middleware("http")(container.AUTH.sign_responses)
    app.include_router(negotiate_router)
    with settings_overrides(
        **{
            "identity.scheme": "ed25519",
            "identity.identifier": SELLER_SIGNER.identity.identifier,
            "capacity.hold_ttl_seconds": 300,
        }
    ):
        with serving(app) as base_url:
            yield SimpleNamespace(base_url=base_url, db=db, holds=holds)


@pytest.fixture
def buyer(storefront, monkeypatch, tmp_path):
    """The buyer's registry, identity and configuration; settlement is recorded."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    publishers = TrustedIdentitySet(identities=(SELLER_SIGNER.identity,))
    listing = {
        "listing_id": LISTING_ID,
        "storefront_url": storefront.base_url,
        "publisher_id": 7,
        "source_registry_url": "http://registry",
        "source_registry_authority": "registry",
        "publisher_principals": publishers.model_dump(mode="json"),
        "accepted_escrows": [dict(_ESCROW_ENTRY)],
        "settlement_options": [payment_option(_PAYMENT_RATE).model_dump(mode="json")],
    }
    seams = {
        "resolve_fresh_buyer_identity": lambda: _IDENTITY,
        "resolve_indexer_urls": lambda **_kw: ["http://registry"],
        "resolve_indexer_urls_for_schema": lambda *_a, **_kw: ["http://registry"],
        "resolve_registry_authorities": lambda urls: {
            url: RegistryAuthority(authority="registry", principals=publishers)
            for url in urls
        },
        "resolve_registry_api_keys": lambda: {},
    }
    for name, seam in seams.items():
        monkeypatch.setattr(buy_cli, name, seam)
    monkeypatch.setattr(
        buy_cli, "query_registry_for_matches_multi", lambda *_a, **_kw: [dict(listing)]
    )
    # The publisher-trust refresh re-reads the listing from its registry.
    monkeypatch.setattr(orchestration, "fetch_listing_dict", lambda *_a, **_kw: dict(listing))
    config = {
        "Settlement": {
            "schema_version": 1,
            "priority": [ARKHAI_PAYMENTS_MECHANISM],
            "arkhai_payments": {"enabled": True},
        },
        "apicredits": {"payer_account": PAYER_ACCOUNT},
    }
    monkeypatch.setattr(settlement_composition, "load_user_config", lambda: config)
    monkeypatch.setattr(payments, "load_user_config", lambda: config)
    settled: list[Any] = []

    def settle(*, negotiation, **_kwargs):
        settled.append(negotiation)
        return BuyResult(
            status="ready",
            seller_url=storefront.base_url,
            negotiation_id=negotiation.outcome.negotiation_id,
            agreed_amount=negotiation.outcome.agreed_amount,
        )

    monkeypatch.setattr(settlement_stages, "settle_negotiation", settle)
    return SimpleNamespace(settled=settled)


def _buy():
    return CliRunner().invoke(
        buyer_app,
        ["credits", "buy", "--quantity", str(_QUANTITY), "--yes"],
    )


async def test_the_opening_is_priced_from_the_selected_payment_option(
    storefront, buyer
) -> None:
    result = await asyncio.to_thread(_buy)
    assert result.exit_code == 0, (result.output, result.exception)

    [negotiation] = buyer.settled
    expected = _PAYMENT_RATE * _QUANTITY
    option = payment_option(_PAYMENT_RATE)
    assert negotiation.outcome.agreed_amount == expected

    # The seller's own record of the deal: the payment option, at its rate.
    thread = await storefront.db.load_negotiation_thread_row(
        negotiation_id=negotiation.outcome.negotiation_id
    )
    assert thread["terminal_state"] == "success"
    assert int(thread["agreed_price"]) == expected
    agreement = json.loads(thread["agreement_bytes"])
    assert agreement["settlement"]["mechanism"] == ARKHAI_PAYMENTS_MECHANISM
    assert agreement["settlement"]["option_id"] == option.option_id
    assert agreement["amount"] == str(expected)
    messages = await storefront.db.load_negotiation_thread(
        negotiation_id=negotiation.outcome.negotiation_id
    )
    opening = next(message for message in messages if message["sender_role"] == "buyer")
    assert int(opening["proposed_price"]) == expected
