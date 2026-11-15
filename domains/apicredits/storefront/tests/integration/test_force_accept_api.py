"""API-credit deal controls through the canonical storefront client.

Force-accept, the stage-event read, and settle wait are kit route services every
storefront binds behind its own administrator authentication, reached through
the same `StorefrontClient` methods. These tests sign with that client and
verify the storefront's signed responses, so a route that authenticates a
contract other than the one the client signs fails here. The negotiation runs
through the real API-credit runtime over a temporary SQLite database; only the
capacity snapshot and key lookups are faked, at the seams the runtime resolves
them through.
"""

from __future__ import annotations

import httpx
import pytest
from apicredits_storefront.domain_runtime import get_market_domain_contract
from apicredits_storefront.negotiation_runtime import (
    build_api_credit_negotiation_runtime,
)
from core_storefront.stage_log import set_stage_event_db_path
from fastapi import FastAPI
from market_core import SettlementEvidence
from market_identity import Ed25519Signer, TrustedIdentitySet
from storefront_client import StorefrontClient
from storefront_client.client import StorefrontClientError

import apicredits_storefront.container as container

from apicredits_storefront.controllers.negotiations_controller import (
    router as negotiations_router,
)
from apicredits_storefront.controllers.settle_controller import admin_settle_router
from apicredits_storefront.controllers.system_controller import (
    router as system_router,
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
_DOMAIN = get_market_domain_contract()


@pytest.fixture
async def storefront(db, fake_capacity, key_records, monkeypatch):
    runtime = build_api_credit_negotiation_runtime(_DOMAIN)
    monkeypatch.setattr(container, "resolved_sqlite_client", db)
    monkeypatch.setattr(container, "resolved_negotiation_runtime", runtime)
    monkeypatch.setattr(container, "resolved_marketplace_signer", SELLER_SIGNER)
    monkeypatch.setattr(
        admin_auth,
        "resolve_admin_identities",
        lambda: TrustedIdentitySet(identities=(ADMIN_SIGNER.identity,)),
    )
    set_stage_event_db_path(db.db_path)
    app = FastAPI()
    app.middleware("http")(authenticate_response)
    app.include_router(negotiations_router)
    app.include_router(system_router)
    app.include_router(admin_settle_router)
    try:
        yield app, db, runtime, fake_capacity
    finally:
        set_stage_event_db_path(None)


def _admin(app, signer: Ed25519Signer = ADMIN_SIGNER) -> StorefrontClient:
    return StorefrontClient(
        "http://seller",
        signer=signer,
        caller_role="admin",
        expected_publishers=TrustedIdentitySet(identities=(SELLER_PRINCIPAL,)),
        transport=httpx.ASGITransport(app=app),
    )


async def _open_countered(runtime, db) -> str:
    """Open a negotiation the bisection policy counters, as a buyer would."""
    opened = await runtime.start(
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
    assert opened["action"] == "counter"
    return opened["negotiation_id"]


async def test_force_accept_through_the_client_records_a_negotiated_acceptance(
    storefront,
):
    app, db, runtime, capacity = storefront
    with settings_overrides(**{"negotiation.policies": ["bisection"]}):
        negotiation_id = await _open_countered(runtime, db)

        async with _admin(app) as admin:
            accepted = await admin.force_accept_negotiation(
                LISTING_ID, negotiation_id, amount=290
            )
            events = await admin.get_events(negotiation_id=negotiation_id)

    assert accepted.action == "accept"
    assert accepted.amount == 290
    thread = await db.load_negotiation_thread_row(negotiation_id=negotiation_id)
    assert thread["terminal_state"] == "success"
    assert int(thread["negotiated_scalar"]) == 290
    assert await db.load_credit_terms(negotiation_id=negotiation_id) == {
        "negotiation_id": negotiation_id,
        "quantity": 3,
        "key_mode": "new",
        "key_id": None,
    }
    # API credits grants no unfunded quota hold at acceptance, forced or not.
    assert capacity.reserved == []
    assert await db.load_capacity_hold(negotiation_id=negotiation_id) is None
    assert events.events, "the forced acceptance recorded no stage events"
    assert {event.negotiation_id for event in events.events} == {negotiation_id}


async def test_force_accept_refuses_a_terminal_negotiation_through_the_client(
    storefront,
):
    app, db, runtime, _capacity = storefront
    with settings_overrides(**{"negotiation.policies": ["bisection"]}):
        negotiation_id = await _open_countered(runtime, db)
        async with _admin(app) as admin:
            await admin.force_accept_negotiation(LISTING_ID, negotiation_id, amount=290)
            with pytest.raises(StorefrontClientError) as refused:
                await admin.force_accept_negotiation(
                    LISTING_ID, negotiation_id, amount=290
                )

    assert refused.value.status_code == 409


async def test_an_unconfigured_administrator_cannot_force_accept(storefront):
    app, db, runtime, _capacity = storefront
    with settings_overrides(**{"negotiation.policies": ["bisection"]}):
        negotiation_id = await _open_countered(runtime, db)
        stranger = Ed25519Signer(bytes.fromhex("66" * 32))
        async with _admin(app, stranger) as admin:
            with pytest.raises(StorefrontClientError) as refused:
                await admin.force_accept_negotiation(
                    LISTING_ID, negotiation_id, amount=290
                )

    assert refused.value.status_code in {401, 403}
    thread = await db.load_negotiation_thread_row(negotiation_id=negotiation_id)
    assert thread["terminal_state"] is None


# The listing resource the evidence's delivery names; a development fixture.
_OFFER = {
    "kind": "api_credits.v1",
    "service_name": "Acme Inference",
    "base_url": "https://api.acme.example",
    "resource_id": "svc-quota",
    "capacity_site_id": "tokens",
    "offering_mode": "api_credits",
}


def _evidence(negotiation_id: str, mechanism: str, settlement_ref: str) -> SettlementEvidence:
    """Verified evidence as settlement records it, set up directly: no route
    writes evidence without a payment or an escrow behind it."""
    return SettlementEvidence(
        negotiation_id, mechanism, settlement_ref, "verified",
        {"kind": "api_credits.settlement-evidence.v1", "schema_version": 1,
         "agreement_digest": "a" * 64, "source": {"verified_source": "fixture"},
         "delivery": {"owner": BUYER_PRINCIPAL.model_dump(mode="json"),
                      "listing_resource": dict(_OFFER), "quantity": 3, "key_mode": "new",
                      "key_id": None, "listing_id": LISTING_ID}},
    )


async def test_settle_wait_reports_a_payments_deal_by_its_negotiation(storefront):
    """Issuance progress, the domain's delivery status, is read under the
    negotiation the evidence names, whichever reference the wait was given."""
    app, db, _runtime, _capacity = storefront
    await db.save_settlement_evidence(
        _evidence("negotiation-paid", "arkhai.payments.v1", "txn-paid")
    )
    await db.save_issuance_progress(
        negotiation_id="negotiation-paid", public_ref="negotiation-paid", status="ready"
    )

    async with _admin(app) as admin:
        by_negotiation = await admin.wait_for_settlement("negotiation-paid", timeout=1.0)
        by_transaction = await admin.wait_for_settlement("txn-paid", timeout=1.0)

    for waited in (by_negotiation, by_transaction):
        assert (waited.ready, waited.status) == (True, "ready")


async def test_settle_wait_reports_an_alkahest_deal_by_its_escrow(storefront):
    app, db, _runtime, _capacity = storefront
    await db.save_settlement_evidence(
        _evidence("negotiation-escrow", "alkahest.v1", "0xsettled")
    )
    await db.save_issuance_progress(
        negotiation_id="negotiation-escrow", public_ref="0xsettled", status="failed"
    )

    async with _admin(app) as admin:
        waited = await admin.wait_for_settlement("0xsettled", timeout=1.0)

    assert (waited.ready, waited.status) == (True, "failed")
