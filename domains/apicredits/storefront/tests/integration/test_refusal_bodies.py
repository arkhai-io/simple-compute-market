"""API-credit refusal bodies are byte-identical to those the storefront served before the family kit.

Driven through the canonical storefront client against the served negotiation
routes; the response bytes are read at the transport, since the client reports
only a prefix of an error body.
"""

from __future__ import annotations

import json
import sqlite3

import httpx
import pytest
from fastapi import FastAPI
from market_arkhai_payments import ARKHAI_PAYMENTS_MECHANISM
from market_core.schemas import RateValue, SettlementOption, derive_settlement_option_id
from market_identity import TrustedIdentitySet
from market_negotiation_runtime import NegotiationStateError
from storefront_client import StorefrontClient, StorefrontClientError

import apicredits_storefront.container as container
from apicredits_storefront.controllers.negotiate_controller import router as negotiate_router
from apicredits_storefront.domain_runtime import get_market_domain_contract
from apicredits_storefront.middleware.response_auth import authenticate_response
from apicredits_storefront.server import build_api_credit_negotiation_runtime
from tests._settings_overrides import settings_overrides
from tests.integration.credit_negotiation import (
    BUYER_PRINCIPAL,
    BUYER_SIGNER,
    LISTING_ID,
    PAYEE_ACCOUNT,
    SELLER_PRINCIPAL,
    SELLER_SIGNER,
    payment_option,
    proposal,
    terms,
)

_DOMAIN = get_market_domain_contract()


class _Recording(httpx.AsyncBaseTransport):
    def __init__(self, app) -> None:
        self._inner = httpx.ASGITransport(app=app)
        self.bodies: list[bytes] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        body = await response.aread()
        self.bodies.append(body)
        return httpx.Response(response.status_code, headers=response.headers, content=body)


def _hourly_payment_option() -> SettlementOption:
    rates = [RateValue(field="amount", per="hour", value=100)]
    params = {"payee_account": PAYEE_ACCOUNT, "asset": "USD/2"}
    return SettlementOption(
        option_id=derive_settlement_option_id(
            mechanism=ARKHAI_PAYMENTS_MECHANISM, asset="USD/2", rates=rates, params=params
        ),
        mechanism=ARKHAI_PAYMENTS_MECHANISM,
        asset="USD/2",
        rates=rates,
        params=params,
    )


@pytest.fixture
async def served(db, fake_capacity, key_records, monkeypatch):
    runtime = build_api_credit_negotiation_runtime(
        _DOMAIN, accepted_obligation_dispatch={ARKHAI_PAYMENTS_MECHANISM: None}
    )
    monkeypatch.setattr(container, "resolved_sqlite_client", db)
    monkeypatch.setattr(container, "resolved_negotiation_runtime", runtime)
    monkeypatch.setattr(container, "resolved_marketplace_signer", SELLER_SIGNER)
    app = FastAPI()
    app.middleware("http")(authenticate_response)
    app.include_router(negotiate_router)
    transport = _Recording(app)
    with settings_overrides(
        **{"identity.scheme": "ed25519", "identity.identifier": SELLER_SIGNER.identity.identifier}
    ):
        yield transport


async def _refused(transport: _Recording, **opening) -> tuple[int, dict]:
    async with StorefrontClient(
        "http://seller",
        signer=BUYER_SIGNER,
        caller_role="buyer",
        expected_publishers=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
        transport=transport,
    ) as buyer:
        with pytest.raises(StorefrontClientError) as refused:
            await buyer.negotiate_new(listing_id=LISTING_ID, **opening)
    return refused.value.status_code, json.loads(transport.bodies[-1])


async def test_a_quota_refusal_body_is_unchanged(served, db, fake_capacity):
    fake_capacity.available = 2
    option = payment_option()
    await db.update_listing(listing_id=LISTING_ID, settlement_options=[option.model_dump(mode="json")])

    status, body = await _refused(
        served,
        initial_amount=300,
        provision_terms=terms(3).model_dump(mode="json"),
        settlement_selection={
            "mechanism": option.mechanism,
            "option_id": option.option_id,
            "expiration_unix": 1_900_000_000,
        },
        selection_only=True,
    )

    assert status == 409
    assert body == {
        "detail": {
            "error": "offer_unfulfillable",
            "reason": "quota_exhausted: requested 3 token(s), quota resource 'svc-quota' cannot cover it",
            "listing_id": LISTING_ID,
            "hint": (
                "Seller refused: listing is closed, the quota cannot cover the requested "
                "quantity, or the key claim was rejected. See `reason`."
            ),
        }
    }


async def test_a_pricing_refusal_body_is_unchanged(served, db):
    option = _hourly_payment_option()
    await db.update_listing(listing_id=LISTING_ID, settlement_options=[option.model_dump(mode="json")])

    status, body = await _refused(
        served,
        initial_amount=300,
        provision_terms=terms(3).model_dump(mode="json"),
        settlement_selection={
            "mechanism": option.mechanism,
            "option_id": option.option_id,
            "expiration_unix": 1_900_000_000,
        },
        selection_only=True,
    )

    assert (status, body) == (404, {"detail": "selected API-credit option rate is not per credit"})


async def test_a_continuation_whose_recorded_terms_changed_is_refused_with_its_unchanged_message(
    db, fake_capacity, key_records
):
    runtime = build_api_credit_negotiation_runtime(_DOMAIN)
    with settings_overrides(**{"negotiation.policies": ["bisection"]}):
        opening = await runtime.start(
            repository=db,
            listing_id=LISTING_ID,
            buyer_principal=BUYER_PRINCIPAL,
            seller_principal=SELLER_PRINCIPAL,
            proposal=proposal(250),
            terms=terms(3),
            seller_agent_url="http://seller:8002",
            buyer_agent_url="http://buyer:9000",
            actor_principal=BUYER_PRINCIPAL,
        )
        with sqlite3.connect(db.db_path) as conn:
            conn.execute("UPDATE credit_deal_terms SET quantity = 4")

        with pytest.raises(NegotiationStateError) as refused:
            await runtime.continue_negotiation(
                repository=db,
                negotiation_id=opening["negotiation_id"],
                buyer_action="accept",
                buyer_proposal=None,
                buyer_reason=None,
                buyer_principal=BUYER_PRINCIPAL,
                seller_principal=SELLER_PRINCIPAL,
                actor_principal=BUYER_PRINCIPAL,
                actor_role="buyer",
            )

    assert str(refused.value) == "recorded API-credit terms do not match the negotiation transcript"
