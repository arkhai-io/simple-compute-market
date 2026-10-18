"""Each site's responses and callbacks verify against its own service peer,
through its rotation.

Application integration at the router level: the storefront's administrator
router behind both authentication middlewares, over the production capacity
runtime (``build_capacity_runtime_for``), fulfillment client
(``build_fulfillment_client``), projection state, and a seeded service-peer
trust, with only the sites' transports replaced by in-process fakes. The
storefront's lifespan does not run, because its startup steps reach a
provisioning service and the sites over the network; the trust is seeded here
as startup seeds it and injected through the container, as every other
collaborator is.

An operator rotates a site's peer through the administrator identity routes
with the typed client. The storefront then calls the site as it does in
operation -- a ``site-projections`` cycle polls it, and a fulfillment status
read reaches its provisioning surface -- and the site sends a
``capacity_released`` callback signed by each principal. Nothing is rebuilt,
reconfigured, or restarted.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from compute_provisioning_client import (
    ComputeProvisioningAuthenticationError,
    ComputeProvisioningClient,
)
from compute_provisioning_contracts import (
    IDENTITY_IDENTIFIER_HEADER,
    IDENTITY_SCHEME_HEADER,
    PROVISIONING_ROUTE_TABLE,
    REQUEST_ID_HEADER,
    ROLE_HEADER,
    SIGNATURE_HEADER,
    SIGNATURE_VERSION_HEADER,
    TIMESTAMP_HEADER,
    canonical_provisioning_request_body,
)
from core_storefront.identity_authority import SERVICE_PEER_AUTHORITY
from core_storefront.service_peers import ServicePeerTrust
from fastapi import FastAPI
from market_capacity_publication import SiteProjectionState
from market_identity import (
    EMPTY_BODY,
    Ed25519Signer,
    ResponseEnvelope,
    RotationIntent,
    TrustedIdentitySet,
    canonical_body_hash,
    sign_response,
    sign_rotation,
)
from market_site_client import SiteCapacityClient
from storefront_client.client import StorefrontClient, StorefrontClientError

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
from market_storefront.middleware.service_peer_auth import (
    service_peer_callback_middleware,
)
from market_storefront.services import capacity_client
from market_storefront.utils.sqlite_client import SQLiteClient
from tests._settings_overrides import replaced_setting, settings_overrides
from tests.fake_site import FakeSite

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


class _FulfillmentSurface:
    """One site's compute-provisioning fulfillment routes, answering a status
    read signed as whichever principal its fake site currently signs with."""

    def __init__(self, site: FakeSite) -> None:
        self.site = site

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        fulfillment_id = path.split("/")[-2]
        body = {
            "fulfillment_id": fulfillment_id,
            "capacity_reservation_id": "reservation-1",
            "state": "active",
        }
        contract, resource = PROVISIONING_ROUTE_TABLE.resolve(
            request.method,
            path,
            canonical_provisioning_request_body(request.method, path, EMPTY_BODY, query={}),
        )
        signer = self.site.signer
        signed = sign_response(
            signer=signer,
            envelope=ResponseEnvelope(
                role="service",
                principal=signer.identity,
                method=request.method,
                operation=contract.operation,
                resource=resource,
                request_id=request.headers[REQUEST_ID_HEADER],
                timestamp=int(time.time()),
                status=200,
                body_hash=canonical_body_hash(body),
            ),
        )
        return httpx.Response(
            200,
            content=json.dumps(body).encode(),
            headers={
                "content-type": "application/json",
                SIGNATURE_VERSION_HEADER: signed.protocol,
                IDENTITY_SCHEME_HEADER: signed.principal.scheme.value,
                IDENTITY_IDENTIFIER_HEADER: signed.principal.identifier,
                ROLE_HEADER: signed.role,
                REQUEST_ID_HEADER: signed.request_id,
                TIMESTAMP_HEADER: str(signed.timestamp),
                SIGNATURE_HEADER: signed.proof.value,
            },
        )


@dataclass
class World:
    admin: StorefrontClient
    app: FastAPI
    runtime: Any
    fulfillment: Any
    sites: dict[str, FakeSite]


_CONTAINER_FIELDS = (
    "resolved_domain_registry",
    "resolved_sqlite_client",
    "resolved_marketplace_signer",
    "resolved_service_peer_trust",
    "resolved_capacity_runtime",
    "resolved_site_projections",
)


@pytest.fixture
async def world(tmp_path) -> AsyncIterator[World]:
    db = SQLiteClient(
        db_path=str(tmp_path / "storefront.db"),
        registry=build_vm_storefront_registry(build_vm_storefront_domain()),
    )
    sites = {
        "home": FakeSite(deliverable_modes={"vm"}),
        "away": FakeSite(deliverable_modes={"vm"}),
    }
    sites["home"].signer = _HOME
    sites["away"].signer = _AWAY
    sites["home"].add_resource("home-gpu", 4, attributes={"offering_mode": "vm"})
    trust = ServicePeerTrust(
        db.db_path,
        {
            "home-peer": ("service", "home", _pins(_HOME)),
            "away-peer": ("service", "away", _pins(_AWAY)),
        },
    )
    # As startup seeds it, before any route serves.
    trust.seed()
    saved = {name: getattr(container, name) for name in _CONTAINER_FIELDS}

    def site_client(site, signer):
        return SiteCapacityClient(
            site.url,
            signer=signer,
            expected_authorities=site.expected_authorities,
            transport=sites[site.site_id].transport(),
        )

    def provisioning_client(site_id, url, signer, authorities):
        return ComputeProvisioningClient(
            url,
            signer=signer,
            caller_role="seller",
            expected_authorities=authorities,
            transport=_FulfillmentSurface(sites[site_id]).transport(),
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
        ), replaced_setting(
            # Replaced at its root, so no site another test configured remains.
            "capacity",
            {
                "placement": "fill_first",
                "sites": {"home": "http://home-site:8081", "away": "http://away-site:8081"},
            },
        ):
            initialize_administrator_identities(db.db_path)
            container.resolved_domain_registry = db.domain_registry
            container.resolved_sqlite_client = db
            container.resolved_marketplace_signer = _STOREFRONT
            container.resolved_service_peer_trust = trust
            # A fresh client factory keys a fresh runtime, bound to this trust.
            runtime = capacity_client.build_capacity_runtime_for(
                lambda: db,
                signer=_STOREFRONT,
                site_projections=lambda: container.resolved_site_projections,
                service_peer_trust=trust,
                site_client_factory=site_client,
            )
            container.resolved_capacity_runtime = runtime
            container.resolved_site_projections = SiteProjectionState(
                runtime.client(), on_resource_pool_change=lambda: None
            )
            fulfillment = capacity_client.build_fulfillment_client(
                runtime.client(), client_factory=provisioning_client
            )
            app = FastAPI()
            app.include_router(admin_router)
            app.middleware("http")(service_peer_callback_middleware)
            app.middleware("http")(administrator_identity_middleware)
            async with StorefrontClient(
                "http://test",
                transport=httpx.ASGITransport(app=app),
                signer=_ADMIN,
                caller_role="admin",
                expected_publishers=_pins(_STOREFRONT),
            ) as admin:
                yield World(
                    admin=admin,
                    app=app,
                    runtime=runtime,
                    fulfillment=fulfillment,
                    sites=sites,
                )
    finally:
        for name, value in saved.items():
            setattr(container, name, value)


async def _responses_verify(world: World, site_id: str, signer: Ed25519Signer) -> bool:
    """Whether the site's answers to a ``site-projections`` cycle, signed by
    ``signer``, verify: the cycle reports the site's resource-pool projection
    `loaded` only when the poll's response verified."""
    world.sites[site_id].signer = signer
    cycle = await world.admin.admin_run_lifecycle_cycle("site-projections")
    family = cycle["sites"][site_id]["resource_pool"]
    return family["state"] == "loaded" and family["last_error"] is None


async def _fulfillment_verifies(
    world: World, site_id: str, signer: Ed25519Signer
) -> bool:
    """Whether the site's fulfillment status answer, signed by ``signer``, verifies."""
    world.sites[site_id].signer = signer
    try:
        status = await world.fulfillment.get_fulfillment_status("fulfillment-1", site_id=site_id)
    except ComputeProvisioningAuthenticationError:
        return False
    assert status.state == "active"
    return True


async def _callback_accepted(world: World, signer: Ed25519Signer, reservation: str) -> bool:
    """Whether the home site's ``capacity_released`` callback, signed by
    ``signer``, is authenticated and applied."""
    async with StorefrontClient(
        "http://test",
        transport=httpx.ASGITransport(app=world.app),
        signer=signer,
        caller_role="service",
        expected_publishers=_pins(_STOREFRONT),
    ) as service:
        try:
            released = await service.notify_capacity_released(reservation, site_id="home")
        except StorefrontClientError as exc:
            # Refused before any handler: an unsigned 403 the client reports.
            assert str(exc).startswith("HTTP 403"), exc
            return False
    assert released["state"] == "released"
    return True


async def _reservation(world: World) -> str:
    world.sites["home"].signer = _HOME_NEXT
    reserved = await world.runtime.site_client("home").reserve(
        claim={"offering_mode": "vm", "resource_id": "home-gpu", "gpu_count": 1},
        deal_ref={"escrow_uid": "escrow-1"},
    )
    return str(reserved["capacity_reservation_id"])


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


async def test_a_sites_responses_and_callbacks_follow_its_rotation(world: World):
    """Spec scenario "A site's responses follow its rotation"."""
    assert await _responses_verify(world, "home", _HOME)
    assert await _fulfillment_verifies(world, "home", _HOME)
    assert not await _responses_verify(world, "home", _HOME_NEXT)
    assert not await _fulfillment_verifies(world, "home", _HOME_NEXT)

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
    assert await _responses_verify(world, "home", _HOME_NEXT)
    assert await _fulfillment_verifies(world, "home", _HOME_NEXT)
    assert await _responses_verify(world, "home", _HOME)
    assert await _fulfillment_verifies(world, "home", _HOME)

    await world.admin.admin_complete_identity_rotation(rotation=_rotation(expires_at))
    # The overlap has ended: only the replacement verifies, through the same
    # runtime and clients, nothing reconfigured or restarted.
    assert await _responses_verify(world, "home", _HOME_NEXT)
    assert await _fulfillment_verifies(world, "home", _HOME_NEXT)
    assert not await _responses_verify(world, "home", _HOME)
    assert not await _fulfillment_verifies(world, "home", _HOME)
    # Callbacks follow the same trust: the retired principal is refused and
    # the replacement's callback is applied.
    reservation = await _reservation(world)
    assert not await _callback_accepted(world, _HOME, reservation)
    assert await _callback_accepted(world, _HOME_NEXT, reservation)
    # The other site's trust is its own peer's, untouched by the rotation.
    assert await _responses_verify(world, "away", _AWAY)
    assert await _fulfillment_verifies(world, "away", _AWAY)


async def test_one_sites_principal_verifies_no_other_sites_responses(world: World):
    assert await _responses_verify(world, "home", _HOME)
    assert await _responses_verify(world, "away", _AWAY)
    assert not await _responses_verify(world, "home", _AWAY)
    assert not await _responses_verify(world, "away", _HOME)
    assert await _fulfillment_verifies(world, "home", _HOME)
    assert await _fulfillment_verifies(world, "away", _AWAY)
    assert not await _fulfillment_verifies(world, "home", _AWAY)
    assert not await _fulfillment_verifies(world, "away", _HOME)
