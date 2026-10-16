"""Each site's responses verify against its own service peer, through its rotation.

The capacity runtime is the one ``build_capacity_runtime_for`` composes, its
site clients given each site's provider of its peer's active principals, with
only the transport replaced by the in-process fake site. The trust is the one
the lifespan seeds and the container holds. An operator rotates a site's peer
through the administrator identity routes with the typed client; the runtime is
not rebuilt and the storefront is not restarted.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
import pytest
from core_storefront.identity_authority import SERVICE_PEER_AUTHORITY
from core_storefront.service_peers import ServicePeerTrust
from fastapi import FastAPI
from market_identity import (
    Ed25519Signer,
    RotationIntent,
    TrustedIdentitySet,
    sign_rotation,
)
from market_site_client import SiteCapacityClient
from market_site_client.client import SiteCapacityAuthenticationError
from storefront_client.client import StorefrontClient

import market_storefront.container as container
from market_storefront.controllers.admin_controller import router as admin_router
from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    build_vm_storefront_registry,
)
from market_storefront.middleware.admin_identity import (
    administrator_identity_middleware,
    initialize_administrator_identities,
)
from market_storefront.services import capacity_client
from market_storefront.utils.sqlite_client import SQLiteClient
from tests._settings_overrides import settings_overrides
from tests.fake_site import FakeSite
from tests.publication_app import _replaced_setting

pytestmark = pytest.mark.asyncio

# Deterministic development keys; never used on a public network.
_STOREFRONT = Ed25519Signer(b"\x81" * 32)
_ADMIN = Ed25519Signer(b"\x82" * 32)
_HOME = Ed25519Signer(b"\x83" * 32)
_HOME_NEXT = Ed25519Signer(b"\x84" * 32)
_AWAY = Ed25519Signer(b"\x85" * 32)
_NONCE = "rotate-home-1"
_OVERLAP_SECONDS = 600


def _pins(signer: Ed25519Signer) -> TrustedIdentitySet:
    return TrustedIdentitySet(identities=(signer.identity,))


@dataclass
class World:
    admin: StorefrontClient
    runtime: capacity_client.CapacityRuntime
    sites: dict[str, FakeSite]


@pytest.fixture
async def world(tmp_path) -> AsyncIterator[World]:
    db = SQLiteClient(
        db_path=str(tmp_path / "storefront.db"),
        registry=build_vm_storefront_registry(build_vm_storefront_domain()),
    )
    sites = {"home": FakeSite(), "away": FakeSite()}
    sites["home"].signer = _HOME
    sites["away"].signer = _AWAY
    trust = ServicePeerTrust(
        db.db_path,
        {
            "home-peer": ("service", "home", _pins(_HOME)),
            "away-peer": ("service", "away", _pins(_AWAY)),
        },
    )
    trust.seed()
    saved = {
        name: getattr(container, name)
        for name in (
            "resolved_domain_registry",
            "resolved_sqlite_client",
            "resolved_marketplace_signer",
            "resolved_service_peer_trust",
        )
    }
    container.resolved_domain_registry = db.domain_registry
    container.resolved_sqlite_client = db
    container.resolved_marketplace_signer = _STOREFRONT
    container.resolved_service_peer_trust = trust
    capacity_client._capacity_runtime_state.update(key=None, runtime=None)

    def site_client(site, signer):
        return SiteCapacityClient(
            site.url,
            signer=signer,
            expected_authorities=site.expected_authorities,
            transport=sites[site.site_id].transport(),
        )

    try:
        with settings_overrides(
            **{
                "identity.administrators": {
                    "operator": {
                        "principals": [_ADMIN.identity.model_dump(mode="json")]
                    }
                }
            }
        ), _replaced_setting(
            # Replaced at its root, so no site another test configured remains.
            "capacity",
            {
                "placement": "fill_first",
                "sites": {"home": "http://home-site:8081", "away": "http://away-site:8081"},
            },
        ):
            initialize_administrator_identities(db.db_path)
            runtime = capacity_client.build_capacity_runtime_for(
                lambda: db,
                signer=_STOREFRONT,
                service_peer_trust=trust,
                site_client_factory=site_client,
            )
            app = FastAPI()
            app.include_router(admin_router)
            app.middleware("http")(administrator_identity_middleware)
            async with StorefrontClient(
                "http://test",
                transport=httpx.ASGITransport(app=app),
                signer=_ADMIN,
                caller_role="admin",
                expected_publishers=_pins(_STOREFRONT),
            ) as admin:
                yield World(admin=admin, runtime=runtime, sites=sites)
    finally:
        capacity_client._capacity_runtime_state.update(key=None, runtime=None)
        for name, value in saved.items():
            setattr(container, name, value)


async def _verifies(world: World, site_id: str, signer: Ed25519Signer) -> bool:
    """Whether the site's answer, signed by ``signer``, verifies."""
    world.sites[site_id].signer = signer
    try:
        await world.runtime.site_client(site_id).snapshot()
    except SiteCapacityAuthenticationError:
        return False
    return True


def _rotation(expires_at: int):
    return sign_rotation(
        current_signer=_HOME,
        replacement_signer=_HOME_NEXT,
        intent=RotationIntent(
            current=_HOME.identity,
            replacement=_HOME_NEXT.identity,
            subject="home-peer",
            authority=SERVICE_PEER_AUTHORITY,
            nonce=_NONCE,
            overlap_seconds=_OVERLAP_SECONDS,
            expires_at=expires_at,
        ),
    )


async def test_a_sites_responses_follow_its_rotation(world: World):
    assert await _verifies(world, "home", _HOME)
    assert not await _verifies(world, "home", _HOME_NEXT)

    expires_at = int(time.time()) + 300
    await world.admin.admin_initiate_identity_rotation(
        authority=SERVICE_PEER_AUTHORITY,
        subject="home-peer",
        current_signer=_HOME,
        replacement_signer=_HOME_NEXT,
        nonce=_NONCE,
        overlap_seconds=_OVERLAP_SECONDS,
        expires_at=expires_at,
    )
    # During the overlap either principal verifies.
    assert await _verifies(world, "home", _HOME_NEXT)
    assert await _verifies(world, "home", _HOME)

    await world.admin.admin_complete_identity_rotation(rotation=_rotation(expires_at))
    # The overlap has ended: only the replacement verifies, with the same
    # runtime and clients, nothing reconfigured or restarted.
    assert await _verifies(world, "home", _HOME_NEXT)
    assert not await _verifies(world, "home", _HOME)
    # The other site's trust is its own peer's, untouched by the rotation.
    assert await _verifies(world, "away", _AWAY)


async def test_one_sites_principal_does_not_verify_anothers_responses(world: World):
    assert await _verifies(world, "home", _HOME)
    assert await _verifies(world, "away", _AWAY)
    assert not await _verifies(world, "home", _AWAY)
    assert not await _verifies(world, "away", _HOME)
