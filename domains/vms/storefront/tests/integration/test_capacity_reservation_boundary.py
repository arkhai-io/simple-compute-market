"""Real capacity-boundary integration coverage.

`domains/vms/storefront/tests/fake_site.py` is an in-process fake used by
almost every other storefront test -- and, by its own docstring, does not
claim to pin the real wire shapes. It does not strip `resource_id` from
reserve responses the way `kit/site`'s real router does, so a test built
only against that fake cannot catch a `resource_id`/`vm_host`-required
regression on either side of the real wire boundary.

This file mounts the real `market_site.router` into a real FastAPI app and
drives it with the real `market_site_client.SiteCapacityClient`
over `ASGITransport` -- an actual wire round-trip, not a hand-rolled
double -- so a future regression in either side of this boundary fails a
test instead of shipping quietly again.
"""

from __future__ import annotations

import json
import time

from typing import Any

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport
from market_identity import (
    EMPTY_BODY,
    Ed25519Signer,
    ResponseEnvelope,
    TrustedIdentitySet,
    canonical_body_hash,
    sign_response,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

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
from starlette.responses import Response


MARKETPLACE_SIGNER = Ed25519Signer(b"\x41" * 32)
SITE_AUTHORITY_SIGNER = Ed25519Signer(b"\x42" * 32)
SITE_AUTHORITIES = TrustedIdentitySet(
    identities=(SITE_AUTHORITY_SIGNER.identity,)
)


@pytest.fixture
def site_app() -> tuple[FastAPI, CapacityLedgerService]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    ledger = CapacityLedgerService(session_factory, unit_claim_keys=("units", "gpu_count"))
    ledger.register_resource(
        resource_id="kvm1",
        total_units=1,
        capacity={"gpu_count": 1},
        attributes={"vm_host": "kvm1", "pool_id": "default"},
        pool_id="default",
    )

    app = FastAPI()
    app.include_router(make_capacity_router(lambda: ledger), prefix="/api/v1")

    @app.middleware("http")
    async def sign_site_response(request: Request, call_next):
        raw_request = await request.body()
        request_body = json.loads(raw_request) if raw_request else EMPTY_BODY
        operation, resource = resolve_capacity_route(
            request.method,
            request.url.path,
            request_body,
        )
        response = await call_next(request)
        raw_response = (
            b"".join([chunk async for chunk in response.body_iterator])
            if hasattr(response, "body_iterator")
            else bytes(response.body)
        )
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
            background=response.background,
        )
    return app, ledger


def _client(app: FastAPI) -> SiteCapacityClient:
    return SiteCapacityClient(
        "http://test",
        signer=MARKETPLACE_SIGNER,
        expected_authorities=SITE_AUTHORITIES,
        transport=ASGITransport(app=app),
    )


class TestOpaqueReservationBoundary:
    """The real wire contract never carries `resource_id`/`vm_host` as
    required or populated fields across the reservation boundary."""

    async def test_reserve_response_never_carries_placement_fields(self, site_app):
        """Boundary-contract test: protects any future caller, not just the
        storefront's obligation-fulfillment path."""
        app, _ = site_app
        client = _client(app)

        reservation = await client.reserve(
            claim={"pool_id": "default", "gpu_count": 1},
            deal_ref={"escrow_uid": "escrow-1"},
        )

        assert reservation is not None
        for leaked_field in ("resource_id", "capacity_bucket_id", "backing_resource_id"):
            assert leaked_field not in reservation, (
                f"{leaked_field!r} must not appear in a reservation response "
                "-- it is the provisioning authority's private placement "
                "accounting, not durable storefront-facing reservation identity"
            )

    async def test_commit_accepts_the_opaque_reservation_response_without_placement_fields(
        self, site_app,
    ):
        """Commit accepts the opaque reservation response without placement fields."""
        app, ledger = site_app
        client = _client(app)

        reservation = await client.reserve(
            claim={"pool_id": "default", "gpu_count": 1},
            deal_ref={"escrow_uid": "escrow-1"},
        )
        assert reservation is not None
        capacity_reservation_id = reservation["capacity_reservation_id"]

        # resource_id is deliberately stripped by the wire boundary (see
        # test_reserve_response_never_carries_placement_fields above).
        # vm_host is not stripped the same way -- it may or may not be
        # present depending on the matched resource's own attributes -- so
        # the fix here is not "vm_host is always absent", it's that
        # fulfillment must not *require* it. Confirmed below by never
        # reading it before commit.
        assert "resource_id" not in reservation

        await client.commit(
            resource_id=None,
            capacity_reservation_id=capacity_reservation_id,
            lease_start_utc=None,
            lease_end_utc=None,
            idempotency_ref="escrow-1",
        )

        committed = ledger.get_reservation(capacity_reservation_id)
        assert committed["state"] == "leased"

    async def test_commit_without_capacity_reservation_id_still_rejected(self, site_app):
        """capacity_reservation_id remains genuinely required -- only
        resource_id became optional. Confirms the fix didn't overcorrect."""
        app, _ = site_app
        client = _client(app)

        with pytest.raises(ValueError):
            await client.commit(resource_id=None, capacity_reservation_id=None)
