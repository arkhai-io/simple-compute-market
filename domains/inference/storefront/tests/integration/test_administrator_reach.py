"""The inference storefront's administrator: admitted as itself, never as a party.

The administrator reads a listing's negotiations and drives a round only
through its own operations, which the canonical storefront client signs and the
storefront verifies; the round is recorded as the administrator's. On every
route that binds its caller to a deal as a party, a request signed under the
``admin`` role by an active administrator principal, over the operation and
resource that party signs, is refused. The storefront is the real app through
its lifespan, over the scripted chain and authority.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from arkhai_api_selling.publish_route import (
    PUBLISH_FROM_QUOTA_OPERATION,
    PUBLISH_FROM_QUOTA_PATH,
    seller_resource,
)
from market_identity import EMPTY_BODY
from storefront_client.client import StorefrontClientError

from inference_storefront import container
from tests._settings_overrides import settings_overrides
from tests.integration.conftest import ADMIN_SIGNER, SELLER_SIGNER
from tests.integration.deal_parties import (
    BUYER_SIGNER,
    QUANTITY,
    Parties,
    ScriptedChain,
    open_negotiation,
    provision_terms,
    publish_request,
    running,
)
from tests.integration.issuance_authority import ScriptedAuthority

ADMIN = ADMIN_SIGNER.identity
BUYER = BUYER_SIGNER.identity


@dataclass
class Countered:
    parties: Parties
    listing_id: str
    negotiation_id: str


@asynccontextmanager
async def countered(monkeypatch) -> AsyncIterator[Countered]:
    """The storefront with one listing and a negotiation the bisection policy
    counters, opened by the buyer a sixth below the listing's price."""
    with settings_overrides(**{"negotiation.policies": ["bisection"]}):
        async with running(monkeypatch, ScriptedChain(), ScriptedAuthority()) as parties:
            listing = await parties.public.get_listing(
                (await parties.listings.publish_from_quota(publish_request(3))).listing_id
            )
            opened = await open_negotiation(parties, listing, amount=QUANTITY * 5 // 6)
            assert opened["action"] == "counter"
            yield Countered(parties, listing.listing_id, opened["negotiation_id"])


async def _threads(listing_id: str) -> list[dict[str, Any]]:
    return await container.resolved_sqlite_client.list_negotiations_for_listing(
        listing_id=listing_id, terminal_state=None, buyer_principal=None, limit=200, offset=0
    )


# -- the administrator's negotiation reads and controls ------------------------


async def test_the_administrator_reads_a_listings_negotiations_through_the_client(
    storefront, registries, monkeypatch
):
    async with countered(monkeypatch) as deal:
        admin = deal.parties.admin
        listed = await admin.list_negotiations(deal.listing_id)
        filtered = await admin.list_negotiations(
            deal.listing_id, buyer_principal=ADMIN, terminal_state="success"
        )
        detail = await admin.get_negotiation(deal.listing_id, deal.negotiation_id)

    assert [thread.negotiation_id for thread in listed.negotiations] == [deal.negotiation_id]
    assert filtered.negotiations == []
    assert detail.negotiation_id == deal.negotiation_id
    assert detail.buyer_principal == BUYER
    assert [message.sender_role for message in detail.messages] == ["buyer", "seller"]


async def test_negotiation_reads_are_refused_unsigned_and_signed_by_a_buyer(
    storefront, registries, monkeypatch
):
    async with countered(monkeypatch) as deal:
        listing = f"/api/v1/listings/{deal.listing_id}/negotiations"
        detail_path = f"{listing}/{deal.negotiation_id}"
        # Rejection-path tests: the typed client signs every read as the
        # administrator, so an unsigned read is sent raw and a buyer's through
        # the client's generic signed request; only their status is asserted.
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=deal.parties.app), base_url="http://seller"
        ) as unsigned:
            unsigned_list = await unsigned.get(listing)
            unsigned_detail = await unsigned.get(detail_path)
        with pytest.raises(StorefrontClientError) as listed:
            await deal.parties.buyer.authenticated_request(
                "GET",
                listing,
                role="buyer",
                operation="admin_list_negotiations",
                resource=f"{deal.listing_id}/negotiations?limit=50&offset=0",
                params={"limit": 50, "offset": 0},
            )
        with pytest.raises(StorefrontClientError) as read:
            await deal.parties.buyer.authenticated_request(
                "GET",
                detail_path,
                role="buyer",
                operation="admin_get_negotiation",
                resource=f"{deal.listing_id}/negotiations/{deal.negotiation_id}",
            )

    assert (unsigned_list.status_code, unsigned_detail.status_code) == (401, 401)
    assert listed.value.status_code in {401, 403}
    assert read.value.status_code in {401, 403}


async def test_an_administrators_advance_is_recorded_as_the_administrators(
    storefront, registries, monkeypatch
):
    async with countered(monkeypatch) as deal:
        admin = deal.parties.admin
        advanced = await admin.advance_negotiation(
            deal.listing_id, deal.negotiation_id, action="exit", reason="operator_decision"
        )
        detail = await admin.get_negotiation(deal.listing_id, deal.negotiation_id)

    assert advanced.action == "exit"
    assert detail.terminal_state == "failure"
    last = detail.messages[-1]
    assert (last.sender_role, last.sender_principal) == ("admin", ADMIN)
    assert BUYER not in {
        message.sender_principal for message in detail.messages if message.sender_role == "admin"
    }


async def test_a_negotiation_list_query_the_signature_does_not_cover_is_refused(
    storefront, registries, monkeypatch
):
    """Rejection-path tests: queries the typed client never builds, each
    answered before anything is read; only their status is asserted."""
    async with countered(monkeypatch) as deal:
        listing = f"/api/v1/listings/{deal.listing_id}/negotiations"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=deal.parties.app), base_url="http://seller"
        ) as unsigned:
            unknown = await unsigned.get(listing, params={"status": "open"})
            repeated = await unsigned.get(f"{listing}?limit=5&limit=6")
        with pytest.raises(StorefrontClientError) as half_filter:
            await deal.parties.admin.authenticated_request(
                "GET", listing, role="admin", operation="admin_list_negotiations",
                resource=f"{deal.listing_id}/negotiations?buyer_scheme=ed25519&limit=50&offset=0",
                params={"buyer_scheme": "ed25519", "limit": 50, "offset": 0},
            )
        with pytest.raises(StorefrontClientError) as malformed:
            await deal.parties.admin.authenticated_request(
                "GET", listing, role="admin", operation="admin_list_negotiations",
                resource=(
                    f"{deal.listing_id}/negotiations?buyer_identifier=x"
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


# Replaced by the listing the test publishes and the thread it opens.
_LISTING = "{listing}"
_THREAD = "{thread}"

_ADMIN_AS_BUYER = ADMIN.model_dump(mode="json")

PARTY_ROUTES = (
    PartyRoute(
        "POST", PUBLISH_FROM_QUOTA_PATH, "seller", PUBLISH_FROM_QUOTA_OPERATION,
        seller_resource(SELLER_SIGNER.identity), {"resource_id": "svc-quota"},
    ),
    PartyRoute(
        "POST", "/api/v1/listings/{listing_id}/close", "seller", "close_listing", _LISTING,
    ),
    PartyRoute(
        "POST", "/api/v1/negotiate/new", "buyer", "negotiate_new", _LISTING,
        {
            "listing_id": _LISTING,
            "buyer_principal": _ADMIN_AS_BUYER,
            "provision_terms": provision_terms(),
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


def _mounted(app: Any) -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in app.routes
        if getattr(route, "path", None)
        for method in (getattr(route, "methods", None) or ())
        if method != "HEAD"
    }


async def test_every_mounted_route_is_a_party_administrator_or_public_route(
    storefront, registries, monkeypatch
):
    """Each route the storefront serves is classified once, so a new route is
    placed here, and a party route is swept below, before it ships."""
    party = {(route.method, route.path) for route in PARTY_ROUTES}
    async with running(monkeypatch, ScriptedChain(), ScriptedAuthority()) as parties:
        mounted = _mounted(parties.app)

    assert mounted - (party | ADMINISTRATOR_ROUTES | PUBLIC_ROUTES) == set()
    assert party <= mounted
    assert not party & ADMINISTRATOR_ROUTES and not party & PUBLIC_ROUTES


def _concrete(value: Any, listing: str, thread: str) -> Any:
    if isinstance(value, str):
        return value.replace(_LISTING, listing).replace(_THREAD, thread)
    if isinstance(value, dict):
        return {key: _concrete(item, listing, thread) for key, item in value.items()}
    return value


@pytest.mark.parametrize("route", PARTY_ROUTES, ids=lambda route: route.id)
async def test_a_party_route_refuses_the_administrator(storefront, registries, monkeypatch, route):
    """Signed under ``admin`` by the active administrator, over the operation
    and resource the party's own client signs and a body the route reads up to
    its authentication, naming the administrator as the buyer where the body
    names one: refused, and no negotiation is opened.

    A rejection-path test: the typed client signs a party's request only under
    that party's role, so the request is sent through its generic signed
    request, and only its status is asserted."""
    async with countered(monkeypatch) as deal:
        listing, thread = deal.listing_id, deal.negotiation_id
        path = (
            route.path.replace("{listing_id}", listing)
            .replace("{neg_id}", thread)
            .replace("{escrow_uid}", thread)
            .replace("{negotiation_id}", thread)
        )
        before = await _threads(listing)
        with pytest.raises(StorefrontClientError) as refused:
            await deal.parties.admin.authenticated_request(
                route.method,
                path,
                role="admin",
                operation=route.operation,
                resource=_concrete(route.resource, listing, thread),
                body=_concrete(route.body, listing, thread),
            )
        after = await _threads(listing)

    assert refused.value.status_code in {401, 403}, refused.value
    assert after == before
