"""A bare-metal deal's capacity effects against a real site.

The site is `kit/site`'s capacity router over a real `CapacityLedgerService`,
mounted in a FastAPI app whose responses are signed as the site authority, and
the fulfillment service reaches it through the storefront's production capacity
client: an `AggregateCapacityClient` over `SiteCapacityClient`, over
`ASGITransport`. The ledger is configured as the compute provisioning service
configures its own, so admission, the reservation it records, and the commit
are the site's, not a matcher called beside the claim. The storefront's
persistence, its settlement evidence, and provisioning are in-memory stand-ins:
they hold what an accepted deal records and are not what these tests prove.

Every signer here is a development fixture, never for use on a public network.
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from typing import Any

import pytest
from arkhai_bare_metal import BareMetalListing, BareMetalTerms
from core_storefront.aggregation import AggregateCapacityClient
from fastapi import FastAPI, Request, Response
from httpx import ASGITransport
from market_core import SettlementEvidence
from market_identity import (
    EMPTY_BODY,
    Ed25519Signer,
    ResponseEnvelope,
    TrustedIdentitySet,
    canonical_body_hash,
    sign_response,
)
from market_resource_pools import ResourcePool
from market_resource_pools.db import Base as ResourcePoolBase
from market_site.db import Base
from market_site.ledger import CapacityLedgerService
from market_site.router import make_capacity_router
from market_site_client import SiteCapacityClient
from market_site_client.client import (
    IDENTITY_IDENTIFIER_HEADER,
    IDENTITY_SCHEME_HEADER,
    REQUEST_ID_HEADER,
    ROLE_HEADER,
    SIGNATURE_HEADER,
    SIGNATURE_VERSION_HEADER,
    TIMESTAMP_HEADER,
    resolve_capacity_route,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from arkhai_bare_metal_storefront.fulfillment_service import BareMetalFulfillmentService
from arkhai_bare_metal_storefront.settlement_evidence import DeliveryInput, EvidencePayload

STOREFRONT_SIGNER = Ed25519Signer(b"\x51" * 32)
SITE_AUTHORITY_SIGNER = Ed25519Signer(b"\x52" * 32)
BUYER = Ed25519Signer(b"\x53" * 32).identity
SITE, POOL, RESOURCE = "site-a", "pool-a", "resource-a"
HOST, PHYSICAL_HOST = "machine-a", "physical-host-a"


def _site_app() -> tuple[FastAPI, CapacityLedgerService]:
    """The site's capacity router over a ledger holding one GPU-less machine,
    declared as a whole host in a pool that delivers bare metal."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    ResourcePoolBase.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as db, db.begin():
        db.add(
            ResourcePool(
                id=POOL,
                label="Bare-metal pool",
                provider="bare_metal.ansible",
                enabled=True,
                policy_tags={"deliverable_modes": ["bare_metal"]},
            )
        )
    ledger = CapacityLedgerService(
        session_factory, unit_claim_keys=("units", "gpu_count"), mirror_dimension="gpu_count"
    )
    ledger.register_resource(
        resource_id=RESOURCE,
        pool_id=POOL,
        host_id=HOST,
        capacity={"units": 1, "vcpu_count": 64, "ram_gb": 512},
        attributes={
            "physical_host_id": PHYSICAL_HOST,
            "allocation_mode": "exclusive",
            "bare_metal_publication": {"enabled": True, "access_methods": ["ssh"]},
        },
    )

    app = FastAPI()
    app.include_router(make_capacity_router(lambda: ledger), prefix="/api/v1")

    @app.middleware("http")
    async def sign_site_response(request: Request, call_next):
        raw_request = await request.body()
        request_body = json.loads(raw_request) if raw_request else EMPTY_BODY
        operation, resource = resolve_capacity_route(
            request.method, request.url.path, request_body
        )
        response = await call_next(request)
        raw_response = b"".join([chunk async for chunk in response.body_iterator])
        response_body = json.loads(raw_response) if raw_response else EMPTY_BODY
        signed = sign_response(
            signer=SITE_AUTHORITY_SIGNER,
            envelope=ResponseEnvelope(
                role="service",
                principal=SITE_AUTHORITY_SIGNER.identity,
                method=request.method,
                operation=operation,
                resource=resource,
                request_id=request.headers[REQUEST_ID_HEADER],
                timestamp=int(time.time()),
                status=response.status_code,
                body_hash=canonical_body_hash(response_body),
            ),
        )
        headers = dict(response.headers)
        headers.update(
            {
                SIGNATURE_VERSION_HEADER: signed.protocol,
                IDENTITY_SCHEME_HEADER: signed.principal.scheme.value,
                IDENTITY_IDENTIFIER_HEADER: signed.principal.identifier,
                ROLE_HEADER: signed.role,
                REQUEST_ID_HEADER: signed.request_id,
                TIMESTAMP_HEADER: str(signed.timestamp),
                SIGNATURE_HEADER: signed.proof.value,
            }
        )
        headers.pop("content-length", None)
        return Response(
            content=raw_response,
            status_code=response.status_code,
            headers=headers,
            media_type=response.media_type,
        )

    return app, ledger


class AcceptedDeal:
    """The storefront's record of one accepted deal for the machine, as the
    fulfillment service reads and advances it."""

    def __init__(self, listing: BareMetalListing) -> None:
        self.lifecycle: dict[str, Any] | None = None
        self.materialization = None
        self.terms = BareMetalTerms(
            host_id=HOST,
            physical_host_id=PHYSICAL_HOST,
            duration_seconds=3600,
            ssh_public_key="ssh-ed25519 buyer",
        )
        self.context = {
            "buyer_scheme": BUYER.scheme.value,
            "buyer_identifier": BUYER.identifier,
            "terminal_state": "success",
            "listing_id": "listing-a",
            "site_id": SITE,
            "pool_id": POOL,
            "physical_resource_id": RESOURCE,
            "host_id": HOST,
            "physical_host_id": PHYSICAL_HOST,
            "claimed_attributes": listing.claimed_attributes,
        }

    async def load_listing_binding(self, *, listing_id):
        return SimpleNamespace(
            site_id=SITE,
            physical_resource_id=RESOURCE,
            binding=SimpleNamespace(offering_mode="bare_metal"),
            capacity_backing="backed",
        )

    async def load_bare_metal_fulfillment_context(self, *, negotiation_id):
        return dict(self.context)

    async def verified_evidence(self, *, negotiation_id, buyer_principal, **_):
        return SettlementEvidence(
            negotiation_id=negotiation_id,
            mechanism="alkahest.v1",
            settlement_ref="escrow-a",
            status="settlement_verified",
            evidence=EvidencePayload(
                agreement_sha256="a" * 64,
                delivery=DeliveryInput(
                    site_id=SITE,
                    physical_resource_id=RESOURCE,
                    pool_id=POOL,
                    terms=self.terms,
                ),
            ).model_dump(mode="json"),
        )

    async def ensure_bare_metal_fulfillment_lifecycle(self, **identity):
        if self.lifecycle is None:
            self.lifecycle = {**identity, "state": "planning"}
        return dict(self.lifecycle)

    async def update_bare_metal_fulfillment_lifecycle(self, *, negotiation_id, state, **ids):
        assert self.lifecycle is not None
        self.lifecycle["state"] = state
        self.lifecycle.update({key: value for key, value in ids.items() if value is not None})
        return dict(self.lifecycle)

    async def load_bare_metal_materialization(self, *, negotiation_id):
        return self.materialization

    async def save_bare_metal_materialization(self, *, negotiation_id, materialization):
        self.materialization = materialization


class Provisioning:
    """Schedules the reserved machine and accepts its fulfillment."""

    async def schedule_resource(self, request):
        return SimpleNamespace(
            settlement_resource_id="settlement-resource-a",
            pool_id=POOL,
            resource_kind="compute.bare-metal",
            provider="bare_metal.ansible",
            attributes={
                "bare_metal_publication": {
                    "enabled": True,
                    "host_id": HOST,
                    "physical_host_id": PHYSICAL_HOST,
                }
            },
        )

    async def begin_fulfillment(self, body):
        return SimpleNamespace(
            fulfillment_id="fulfillment-a",
            capacity_reservation_id=body.capacity_reservation_id,
            state="dispatch_pending",
        )


@pytest.fixture
def site() -> tuple[FastAPI, CapacityLedgerService]:
    return _site_app()


async def test_a_machine_without_gpus_is_reserved_and_leased_at_the_site(site) -> None:
    """A listing whose shape states no attribute claims one unit of its
    Physical Resource with no attribute, which the site admits, holds against
    that machine, and leases at commit."""
    app, ledger = site
    listing = BareMetalListing(
        capacity_backing="backed",
        region="us-west",
        vcpu_count=64,
        ram_gb=512,
        host_id=HOST,
        physical_host_id=PHYSICAL_HOST,
        access_methods=["ssh"],
    )
    deal = AcceptedDeal(listing)
    capacity = AggregateCapacityClient(
        {
            SITE: SiteCapacityClient(
                "http://site-a",
                signer=STOREFRONT_SIGNER,
                expected_authorities=TrustedIdentitySet(
                    identities=(SITE_AUTHORITY_SIGNER.identity,)
                ),
                transport=ASGITransport(app=app),
            )
        }
    )
    service = BareMetalFulfillmentService(
        db=deal,
        capacity_client=capacity,
        fulfillment_client=Provisioning(),
        read_verified_evidence=deal.verified_evidence,
    )

    lifecycle = await service.begin(
        negotiation_id="neg-a", settlement_ref="escrow-a", buyer_principal=BUYER
    )

    assert listing.claimed_attributes == {}
    reservation_id = lifecycle["capacity_reservation_id"]
    reservation = ledger.get_reservation(reservation_id)
    assert reservation["state"] == "leased"
    assert ledger.get_reservation_backing_resource_id(reservation_id) == RESOURCE
    assert reservation["host_id"] == HOST
    assert reservation["dimensions"] == {"units": 1}
    assert reservation["claim_attributes"] == {"resource_id": RESOURCE}
    assert reservation["deal_ref"] == {"escrow_uid": "escrow-a", "negotiation_id": "neg-a"}
    (row,) = ledger.snapshot()
    assert row["available"]["units"] == 0
    # The scalar figure mirrors `gpu_count`, which this machine does not declare.
    assert row["available_units"] is None
