"""Exact settlement selections through the canonical storefront client.

The storefront's negotiation routes, response authentication, and the
API-credit negotiation runtime run over a temporary SQLite database, composed
with the obligation dispatch production composes: neither Alkahest nor Arkhai
payments builds an accepted obligation from an option. A payment deal settles
from the accepted Agreement, so its exact selection is accepted without a plan;
an Alkahest escrow is settled only under the plan its escrow proposal
materializes against the listing's release condition, which a selection
cannot build, so its exact selection is refused. Only the capacity snapshot,
key lookups, and the payments service client are controlled, at the seams they
resolve through.
"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import httpx
import pytest
from apicredits_storefront.domain_runtime import get_market_domain_contract
from apicredits_storefront.server import build_api_credit_negotiation_runtime
from apicredits_storefront.settlement_composition import SELLER_STAGES
from fastapi import FastAPI
from market_alkahest import ALKAHEST_MECHANISM_ID
from market_arkhai_payments import (
    ARKHAI_PAYMENTS_MECHANISM,
    ArkhaiPaymentsConfig,
    servicing_stage,
)
from market_arkhai_payments.fixtures import FakePaymentsClient
from market_core.schemas import RateValue, SettlementOption, derive_settlement_option_id
from market_identity import Ed25519Signer, TrustedIdentitySet
from storefront_client import StorefrontClient, StorefrontClientError

import apicredits_storefront.container as container
from apicredits_storefront.controllers.negotiate_controller import (
    router as negotiate_router,
)
from apicredits_storefront.middleware.response_auth import authenticate_response
from tests._settings_overrides import settings_overrides
from tests.integration.credit_negotiation import (
    BUYER_SIGNER,
    CONDITION,
    ESCROW,
    LISTING_ID,
    PAYER_ACCOUNT,
    SELLER_SIGNER,
    TOKEN,
    payment_option,
    terms,
)

# A deterministic development key for this test only; never used on any network.
_SERVICE = Ed25519Signer(bytes.fromhex("55" * 32))
_DISPUTE = "33333333-3333-4333-8333-333333333333"
_DOMAIN = get_market_domain_contract()


def _alkahest_option() -> SettlementOption:
    """The seeded listing's escrow as its Alkahest option publishes it."""
    rates = [RateValue(field="amount", per="token", value=100)]
    params = {
        "accepted_escrow": {
            "chain_name": "anvil",
            "escrow_address": ESCROW,
            "literal_fields": {"token": TOKEN},
            "rates": [{"field": "amount", "per": "token", "value": "100"}],
        }
    }
    return SettlementOption(
        option_id=derive_settlement_option_id(
            mechanism=ALKAHEST_MECHANISM_ID, asset=TOKEN, rates=rates, params=params
        ),
        mechanism=ALKAHEST_MECHANISM_ID,
        asset=TOKEN,
        rates=rates,
        params=params,
    )


@pytest.fixture
async def storefront(db, fake_capacity, key_records, monkeypatch):
    """The served negotiation routes, composed as production composes them."""
    stage = servicing_stage(
        ArkhaiPaymentsConfig(
            enabled=True,
            service_url="http://127.0.0.1:9",
            service_identity=_SERVICE.identity,
            fee_bps=250,
            dispute_authority=_DISPUTE,
            development_auth=True,
        ),
        client_for_owner=FakePaymentsClient(),
    )
    composition = SimpleNamespace(arkhai_payments_stage=stage)
    runtime = build_api_credit_negotiation_runtime(
        _DOMAIN,
        accepted_obligation_dispatch={
            ALKAHEST_MECHANISM_ID: None,
            ARKHAI_PAYMENTS_MECHANISM: None,
        },
        settlement_artifacts_builder=lambda agreement: SELLER_STAGES[
            agreement["settlement"]["mechanism"]
        ].agreement_artifacts(agreement, composition),
    )
    monkeypatch.setattr(container, "resolved_sqlite_client", db)
    monkeypatch.setattr(container, "resolved_negotiation_runtime", runtime)
    monkeypatch.setattr(container, "resolved_marketplace_signer", SELLER_SIGNER)
    await db.update_listing(
        listing_id=LISTING_ID,
        settlement_options=[
            _alkahest_option().model_dump(mode="json"),
            payment_option().model_dump(mode="json"),
        ],
    )
    app = FastAPI()
    app.middleware("http")(authenticate_response)
    app.include_router(negotiate_router)
    with settings_overrides(
        **{
            "identity.scheme": "ed25519",
            "identity.identifier": SELLER_SIGNER.identity.identifier,
        }
    ):
        yield SimpleNamespace(app=app, db=db)


def _buyer(app) -> StorefrontClient:
    return StorefrontClient(
        "http://seller",
        signer=BUYER_SIGNER,
        caller_role="buyer",
        expected_publishers=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
        transport=httpx.ASGITransport(app=app),
    )


async def _open_selecting(app, option: SettlementOption, **params) -> dict:
    async with _buyer(app) as buyer:
        # Three credits at the options' listed 100 per credit.
        return await buyer.negotiate_new(
            listing_id=LISTING_ID,
            initial_amount=300,
            provision_terms=terms(3).model_dump(mode="json"),
            settlement_selection={
                "mechanism": option.mechanism,
                "option_id": option.option_id,
                "expiration_unix": 1_900_000_000,
                **({"params": params} if params else {}),
            },
            selection_only=True,
        )


def _threads(db) -> int:
    with sqlite3.connect(db.db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM negotiation_threads").fetchone()[0]


@pytest.mark.parametrize(
    "demands", [[CONDITION], []], ids=["authorized condition", "no demands"]
)
async def test_an_exact_alkahest_selection_is_refused_with_nothing_recorded(
    storefront, demands
):
    await storefront.db.update_listing(listing_id=LISTING_ID, demands=demands)

    with pytest.raises(StorefrontClientError) as refused:
        await _open_selecting(storefront.app, _alkahest_option())

    assert refused.value.status_code == 409
    assert "settlement_selection_requires_plan" in str(refused.value)
    assert _threads(storefront.db) == 0


async def test_an_exact_payment_selection_is_accepted_with_its_agreement(storefront):
    accepted = await _open_selecting(
        storefront.app, payment_option(), payer_account=PAYER_ACCOUNT
    )

    assert accepted["action"] == "accept"
    assert accepted.get("settlement_plan") is None
    assert accepted["agreement_bytes"]
    assert accepted["settlement_data"]["mandate"]
    thread = await storefront.db.load_negotiation_thread_row(
        negotiation_id=accepted["negotiation_id"]
    )
    assert thread["terminal_state"] == "success"
    assert thread["agreement_bytes"]
