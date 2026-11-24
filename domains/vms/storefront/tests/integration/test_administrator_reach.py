"""The VM storefront's administrator: admitted as itself, never as a party.

On every route that binds its caller to a deal as a party -- a buyer's, the
seller's own counterparty routes, a site's callbacks -- a request signed under
the ``admin`` role by an active administrator principal, over the operation and
resource that party's client signs and a body the route reads up to its
authentication, is refused. The administrator's advance is
recorded as the administrator's round, not the buyer's. The lifecycle routes
the storefront mounts from the deal-servicing kit are held by that kit's own
tests.

Every principal here is a deterministic development fixture; never use one on
a public network.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from compute_provisioning_contracts import LeaseEndedEvent, sign_lease_end
from core_storefront.service_peers import ServicePeerTrust
from fastapi import FastAPI
from market_core.schemas import ProvisionTerms
from market_identity import EMPTY_BODY, Ed25519Signer, TrustedIdentitySet
from storefront_client import StorefrontClient, StorefrontClientError

import market_storefront.container as _container
import market_storefront.middleware.admin_identity as _admin_identity
import market_storefront.server as server
from market_storefront.middleware.service_peer_auth import (
    service_peer_callback_middleware,
)
from market_storefront.middleware.seller_auth import listing_lifecycle_middleware
from tests.integration.test_negotiations_api import (  # noqa: F401 - fixtures
    _seed_order,
    _seed_thread,
    api,
    client,
    db,
)
from tests.integration.test_negotiations_api import _ADMIN_SIGNER as _NEGOTIATIONS_ADMIN
from tests.integration.test_payment_settlement import LISTING, NEGOTIATION, SELLER
from tests.integration.test_settle_controller import ADMIN_SIGNER, ADMINISTRATORS
from tests.integration.test_vm_delivery_path import payment_rig  # noqa: F401 - fixture
from tests.fake_site import TEST_MARKETPLACE_SIGNER
from tests.introduction_deals import (
    BUYER_CONTACT,
    CONTACT_PUBLISHABLE,
    accept_introduction,
    introduction_transport,
    offer_introduction,
    publish,
)
from tests.loopback import serving
from tests.publication_app import SITE as SITE_A
from tests.publication_app import SITE_CONTACTS, pool, publication_app

ADMIN = ADMIN_SIGNER.identity
_ADMIN_AS_PARTY = ADMIN.model_dump(mode="json")
_PUBLISHERS = TrustedIdentitySet(identities=(SELLER.identity,))
SITE = Ed25519Signer(b"\x52" * 32)
_SITE_ID = "site-test"
_RESERVATION = "fixture-admin-reach-reservation"


# -- the administrator's advance -----------------------------------------------


async def test_an_administrators_advance_is_recorded_as_the_administrators(client):
    admin, db = client
    await _seed_order(db, "ord-admin-advance")
    await _seed_thread(db, "neg-admin-advance", "ord-admin-advance")

    advanced = await admin.advance_negotiation(
        "ord-admin-advance", "neg-admin-advance", action="exit", reason="operator_decision"
    )
    detail = await admin.get_negotiation("ord-admin-advance", "neg-admin-advance")

    assert advanced.action == "exit"
    last = detail.messages[-1]
    assert (last.sender_role, last.sender_principal) == (
        "admin",
        _NEGOTIATIONS_ADMIN.identity,
    )
    assert detail.buyer_principal != _NEGOTIATIONS_ADMIN.identity


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


def _lease_ended_report() -> dict:
    """A site's signed report that the reservation's lease ended."""
    event = LeaseEndedEvent(
        event_id="fixture-admin-reach-end", capacity_reservation_id=_RESERVATION,
        site_id=_SITE_ID, effective_at=1_800_000_000, cause="force_release",
        source_state="leased", reason="development failure", caller=SITE.identity,
    )
    return sign_lease_end(event, SITE).model_dump(mode="json")


PARTY_ROUTES = (
    PartyRoute("POST", "/api/v1/listings/create", "seller", "create_listing", "", {}),
    PartyRoute(
        "POST", "/api/v1/listings/{listing_id}/close", "seller", "close_listing", LISTING
    ),
    PartyRoute(
        "POST", "/api/v1/listings/{listing_id}/refund", "seller", "refund_listing",
        LISTING, {"buyer_principal": _ADMIN_AS_PARTY},
    ),
    PartyRoute(
        "POST", "/api/v1/listings/{listing_id}/claim", "seller", "claim_listing",
        LISTING, {"claimant_principal": _ADMIN_AS_PARTY},
    ),
    PartyRoute(
        "POST", "/api/v1/listings/{listing_id}/arbitrate", "seller", "arbitrate_listing",
        LISTING, {},
    ),
    PartyRoute(
        "POST", "/api/v1/listings/{listing_id}/reclaim", "buyer", "reclaim_listing",
        LISTING, {"payer_principal": _ADMIN_AS_PARTY},
    ),
    PartyRoute(
        "POST", "/api/v1/negotiate/new", "buyer", "negotiate_new", LISTING,
        {
            "listing_id": LISTING,
            "buyer_principal": _ADMIN_AS_PARTY,
            "provision_terms": ProvisionTerms(
                kind="vm.v1", version=1, payload={}
            ).model_dump(mode="json"),
        },
    ),
    PartyRoute(
        "POST", "/api/v1/negotiate/{neg_id}", "buyer", "negotiate_continue",
        NEGOTIATION, {"action": "exit", "buyer_principal": _ADMIN_AS_PARTY},
    ),
    PartyRoute(
        "POST", "/api/v1/settle/{escrow_uid}", "buyer", "settle_escrow", NEGOTIATION,
        {"negotiation_id": NEGOTIATION, "buyer_principal": _ADMIN_AS_PARTY},
    ),
    PartyRoute(
        "GET", "/api/v1/settle/{escrow_uid}/status", "buyer", "settle_status",
        NEGOTIATION,
    ),
    PartyRoute(
        "POST", "/api/v1/settlements/{negotiation_id}/refund", "seller",
        "refund_settlement", NEGOTIATION,
    ),
    PartyRoute(
        "POST", "/api/v1/deals/{escrow_uid}/heartbeat", "buyer", "deal_heartbeat",
        NEGOTIATION,
        {"buyer_principal": _ADMIN_AS_PARTY, "seller_principal": SELLER.identity.model_dump(mode="json")},
    ),
    PartyRoute(
        "POST", "/api/v1/admin/fulfillment/events/capacity-released", "service",
        "fulfillment_capacity_released", _RESERVATION,
        {"capacity_reservation_id": _RESERVATION, "site_id": _SITE_ID},
    ),
    PartyRoute(
        "POST", "/api/v1/capacity/reservations/{capacity_reservation_id}/lease-ended",
        "service", "lease_ended", _RESERVATION, _lease_ended_report(),
    ),
)

#: Party routes swept against an accepted introduction below, since only a
#: deal settled by contact exchange reaches their authentication.
INTRODUCTION_ROUTES = frozenset(
    {("POST", "/api/v1/introductions"), ("GET", "/api/v1/introductions/{obligation_ref}")}
)

#: The buyer's lifecycle routes, mounted from the deal-servicing kit and held
#: there: `kit/deal-servicing/tests/integration/test_routes.py`.
KIT_PARTY_ROUTES = frozenset(
    {
        ("POST", "/api/v1/negotiations/{negotiation_id}/lifecycle"),
        ("GET", "/api/v1/negotiations/{negotiation_id}/lifecycle"),
    }
)

#: The administrator's own routes. System status also admits a configured
#: site's service read.
ADMINISTRATOR_ROUTES = frozenset(
    {
        ("GET", "/api/v1/system/status"),
        ("GET", "/api/v1/system/events"),
        ("POST", "/api/v1/admin/identity/rotations"),
        ("GET", "/api/v1/admin/identity/status"),
        ("POST", "/api/v1/admin/identity/retirements"),
        ("POST", "/api/v1/admin/pause"),
        ("POST", "/api/v1/admin/resume"),
        ("POST", "/api/v1/admin/portfolio/reservations"),
        ("POST", "/api/v1/admin/portfolio/release-reservations"),
        ("POST", "/api/v1/admin/deals/{escrow_uid}/interrupt"),
        ("DELETE", "/api/v1/admin/introductions/{obligation_ref}/payloads"),
        ("POST", "/api/v1/admin/lifecycle/pause"),
        ("POST", "/api/v1/admin/lifecycle/resume"),
        ("POST", "/api/v1/admin/lifecycle/{loop}/run-cycle"),
        ("POST", "/api/v1/admin/lifecycle/{loop}/dry-run"),
        ("POST", "/api/v1/admin/capacity/projections/refresh"),
        ("PUT", "/api/v1/admin/pool-overrides"),
        ("GET", "/api/v1/admin/pool-overrides"),
        ("DELETE", "/api/v1/admin/pool-overrides"),
        ("POST", "/api/v1/listings/{listing_id}/pause"),
        ("POST", "/api/v1/listings/{listing_id}/resume"),
        ("POST", "/api/v1/admin/listings/{listing_id}/evaluate-negotiate"),
        ("GET", "/api/v1/listings/{listing_id}/negotiations"),
        ("GET", "/api/v1/listings/{listing_id}/negotiations/{neg_id}"),
        ("POST", "/api/v1/listings/{listing_id}/negotiations/{neg_id}/advance"),
        ("POST", "/api/v1/listings/{listing_id}/negotiations/{neg_id}/force-accept"),
        ("POST", "/api/v1/admin/settle/{escrow_uid}/verify"),
        ("POST", "/api/v1/admin/settle/{escrow_uid}/evaluate"),
        ("GET", "/api/v1/admin/settle/{escrow_uid}/wait"),
        ("GET", "/api/v1/admin/lifecycle"),
        ("POST", "/api/v1/admin/lifecycle/{negotiation_id}"),
        ("GET", "/api/v1/admin/lifecycle/{negotiation_id}"),
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


def test_every_mounted_route_is_classified_once():
    """Each route the storefront serves is a party, administrator or public
    route, so a new route is placed here, and a party route swept, before it
    ships."""
    party = {(route.method, route.path) for route in PARTY_ROUTES}
    classes = (
        party, INTRODUCTION_ROUTES, KIT_PARTY_ROUTES, ADMINISTRATOR_ROUTES, PUBLIC_ROUTES
    )
    mounted = _mounted(server.app)

    assert mounted - set().union(*classes) == set()
    assert party | INTRODUCTION_ROUTES | KIT_PARTY_ROUTES <= mounted
    assert sum(len(group) for group in classes) == len(set().union(*classes))


@pytest.fixture
async def storefront(payment_rig, monkeypatch):  # noqa: F811 - the imported fixture
    """The storefront's party routers and its three authentication middlewares,
    in production's order, over a settled payments deal; ``ADMIN`` is its one
    active administrator, and the site's service peer is trusted."""
    rig = await payment_rig()
    await rig.settle()
    await rig.delivered()
    monkeypatch.setattr(
        _admin_identity,
        "get_administrator_configs",
        lambda: {"integration-admin": ADMINISTRATORS},
    )
    _admin_identity.initialize_administrator_identities(rig.db.db_path)
    trust = ServicePeerTrust(rig.db.db_path, {
        "fixture-provisioner": ("service", _SITE_ID, TrustedIdentitySet(identities=(SITE.identity,))),
    })
    trust.seed()
    monkeypatch.setattr(_container, "resolved_service_peer_trust", trust)
    app = FastAPI()
    for router in (
        server.admin_router,
        server.listings_router,
        server.negotiate_router,
        server.settle_router,
        server.settlements_router,
        server.deals_router,
        server.lease_reports_router,
    ):
        app.include_router(router)
    for middleware in (
        listing_lifecycle_middleware,
        service_peer_callback_middleware,
        _admin_identity.administrator_identity_middleware,
    ):
        app.middleware("http")(middleware)
    yield app, rig


@pytest.mark.parametrize("route", PARTY_ROUTES, ids=lambda route: route.id)
async def test_a_party_route_refuses_the_administrator(storefront, route):
    """Signed under ``admin`` by the active administrator, naming the
    administrator as the party where the body names one: refused, no
    negotiation opened and the deal's thread unchanged.

    A rejection-path test: the typed client signs a party's request only under
    that party's role, so the request is sent through its generic signed
    request, and only its status is asserted."""
    app, rig = storefront
    path = (
        route.path.replace("{listing_id}", LISTING)
        .replace("{neg_id}", NEGOTIATION)
        .replace("{escrow_uid}", NEGOTIATION)
        .replace("{negotiation_id}", NEGOTIATION)
        .replace("{capacity_reservation_id}", _RESERVATION)
    )
    before = await rig.db.load_negotiation_thread_row(negotiation_id=NEGOTIATION)
    threads = _thread_count(rig.db.db_path)

    async with StorefrontClient(
        "http://test", signer=ADMIN_SIGNER, caller_role="admin",
        expected_publishers=_PUBLISHERS, transport=httpx.ASGITransport(app=app),
    ) as admin:
        with pytest.raises(StorefrontClientError) as refused:
            await admin.authenticated_request(
                route.method, path, role="admin", operation=route.operation,
                resource=route.resource, body=route.body,
            )

    assert refused.value.status_code in {401, 403}, refused.value
    assert await rig.db.load_negotiation_thread_row(negotiation_id=NEGOTIATION) == before
    assert _thread_count(rig.db.db_path) == threads


def _thread_count(db_path: str) -> int:
    with sqlite3.connect(db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM negotiation_threads").fetchone()[0]


async def test_the_introduction_routes_refuse_the_administrator(tmp_path, monkeypatch):
    """An accepted introduction's start and its read once the buyer has
    started it, each signed under ``admin`` by the storefront's active
    administrator over the party's own operation and resource: refused, and the
    administrator's start reveals nothing. Rejection-path requests, sent
    through the typed client's generic signed request; only their status is
    asserted."""
    monkeypatch.setattr(
        _admin_identity,
        "get_administrator_configs",
        lambda: {"integration-admin": ADMINISTRATORS},
    )
    async with publication_app(
        tmp_path,
        mechanism_fulfillment=CONTACT_PUBLISHABLE,
        contacts={SITE_A: SITE_CONTACTS[SITE_A]},
    ) as world:
        _admin_identity.initialize_administrator_identities(world.db.db_path)
        world.pools.append(pool("broker-a", backing="unbacked"))
        await offer_introduction(world, SITE_A, "broker-a")
        listing = (await publish(world))["broker-a"]
        negotiation_id, obligation_ref = await accept_introduction(world, listing)
        start = {
            "negotiation_id": negotiation_id,
            "obligation_ref": obligation_ref,
            "contact_payload": {"email": "administrator@example.com"},
        }
        with serving(world.app) as base_url:
            async with StorefrontClient(
                base_url, signer=ADMIN_SIGNER, caller_role="admin",
                expected_publishers=TrustedIdentitySet(
                    identities=(TEST_MARKETPLACE_SIGNER.identity,)
                ),
            ) as admin:
                with pytest.raises(StorefrontClientError) as started:
                    await admin.authenticated_request(
                        "POST", "/api/v1/introductions", role="admin",
                        operation="introduction_start", resource=obligation_ref,
                        body=start,
                    )
                # A reveal is read only once its buyer has started it.
                revealed = introduction_transport(base_url).start(
                    negotiation_id=negotiation_id,
                    obligation_ref=obligation_ref,
                    contact_payload=dict(BUYER_CONTACT),
                )
                with pytest.raises(StorefrontClientError) as read:
                    await admin.authenticated_request(
                        "GET", f"/api/v1/introductions/{obligation_ref}", role="admin",
                        operation="introduction_read", resource=obligation_ref,
                    )

    assert (started.value.status_code, read.value.status_code) == (403, 403)
    # The buyer's start was the first: the administrator's revealed nothing.
    assert revealed["counterparty_contact"] == SITE_CONTACTS[SITE_A]
