"""Real capacity-boundary integration coverage.

`domains/vms/storefront/tests/fake_site.py` is an in-process fake used by
almost every other storefront test -- and, by its own docstring, does not
claim to pin the real wire shapes. It does not strip `resource_id` from
reserve responses the way `kit/site`'s real router does, which is exactly
how the original `resource_id`/`vm_host`-required bugs went undetected
through the entire existing storefront test suite.

This file mounts the real `market_site.router` into a real FastAPI app and
drives it with the real `core_storefront.capacity_remote.RemoteCapacityClient`
over `ASGITransport` -- an actual wire round-trip, not a hand-rolled
double -- so a future regression in either side of this boundary fails a
test instead of shipping quietly again.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core_storefront.capacity_remote import RemoteCapacityClient
from market_site.db import Base
from market_site.ledger import CapacityLedgerService
from market_site.router import make_capacity_router


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
    return app, ledger


def _client(app: FastAPI) -> RemoteCapacityClient:
    return RemoteCapacityClient(
        "http://test", transport=ASGITransport(app=app),
    )


class TestOpaqueReservationBoundary:
    """The regression coverage for the original resource_id/vm_host bug."""

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
