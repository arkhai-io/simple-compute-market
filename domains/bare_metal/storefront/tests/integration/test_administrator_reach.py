"""The bare-metal storefront's administrator: admitted as itself, never as a party.

On every route that binds its caller to a deal as a party -- a buyer's, the
seller's own counterparty routes, a site's callbacks -- a request signed under
the ``admin`` role by an active administrator principal, over the operation and
resource that party's client signs and a body the route reads up to its
authentication, is refused. The administrator reads a
listing's negotiations through the canonical storefront client. The storefront
serves no advance route; its administrator acts on a negotiation by
force-accepting it, the route passing the authenticated administrator as the
actor, whose acceptance the negotiation runtime records under its role
(`kit/negotiation-runtime`'s administrative acceptance tests); no test here
force-accepts.
The lifecycle routes the storefront mounts from the deal-servicing kit are held
by that kit's own tests; the lease-ready evidence read is a record of the
storefront's own deals, which its administrator may read.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field, replace
from typing import Any

import httpx
import pytest
from market_core.schemas import ProvisionTerms
from market_identity import EMPTY_BODY, Eip191Signer, TrustedIdentitySet
from storefront_client import StorefrontClient, StorefrontClientError

from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.server import (
    build_bare_metal_storefront_app,
    build_bare_metal_storefront_registry,
)
from held_loops import held_loop_controller
from loopback import serving
from site_trust import seeded_sites
from test_http_introductions import (
    _accept_typed,
    _insert_contact_listing,
    _introductions,
)
from test_http_introductions import _app as _introduction_app
from test_http_introductions import _runtime as _introduction_runtime
from test_http_settlement import (
    ADMIN_SIGNER,
    BUYER_SIGNER,
    SELLER_SIGNER,
    SITE_SIGNER,
    _accepted_runtime,
    _app,
)

ADMIN = ADMIN_SIGNER.identity
_ADMIN_AS_BUYER = ADMIN.model_dump(mode="json")
_PUBLISHERS = TrustedIdentitySet(identities=(SELLER_SIGNER.identity,))
_LISTING = "listing-1"
_SITE = "site-a"
_RESERVATION = "reservation-admin-reach"


def _client(app_or_url, signer: Eip191Signer, role: str) -> StorefrontClient:
    if isinstance(app_or_url, str):
        return StorefrontClient(
            app_or_url, signer=signer, caller_role=role, expected_publishers=_PUBLISHERS
        )
    return StorefrontClient(
        "http://seller",
        signer=signer,
        caller_role=role,
        expected_publishers=_PUBLISHERS,
        transport=httpx.ASGITransport(app=app_or_url),
    )


@pytest.fixture
async def storefront(tmp_path):
    """The production app over an accepted deal whose fulfillment holds a
    reservation at a site whose service peer the storefront trusts."""

    async def verifier(**_kwargs):
        return 1

    path = str(tmp_path / "storefront.db")
    runtime, negotiation_id = await _accepted_runtime(path, verifier)
    _bindings, trust = seeded_sites(path, {_SITE: SITE_SIGNER.identity})
    # The loops start held: no timer cycle touches the deal the sweep reads.
    runtime = replace(
        runtime, service_peer_trust=trust, loop_controller_factory=held_loop_controller
    )
    _hold_reservation(runtime, negotiation_id)
    app = _app(runtime)
    async with app.router.lifespan_context(app):
        yield app, runtime, negotiation_id


def _hold_reservation(runtime, negotiation_id: str) -> None:
    """Service-internal setup: the deal's fulfillment holding a reservation at
    the site, which only a delivered deal reaches through the API."""
    with sqlite3.connect(runtime.db.db_path) as conn:
        conn.execute(
            "INSERT INTO bare_metal_fulfillment_lifecycle("
            "negotiation_id, settlement_ref, site_id, physical_resource_id, "
            "capacity_reservation_id, state) VALUES (?, ?, ?, ?, ?, 'leased')",
            (negotiation_id, negotiation_id, _SITE, "resource-1", _RESERVATION),
        )


# -- the administrator's negotiation reads and controls ------------------------


async def test_the_administrator_reads_a_listings_negotiations_through_the_client(
    storefront,
):
    app, _runtime, negotiation_id = storefront

    async with _client(app, ADMIN_SIGNER, "admin") as admin:
        listed = await admin.list_negotiations(_LISTING)
        detail = await admin.get_negotiation(_LISTING, negotiation_id)

    assert negotiation_id in {thread.negotiation_id for thread in listed.negotiations}
    assert detail.negotiation_id == negotiation_id
    assert detail.buyer_principal == BUYER_SIGNER.identity


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


#: Replaced by the accepted deal's negotiation id.
_DEAL = "{deal}"

PARTY_ROUTES = (
    PartyRoute(
        "POST", "/api/v1/listings/{listing_id}/close", "seller", "close_listing", _LISTING
    ),
    PartyRoute(
        "POST", "/api/v1/negotiate/new", "buyer", "negotiate_new", _LISTING,
        {
            "listing_id": _LISTING,
            "buyer_principal": _ADMIN_AS_BUYER,
            "provision_terms": ProvisionTerms(
                kind="bare_metal.v2", version=1, payload={"duration_seconds": 3600}
            ).model_dump(mode="json"),
        },
    ),
    PartyRoute(
        "POST", "/api/v1/negotiate/{negotiation_id}", "buyer", "negotiate_continue",
        _DEAL, {"action": "exit", "buyer_principal": _ADMIN_AS_BUYER},
    ),
    PartyRoute(
        "POST", "/api/v1/settle/{escrow_uid}", "buyer", "settle_escrow", _DEAL,
        {"negotiation_id": _DEAL, "buyer_principal": _ADMIN_AS_BUYER},
    ),
    PartyRoute(
        "GET", "/api/v1/settle/{escrow_uid}/status", "buyer", "settle_status", _DEAL
    ),
    PartyRoute(
        "POST", "/api/v1/settlements/{negotiation_id}/refund", "seller",
        "refund_settlement", _DEAL,
    ),
    PartyRoute(
        "GET", "/api/v1/fulfillments/{negotiation_id}/status", "buyer",
        "bare_metal_fulfillment_status", _DEAL,
    ),
    PartyRoute(
        "GET", "/api/v1/fulfillments/{negotiation_id}/access", "buyer",
        "bare_metal_fulfillment_access", _DEAL,
    ),
    PartyRoute(
        "GET", "/api/v1/fulfillments/{negotiation_id}/result", "buyer",
        "bare_metal_fulfillment_result", _DEAL,
    ),
    PartyRoute(
        "POST", "/api/v1/admin/fulfillment/events/capacity-released", "service",
        "fulfillment_capacity_released", _RESERVATION,
        {"capacity_reservation_id": _RESERVATION, "site_id": _SITE},
    ),
    PartyRoute(
        "POST", "/api/v1/capacity/reservations/{capacity_reservation_id}/lease-ended",
        "service", "lease_ended", _RESERVATION, {"site_id": _SITE},
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

#: The storefront's records of its own deals, which its administrator reads.
DEAL_RECORDS = frozenset({("GET", "/api/v1/evidence/bare-metal/{evidence_digest}")})

#: The administrator's own routes. System status also admits a configured
#: site's service read.
ADMINISTRATOR_ROUTES = frozenset(
    {
        ("DELETE", "/api/v1/admin/introductions/{obligation_ref}/payloads"),
        ("POST", "/api/v1/listings/{listing_id}/pause"),
        ("POST", "/api/v1/listings/{listing_id}/resume"),
        ("POST", "/api/v1/admin/listings/{listing_id}/evaluate-negotiate"),
        ("POST", "/api/v1/listings/{listing_id}/negotiations/{negotiation_id}/force-accept"),
        ("GET", "/api/v1/system/events"),
        ("GET", "/api/v1/listings/{listing_id}/negotiations"),
        ("GET", "/api/v1/listings/{listing_id}/negotiations/{negotiation_id}"),
        ("GET", "/api/v1/system/status"),
        ("POST", "/api/v1/admin/settle/{escrow_uid}/verify"),
        ("POST", "/api/v1/admin/settle/{escrow_uid}/evaluate"),
        ("GET", "/api/v1/admin/settle/{escrow_uid}/wait"),
        ("POST", "/api/v1/admin/portfolio/reservations"),
        ("POST", "/api/v1/admin/deals/{negotiation_id}/interrupt"),
        ("POST", "/api/v1/admin/identity/rotations"),
        ("POST", "/api/v1/admin/identity/retirements"),
        ("GET", "/api/v1/admin/identity/status"),
        ("PUT", "/api/v1/admin/pool-overrides"),
        ("GET", "/api/v1/admin/pool-overrides"),
        ("DELETE", "/api/v1/admin/pool-overrides"),
        ("POST", "/api/v1/admin/pause"),
        ("POST", "/api/v1/admin/resume"),
        ("POST", "/api/v1/admin/lifecycle/pause"),
        ("POST", "/api/v1/admin/lifecycle/resume"),
        ("POST", "/api/v1/admin/lifecycle/{loop}/run-cycle"),
        ("POST", "/api/v1/admin/lifecycle/{loop}/dry-run"),
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
    """Each route the storefront serves is a party, administrator, deal-record
    or public route, so a new route is placed here, and a party route swept,
    before it ships."""
    party = {(route.method, route.path) for route in PARTY_ROUTES}
    classes = (
        party, INTRODUCTION_ROUTES, KIT_PARTY_ROUTES, DEAL_RECORDS,
        ADMINISTRATOR_ROUTES, PUBLIC_ROUTES,
    )
    mounted = _mounted(
        build_bare_metal_storefront_app(
            registry=build_bare_metal_storefront_registry(
                domain=get_market_domain_contract()
            )
        )
    )

    assert mounted - set().union(*classes) == set()
    assert party | INTRODUCTION_ROUTES | KIT_PARTY_ROUTES <= mounted
    assert sum(len(group) for group in classes) == len(set().union(*classes))


def _concrete(value: Any, deal: str) -> Any:
    if isinstance(value, str):
        return value.replace(_DEAL, deal)
    if isinstance(value, dict):
        return {key: _concrete(item, deal) for key, item in value.items()}
    return value


@pytest.mark.parametrize("route", PARTY_ROUTES, ids=lambda route: route.id)
async def test_a_party_route_refuses_the_administrator(storefront, route):
    """Signed under ``admin`` by the active administrator, naming the
    administrator as the buyer where the body names one: refused, no
    negotiation opened and the deal's thread unchanged.

    A rejection-path test: the typed client signs a party's request only under
    that party's role, so the request is sent through its generic signed
    request, and only its status is asserted."""
    app, runtime, deal = storefront
    path = (
        route.path.replace("{listing_id}", _LISTING)
        .replace("{negotiation_id}", deal)
        .replace("{escrow_uid}", deal)
        .replace("{capacity_reservation_id}", _RESERVATION)
    )
    before = await runtime.db.load_negotiation_thread_row(negotiation_id=deal)
    threads = _thread_count(runtime.db.db_path)

    async with _client(app, ADMIN_SIGNER, "admin") as admin:
        with pytest.raises(StorefrontClientError) as refused:
            await admin.authenticated_request(
                route.method,
                path,
                role="admin",
                operation=route.operation,
                resource=_concrete(route.resource, deal),
                body=_concrete(route.body, deal),
            )

    assert refused.value.status_code in {401, 403}, refused.value
    assert await runtime.db.load_negotiation_thread_row(negotiation_id=deal) == before
    assert _thread_count(runtime.db.db_path) == threads


def _thread_count(db_path: str) -> int:
    with sqlite3.connect(db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM negotiation_threads").fetchone()[0]


async def test_the_introduction_routes_refuse_the_administrator(tmp_path):
    """An accepted introduction's start and its read once the buyer has
    started it, each signed under ``admin`` by the active administrator over the
    party's own operation and resource: refused, and the administrator's start
    reveals nothing. Rejection-path requests, sent through the typed client's
    generic signed request; only their status is asserted."""
    runtime = _introduction_runtime(str(tmp_path / "storefront.db"))
    option = await _insert_contact_listing(runtime)
    app = _introduction_app(runtime)
    with serving(app) as base_url:
        negotiation_id, obligation_ref = await _accept_typed(base_url, option)
        start = {
            "negotiation_id": negotiation_id,
            "obligation_ref": obligation_ref,
            "contact_payload": {"email": "administrator@example.com"},
        }
        async with _client(base_url, ADMIN_SIGNER, "admin") as admin:
            with pytest.raises(StorefrontClientError) as started:
                await admin.authenticated_request(
                    "POST", "/api/v1/introductions", role="admin",
                    operation="introduction_start", resource=obligation_ref, body=start,
                )
            unrevealed = await runtime.settlement_runtime.get_status(negotiation_id)
            # A reveal is read only once its buyer has started it.
            _introductions(base_url).start(
                negotiation_id=negotiation_id,
                obligation_ref=obligation_ref,
                contact_payload={"email": "buyer@example.com"},
            )
            with pytest.raises(StorefrontClientError) as read:
                await admin.authenticated_request(
                    "GET", f"/api/v1/introductions/{obligation_ref}", role="admin",
                    operation="introduction_read", resource=obligation_ref,
                )

    assert (started.value.status_code, read.value.status_code) == (403, 403)
    assert unrevealed.status != "complete"
