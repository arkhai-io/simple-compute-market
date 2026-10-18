"""A site's trust follows its service peer's rotation, through the running app.

Application integration: the real app and its lifespan, composed from the
configuration files by the production root -- which seeds the site's service
peer into durable identity state -- with only the site authority's transport
replaced by a double signing as a principal the test chooses. Every call goes
through the canonical storefront client: the rotation and its completion
through the administrator's identity routes, response verification observed
through a pool-override write (whose live check reads the site's projection
through the site's client), and callbacks through the site's own client.

Every key is a development fixture, never used on a public network.
"""

from __future__ import annotations

import sqlite3
import time

import httpx
import pytest
from core_storefront.identity_authority import SERVICE_PEER_AUTHORITY
from market_identity import Eip191Signer, RotationIntent, TrustedIdentitySet, sign_rotation
from market_pool_overrides import PoolOverrideClient
from storefront_client import StorefrontClient
from storefront_client.client import StorefrontClientError

from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.runtime import build_runtime_from_configuration
from arkhai_bare_metal_storefront.server import (
    build_bare_metal_storefront_app,
    build_bare_metal_storefront_registry,
)
from signed_sites import SignedSite, SignedSites
from storefront_configuration import (
    ADMIN,
    SELLER,
    SELLER_CREDENTIAL,
    SITE,
    SITE_ID,
    publishable_configuration,
    write_configuration,
)

pytestmark = pytest.mark.asyncio

# The replacement for the site's principal; a development key.
SITE_NEXT = Eip191Signer(bytes.fromhex("46" * 32))
PEER = "site_a_authority"
NONCE = "rotate-site-a-1"
OVERLAP_SECONDS = 600
RESERVATION = "reservation-1"


def _client(app, signer, role: str) -> StorefrontClient:
    return StorefrontClient(
        "http://seller",
        signer=signer,
        caller_role=role,
        expected_publishers=TrustedIdentitySet(identities=(SELLER.identity,)),
        transport=httpx.ASGITransport(app=app),
    )


def _rotation(expires_at: int):
    return sign_rotation(
        current_signer=SITE,
        replacement_signer=SITE_NEXT,
        intent=RotationIntent(
            current=SITE.identity,
            replacement=SITE_NEXT.identity,
            subject=PEER,
            authority=SERVICE_PEER_AUTHORITY,
            nonce=NONCE,
            overlap_seconds=OVERLAP_SECONDS,
            expires_at=expires_at,
        ),
    )


async def _responses_verify(admin, site: SignedSite, signer: Eip191Signer) -> bool:
    """Whether the site's answer, signed by ``signer``, verifies: a pool-override
    write is accepted only when the live projection it checks against does."""
    site.signer = signer
    try:
        await PoolOverrideClient(admin).put_pool_override(
            {
                "site_id": SITE_ID,
                "pool_id": "pool-a",
                "offering_mode": "bare_metal",
                "terms": {"max_duration_seconds": 3600},
            }
        )
    except StorefrontClientError as exc:
        assert exc.status_code == 503 and "did not verify" in str(exc), exc
        return False
    return True


async def _callback_applied(app, signer: Eip191Signer) -> bool:
    """Whether the site's capacity-released callback, signed by ``signer``, is
    authenticated and applied."""
    async with _client(app, signer, "service") as site:
        try:
            released = await site.notify_capacity_released(RESERVATION, site_id=SITE_ID)
        except StorefrontClientError as exc:
            assert exc.status_code == 403, exc
            return False
    assert released == {"capacity_reservation_id": RESERVATION, "state": "released"}
    return True


def _a_deal_holding_the_reservation(db_path: str) -> None:
    """Service-internal setup: a deal whose fulfillment holds the site's
    reservation, which only a settled deal reaches through the API."""
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO bare_metal_fulfillment_lifecycle("
            "negotiation_id, settlement_ref, site_id, physical_resource_id, "
            "capacity_reservation_id, state) VALUES (?, ?, ?, ?, ?, 'terminating')",
            ("negotiation-1", "escrow-1", SITE_ID, "resource-1", RESERVATION),
        )


async def test_a_rotation_through_the_routes_moves_responses_and_callbacks(
    monkeypatch, tmp_path
) -> None:
    """Spec scenario "A site's responses follow its rotation"."""
    database = tmp_path / "storefront.db"
    write_configuration(monkeypatch, tmp_path, publishable_configuration(database))
    site = SignedSite(SITE)
    sites = SignedSites({"site-a.test": site})
    domain = get_market_domain_contract()
    app = build_bare_metal_storefront_app(
        registry=build_bare_metal_storefront_registry(domain=domain),
        runtime_factory=lambda: build_runtime_from_configuration(
            credential=SELLER_CREDENTIAL, domain=domain, site_clients=sites.factories()
        ),
    )

    async with app.router.lifespan_context(app):
        _a_deal_holding_the_reservation(str(database))
        async with _client(app, ADMIN, "admin") as admin:
            # Startup seeded the configured peer: its principal alone verifies.
            assert await _responses_verify(admin, site, SITE)
            assert not await _responses_verify(admin, site, SITE_NEXT)

            expires_at = int(time.time()) + 300
            await admin.admin_initiate_identity_rotation(
                authority=SERVICE_PEER_AUTHORITY,
                subject=PEER,
                current_signer=SITE,
                replacement_signer=SITE_NEXT,
                nonce=NONCE,
                overlap_seconds=OVERLAP_SECONDS,
                expires_at=expires_at,
            )
            during = await admin.admin_get_identity_status(
                authority=SERVICE_PEER_AUTHORITY, subject=PEER
            )
            # During the overlap either principal verifies.
            assert await _responses_verify(admin, site, SITE_NEXT)
            assert await _responses_verify(admin, site, SITE)

            await admin.admin_complete_identity_rotation(rotation=_rotation(expires_at))
            after = await admin.admin_get_identity_status(
                authority=SERVICE_PEER_AUTHORITY, subject=PEER
            )
            # The overlap has ended: only the replacement verifies, with no
            # configuration change and no restart.
            assert await _responses_verify(admin, site, SITE_NEXT)
            assert not await _responses_verify(admin, site, SITE)

        # Callbacks verify against the same principals.
        assert not await _callback_applied(app, SITE)
        assert await _callback_applied(app, SITE_NEXT)

    assert during.primary == SITE_NEXT.identity
    assert {
        binding.principal.identifier for binding in during.bindings if binding.active
    } == {SITE.identity.identifier, SITE_NEXT.identity.identifier}
    assert [
        binding.principal.identifier for binding in after.bindings if binding.active
    ] == [SITE_NEXT.identity.identifier]
