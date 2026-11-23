"""The API-credit storefront's administrator: admitted as itself, never as a party.

The administrator reads a listing's negotiations and drives a round only
through its own operations, which the canonical storefront client signs and the
storefront verifies; the round is recorded as the administrator's. On every
route that binds its caller to a deal as a party -- a buyer's, the seller's own
counterparty routes -- a request signed under the ``admin`` role by an active
administrator principal, over the operation and resource that party signs, is
refused. The negotiation runs through the real
API-credit runtime over a temporary SQLite database; only the capacity snapshot
and key lookups are faked, at the seams the runtime resolves them through.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from apicredits_storefront.domain_runtime import get_market_domain_contract
from apicredits_storefront.negotiation_runtime import (
    build_api_credit_negotiation_runtime,
)
from core_storefront.services.negotiation_service import NegotiationService
from core_storefront.stage_log import set_stage_event_db_path, stage_event
from fastapi import FastAPI
from market_identity import EMPTY_BODY, Ed25519Signer, TrustedIdentitySet
from storefront_client import StorefrontClient
from storefront_client.client import StorefrontClientError

import apicredits_storefront.container as container
import apicredits_storefront.server as server
from apicredits_storefront.listing_publication import (
    PUBLISH_FROM_QUOTA_OPERATION,
    PUBLISH_FROM_QUOTA_PATH,
    seller_resource,
)
from apicredits_storefront.middleware import admin_auth
from apicredits_storefront.middleware.response_auth import authenticate_response
from tests._settings_overrides import settings_overrides
from tests.integration.credit_negotiation import (
    BUYER_PRINCIPAL,
    BUYER_SIGNER,
    LISTING_ID,
    SELLER_PRINCIPAL,
    SELLER_SIGNER,
    proposal,
    terms,
)

# A deterministic development key for this test only; never used on any network.
ADMIN_SIGNER = Ed25519Signer(bytes.fromhex("44" * 32))
ADMIN = ADMIN_SIGNER.identity
_DOMAIN = get_market_domain_contract()
_PUBLISHERS = TrustedIdentitySet(identities=(SELLER_PRINCIPAL,))


@pytest.fixture
async def storefront(db, fake_capacity, key_records, monkeypatch):
    """Every router the storefront mounts, over the real negotiation runtime,
    with ``ADMIN`` its one configured administrator."""
    runtime = build_api_credit_negotiation_runtime(_DOMAIN)
    monkeypatch.setattr(container, "resolved_sqlite_client", db)
    monkeypatch.setattr(container, "resolved_negotiation_runtime", runtime)
    monkeypatch.setattr(
        container,
        "resolved_negotiation_service",
        NegotiationService(
            sqlite_client=db,
            continue_negotiation=runtime.continue_negotiation,
            stage_event=stage_event,
        ),
    )
    monkeypatch.setattr(container, "resolved_marketplace_signer", SELLER_SIGNER)
    monkeypatch.setattr(
        admin_auth,
        "resolve_admin_identities",
        lambda: TrustedIdentitySet(identities=(ADMIN,)),
    )
    set_stage_event_db_path(db.db_path)
    app = FastAPI()
    app.middleware("http")(authenticate_response)
    for router in _ROUTERS:
        app.include_router(router)
    try:
        with settings_overrides(
            **{
                "negotiation.policies": ["bisection"],
                "identity.scheme": SELLER_PRINCIPAL.scheme.value,
                "identity.identifier": SELLER_PRINCIPAL.identifier,
            }
        ):
            yield app, db, runtime
    finally:
        set_stage_event_db_path(None)


_ROUTERS = (
    server.system_router,
    server.listings_router,
    server.negotiate_router,
    server.negotiations_router,
    server.settle_router,
    server.settlements_router,
    server.admin_settle_router,
    server.lifecycle_router,
    server.trading_pause_router,
)


def _client(app: FastAPI, signer: Ed25519Signer, role: str) -> StorefrontClient:
    return StorefrontClient(
        "http://seller",
        signer=signer,
        caller_role=role,
        expected_publishers=_PUBLISHERS,
        transport=httpx.ASGITransport(app=app),
    )


async def _open_countered(runtime, db, *, buyer=BUYER_PRINCIPAL) -> str:
    """Open a negotiation the bisection policy counters, as a buyer would."""
    opened = await runtime.start(
        repository=db,
        listing_id=LISTING_ID,
        buyer_principal=buyer,
        seller_principal=SELLER_PRINCIPAL,
        proposal=proposal(250),
        terms=terms(3),
        seller_agent_url="http://seller:8002",
        buyer_agent_url="http://buyer:9000",
        actor_principal=buyer,
    )
    assert opened["action"] == "counter"
    return opened["negotiation_id"]


# -- the administrator's negotiation reads and controls ------------------------


async def test_the_administrator_reads_a_listings_negotiations_through_the_client(
    storefront,
):
    app, db, runtime = storefront
    negotiation_id = await _open_countered(runtime, db)

    async with _client(app, ADMIN_SIGNER, "admin") as admin:
        listed = await admin.list_negotiations(LISTING_ID)
        filtered = await admin.list_negotiations(
            LISTING_ID, buyer_principal=ADMIN, terminal_state="success"
        )
        detail = await admin.get_negotiation(LISTING_ID, negotiation_id)

    assert [thread.negotiation_id for thread in listed.negotiations] == [negotiation_id]
    assert filtered.negotiations == []
    assert detail.negotiation_id == negotiation_id
    assert detail.buyer_principal == BUYER_PRINCIPAL
    assert [message.sender_role for message in detail.messages] == ["buyer", "seller"]


async def test_negotiation_reads_are_refused_unsigned_and_signed_by_a_buyer(storefront):
    app, db, runtime = storefront
    negotiation_id = await _open_countered(runtime, db)
    detail_path = f"/api/v1/listings/{LISTING_ID}/negotiations/{negotiation_id}"

    # Rejection-path tests: the typed client signs every read as the
    # administrator, so an unsigned read is sent raw and a buyer's through the
    # client's generic signed request; only their status is asserted.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://seller"
    ) as unsigned:
        unsigned_list = await unsigned.get(f"/api/v1/listings/{LISTING_ID}/negotiations")
        unsigned_detail = await unsigned.get(detail_path)

    async with _client(app, BUYER_SIGNER, "buyer") as buyer:
        with pytest.raises(StorefrontClientError) as listed:
            await buyer.authenticated_request(
                "GET",
                f"/api/v1/listings/{LISTING_ID}/negotiations",
                role="buyer",
                operation="admin_list_negotiations",
                resource=f"{LISTING_ID}/negotiations?limit=50&offset=0",
                params={"limit": 50, "offset": 0},
            )
        with pytest.raises(StorefrontClientError) as read:
            await buyer.authenticated_request(
                "GET",
                detail_path,
                role="buyer",
                operation="admin_get_negotiation",
                resource=f"{LISTING_ID}/negotiations/{negotiation_id}",
            )

    assert (unsigned_list.status_code, unsigned_detail.status_code) == (401, 401)
    assert listed.value.status_code in {401, 403}
    assert read.value.status_code in {401, 403}


async def test_an_administrators_advance_is_recorded_as_the_administrators(storefront):
    app, db, runtime = storefront
    negotiation_id = await _open_countered(runtime, db)

    async with _client(app, ADMIN_SIGNER, "admin") as admin:
        advanced = await admin.advance_negotiation(
            LISTING_ID, negotiation_id, action="exit", reason="operator_decision"
        )
        detail = await admin.get_negotiation(LISTING_ID, negotiation_id)

    assert advanced.action == "exit"
    assert detail.terminal_state == "failure"
    last = detail.messages[-1]
    assert (last.sender_role, last.sender_principal) == ("admin", ADMIN)
    assert BUYER_PRINCIPAL not in {
        message.sender_principal
        for message in detail.messages
        if message.sender_role == "admin"
    }


async def test_a_negotiation_list_query_the_signature_does_not_cover_is_refused(
    storefront,
):
    """Rejection-path tests: queries the typed client never builds, each
    answered before anything is read; only their status is asserted."""
    app, _db, _runtime = storefront
    listing = f"/api/v1/listings/{LISTING_ID}/negotiations"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://seller"
    ) as unsigned:
        unknown = await unsigned.get(listing, params={"status": "open"})
        repeated = await unsigned.get(f"{listing}?limit=5&limit=6")
    async with _client(app, ADMIN_SIGNER, "admin") as admin:
        with pytest.raises(StorefrontClientError) as half_filter:
            await admin.authenticated_request(
                "GET", listing, role="admin", operation="admin_list_negotiations",
                resource=f"{LISTING_ID}/negotiations?buyer_scheme=ed25519&limit=50&offset=0",
                params={"buyer_scheme": "ed25519", "limit": 50, "offset": 0},
            )
        with pytest.raises(StorefrontClientError) as malformed:
            await admin.authenticated_request(
                "GET", listing, role="admin", operation="admin_list_negotiations",
                resource=(
                    f"{LISTING_ID}/negotiations?buyer_identifier=x"
                    "&buyer_scheme=nope&limit=50&offset=0"
                ),
                params={
                    "buyer_identifier": "x", "buyer_scheme": "nope",
                    "limit": 50, "offset": 0,
                },
            )

    assert (unknown.status_code, repeated.status_code) == (400, 400)
    assert (half_filter.value.status_code, malformed.value.status_code) == (422, 422)


# -- the party routes ----------------------------------------------------------


@dataclass(frozen=True)
class PartyRoute:
    """One route binding its caller to a deal as a party, with the operation
    and resource that party's client signs for it."""

    method: str
    path: str
    role: str
    operation: str
    resource: str
    body: Any = field(default=EMPTY_BODY)

    @property
    def id(self) -> str:
        return f"{self.method} {self.path}"


# Replaced by the thread the test opens, which the deal-bound routes name and
# the settle-status route reads before it authenticates.
_THREAD = "{thread}"

_ADMIN_AS_BUYER = ADMIN.model_dump(mode="json")

PARTY_ROUTES = (
    PartyRoute(
        "POST", PUBLISH_FROM_QUOTA_PATH, "seller", PUBLISH_FROM_QUOTA_OPERATION,
        seller_resource(SELLER_PRINCIPAL), {"resource_id": "svc-quota"},
    ),
    PartyRoute(
        "POST", "/api/v1/listings/{listing_id}/close", "seller", "close_listing",
        LISTING_ID,
    ),
    PartyRoute(
        "POST", "/api/v1/negotiate/new", "buyer", "negotiate_new", LISTING_ID,
        {
            "listing_id": LISTING_ID,
            "buyer_principal": _ADMIN_AS_BUYER,
            "provision_terms": terms(3).model_dump(mode="json"),
            "proposal": proposal(250).model_dump(mode="json", exclude_none=True),
        },
    ),
    PartyRoute(
        "POST", "/api/v1/negotiate/{neg_id}", "buyer", "negotiate_continue", _THREAD,
        {"action": "exit", "buyer_principal": _ADMIN_AS_BUYER},
    ),
    PartyRoute(
        "POST", "/api/v1/settle/{escrow_uid}", "buyer", "settle_escrow", _THREAD,
        {"negotiation_id": _THREAD, "buyer_principal": _ADMIN_AS_BUYER},
    ),
    PartyRoute(
        "GET", "/api/v1/settle/{escrow_uid}/status", "buyer", "settle_status", _THREAD,
    ),
    PartyRoute(
        "POST", "/api/v1/settlements/{negotiation_id}/refund", "seller",
        "refund_settlement", _THREAD,
    ),
)

#: The administrator's own routes.
ADMINISTRATOR_ROUTES = frozenset(
    {
        ("GET", "/api/v1/system/status"),
        ("GET", "/api/v1/system/events"),
        ("POST", "/api/v1/listings/{listing_id}/pause"),
        ("POST", "/api/v1/listings/{listing_id}/resume"),
        ("GET", "/api/v1/listings/{listing_id}/negotiations"),
        ("GET", "/api/v1/listings/{listing_id}/negotiations/{neg_id}"),
        ("POST", "/api/v1/listings/{listing_id}/negotiations/{neg_id}/advance"),
        ("POST", "/api/v1/listings/{listing_id}/negotiations/{neg_id}/force-accept"),
        ("GET", "/api/v1/admin/settle/{escrow_uid}/wait"),
        ("POST", "/api/v1/admin/lifecycle/pause"),
        ("POST", "/api/v1/admin/lifecycle/resume"),
        ("POST", "/api/v1/admin/lifecycle/{loop}/run-cycle"),
        ("POST", "/api/v1/admin/lifecycle/{loop}/dry-run"),
        ("POST", "/api/v1/admin/pause"),
        ("POST", "/api/v1/admin/resume"),
        # Mounted only while the process's time source is injected.
        ("POST", "/api/v1/admin/time"),
    }
)

#: Routes no one signs: health, the public listing reads, and the framework's
#: own documentation.
PUBLIC_ROUTES = frozenset(
    {
        ("GET", "/health"),
        ("GET", "/api/v1/system/health"),
        ("GET", "/api/v1/listings"),
        ("GET", "/api/v1/listings/{listing_id}"),
        ("GET", "/openapi.json"),
        ("GET", "/docs"),
        ("GET", "/docs/oauth2-redirect"),
        ("GET", "/redoc"),
    }
)


def _mounted(app) -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in app.routes
        if getattr(route, "path", None)
        for method in (getattr(route, "methods", None) or ())
        if method != "HEAD"
    }


def test_every_mounted_route_is_a_party_administrator_or_public_route():
    """Each route the storefront serves is classified once, so a new route is
    placed here, and a party route is swept below, before it ships."""
    party = {(route.method, route.path) for route in PARTY_ROUTES}
    mounted = _mounted(server.app)

    assert mounted - (party | ADMINISTRATOR_ROUTES | PUBLIC_ROUTES) == set()
    assert party <= mounted
    assert not party & ADMINISTRATOR_ROUTES and not party & PUBLIC_ROUTES


def _concrete(value: Any, thread: str) -> Any:
    if isinstance(value, str):
        return value.replace(_THREAD, thread)
    if isinstance(value, dict):
        return {key: _concrete(item, thread) for key, item in value.items()}
    return value


@pytest.mark.parametrize("route", PARTY_ROUTES, ids=lambda route: route.id)
async def test_a_party_route_refuses_the_administrator(storefront, route):
    """Signed under ``admin`` by the active administrator, over the operation
    and resource the party's own client signs and a body the route reads up to
    its authentication, naming the administrator as the buyer where the body
    names one: refused, and no negotiation is opened.

    A rejection-path test: the typed client signs a party's request only under
    that party's role, so the request is sent through its generic signed
    request, and only its status is asserted."""
    app, db, runtime = storefront
    thread = await _open_countered(runtime, db, buyer=ADMIN)
    path = (
        route.path.replace("{listing_id}", LISTING_ID)
        .replace("{neg_id}", thread)
        .replace("{escrow_uid}", thread)
        .replace("{negotiation_id}", thread)
    )
    before = await db.list_negotiations_for_listing(
        listing_id=LISTING_ID, terminal_state=None, buyer_principal=None,
        limit=200, offset=0,
    )

    async with _client(app, ADMIN_SIGNER, "admin") as admin:
        with pytest.raises(StorefrontClientError) as refused:
            await admin.authenticated_request(
                route.method,
                path,
                role="admin",
                operation=route.operation,
                resource=_concrete(route.resource, thread),
                body=_concrete(route.body, thread),
            )

    assert refused.value.status_code in {401, 403}, refused.value
    after = await db.list_negotiations_for_listing(
        listing_id=LISTING_ID, terminal_state=None, buyer_principal=None,
        limit=200, offset=0,
    )
    assert after == before
