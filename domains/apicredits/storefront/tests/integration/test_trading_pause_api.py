"""The API-credit trading pause and the event read's signature, over HTTP.

Pause and resume are the storefront kit's route service, bound at the paths the
canonical storefront client calls; these tests sign with that client and verify
the storefront's signed responses. While paused, the negotiation runtime refuses
a new negotiation. The negotiation runs through the real API-credit runtime over
a temporary SQLite database, with the capacity snapshot and key lookups faked as
in the other integration tests.
"""

from __future__ import annotations

import httpx
import pytest
from apicredits_storefront.domain_runtime import get_market_domain_contract
from apicredits_storefront.negotiation_runtime import (
    build_api_credit_negotiation_runtime,
)
from fastapi import FastAPI
from market_identity import Ed25519Signer, TrustedIdentitySet
from market_negotiation_runtime import StorefrontPausedError
from storefront_client import StorefrontClient

import apicredits_storefront.container as container

from apicredits_storefront.controllers.system_controller import (
    router as system_router,
)
from apicredits_storefront.controllers.trading_pause_controller import (
    router as trading_pause_router,
)
from apicredits_storefront.middleware import admin_auth
from apicredits_storefront.middleware.response_auth import authenticate_response
from tests._settings_overrides import settings_overrides
from tests.integration.credit_negotiation import (
    BUYER_PRINCIPAL,
    LISTING_ID,
    SELLER_PRINCIPAL,
    SELLER_SIGNER,
    proposal,
    terms,
)

# A deterministic development key for this test only; never used on any network.
ADMIN_SIGNER = Ed25519Signer(bytes.fromhex("44" * 32))


@pytest.fixture
async def storefront(db, fake_capacity, key_records, monkeypatch):
    runtime = build_api_credit_negotiation_runtime(get_market_domain_contract())
    monkeypatch.setattr(container, "resolved_sqlite_client", db)
    monkeypatch.setattr(container, "resolved_negotiation_runtime", runtime)
    monkeypatch.setattr(container, "resolved_marketplace_signer", SELLER_SIGNER)
    monkeypatch.setattr(
        admin_auth,
        "resolve_admin_identities",
        lambda: TrustedIdentitySet(identities=(ADMIN_SIGNER.identity,)),
    )
    container.trading_pause.resume()
    app = FastAPI()
    app.middleware("http")(authenticate_response)
    app.include_router(trading_pause_router)
    app.include_router(system_router)
    try:
        yield app, db, runtime
    finally:
        container.trading_pause.resume()


def _admin(app) -> StorefrontClient:
    return StorefrontClient(
        "http://seller",
        signer=ADMIN_SIGNER,
        caller_role="admin",
        expected_publishers=TrustedIdentitySet(identities=(SELLER_PRINCIPAL,)),
        transport=httpx.ASGITransport(app=app),
    )


async def _open(runtime, db) -> dict:
    return await runtime.start(
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


async def test_a_paused_storefront_refuses_openings_until_resumed(storefront):
    app, db, runtime = storefront
    with settings_overrides(**{"negotiation.policies": ["bisection"]}):
        async with _admin(app) as admin:
            paused = await admin.admin_pause()
            assert paused.paused is True
            with pytest.raises(StorefrontPausedError):
                await _open(runtime, db)

            resumed = await admin.admin_resume()
            assert resumed.paused is False
            opened = await _open(runtime, db)

    assert opened["action"] == "counter"


@pytest.mark.parametrize(
    "query",
    ["limit=100&since_id=0&stream=false&after=1", "stream=true", "stage=a&stage=b"],
)
async def test_an_event_read_the_signature_does_not_bind_is_refused(storefront, query):
    app, _db, _runtime = storefront
    # Rejection path: the canonical client cannot send these, so the request is
    # raw, and only its status is asserted.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://seller"
    ) as raw:
        response = await raw.get(f"/api/v1/system/events?{query}")
    assert response.status_code == 400
