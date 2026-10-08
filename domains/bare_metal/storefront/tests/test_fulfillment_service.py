from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from core_storefront import (
    StorefrontDomainBinding,
    StorefrontFulfillmentContext,
    StorefrontFulfillmentPorts,
    StorefrontThreadBinding,
    fulfill_domain,
)
from arkhai_bare_metal import BareMetalListing, BareMetalTerms
from market_core import VersionedEnvelope
from market_identity import Ed25519Signer

from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.fulfillment_service import (
    BareMetalFulfillmentError,
    BareMetalFulfillmentService,
)
from arkhai_bare_metal.fixtures.listing import LISTING_HARDWARE


BUYER = Ed25519Signer(bytes.fromhex("11" * 32)).identity


class FakeDb:
    def __init__(self) -> None:
        self._market_domain = get_market_domain_contract()
        self.lifecycle = None
        self.materialization = None
        self.receipt = None
        self.result = None
        self.context = {
            "buyer_scheme": BUYER.scheme.value,
            "buyer_identifier": BUYER.identifier,
            "terminal_state": "success",
            "site_id": "site-a",
            "physical_resource_id": "resource-a",
            "host_id": "machine-a",
            "physical_host_id": "host-a",
            "claimed_attributes": {"gpu_model": LISTING_HARDWARE["gpu_model"]},
        }
        self.terms = BareMetalTerms(
            host_id="machine-a",
            physical_host_id="host-a",
            duration_seconds=3600,
            ssh_public_key="ssh-ed25519 buyer",
        )
        self.listing = BareMetalListing(
            capacity_backing="backed",
            **LISTING_HARDWARE,
            host_id="machine-a",
            physical_host_id="host-a",
        )

    async def load_thread_binding(self, *, negotiation_id):
        return StorefrontThreadBinding(
            negotiation_id=negotiation_id,
            listing_id="listing-a",
            site_id="site-a",
            binding=StorefrontDomainBinding(
                offering_mode="bare_metal",
                domain_identity=get_market_domain_contract().identity,
                contract_major=1,
                contract_minor=0,
            ),
        )

    async def load_bare_metal_fulfillment_context(self, *, negotiation_id):
        assert negotiation_id == "neg-a"
        return dict(self.context)

    async def load_escrow(self, *, escrow_uid):
        return {
            "escrow_uid": escrow_uid,
            "negotiation_id": "neg-a",
            "status": "settlement_verified",
        }

    async def load_bare_metal_terms(self, *, negotiation_id):
        return self.terms

    async def load_bare_metal_listing_payload(self, *, listing_id):
        assert listing_id == "listing-a"
        return self.listing

    async def ensure_bare_metal_fulfillment_lifecycle(self, **identity):
        if self.lifecycle is None:
            self.lifecycle = {**identity, "state": "planning"}
        return dict(self.lifecycle)

    async def load_bare_metal_fulfillment_lifecycle(self, *, negotiation_id):
        return None if self.lifecycle is None else dict(self.lifecycle)

    async def update_bare_metal_fulfillment_lifecycle(
        self,
        *,
        negotiation_id,
        state,
        capacity_reservation_id=None,
        settlement_resource_id=None,
        fulfillment_id=None,
        failure_reason=None,
    ):
        assert self.lifecycle is not None
        self.lifecycle["state"] = state
        for key, value in (
            ("capacity_reservation_id", capacity_reservation_id),
            ("settlement_resource_id", settlement_resource_id),
            ("fulfillment_id", fulfillment_id),
            ("failure_reason", failure_reason),
        ):
            if value is not None:
                self.lifecycle[key] = value
        return dict(self.lifecycle)

    async def save_bare_metal_materialization(self, *, negotiation_id, materialization):
        self.materialization = materialization

    async def load_bare_metal_materialization(self, *, negotiation_id):
        return self.materialization

    async def save_bare_metal_receipt(self, *, negotiation_id, receipt):
        self.receipt = receipt

    async def save_bare_metal_result(self, *, negotiation_id, result):
        self.result = result


class FakeSite:
    def __init__(self) -> None:
        self.releases = []

    async def list_reservations(self):
        return []

    async def release(self, **request):
        self.releases.append(request)
        return {"state": "released"}


class FakeCapacity:
    def __init__(self, *, returned_site: str = "site-a") -> None:
        self.returned_site = returned_site
        self.site_client = FakeSite()
        self.reservation_sites = {}
        self.reserves = []
        self.commits = []
        self.committed_window: tuple[str, str] | None = None

    def site(self, site_id):
        assert site_id == "site-a"
        return self.site_client

    async def reserve(self, **request):
        self.reserves.append(request)
        self.reservation_sites["reservation-a"] = request["site"]
        return {
            "capacity_reservation_id": "reservation-a",
            "site": self.returned_site,
        }

    async def commit(self, **request):
        """Write-once, as the site's: the first commit's window is kept."""
        self.commits.append(request)
        if self.committed_window is None:
            self.committed_window = (request["lease_start_utc"], request["lease_end_utc"])
        start, end = self.committed_window
        return {
            "capacity_reservation_id": request["capacity_reservation_id"],
            "state": "leased",
            "lease_start_utc": start,
            "lease_end_utc": end,
            "site": request["site_id"],
        }


class FakeFulfillment:
    def __init__(self, *, begin_failures: int = 0) -> None:
        self.phase = "create"
        self.schedules = []
        self.begins = []
        self.teardowns = []
        self.terminations = []
        self.begin_failures = begin_failures

    async def schedule_resource(self, request):
        self.schedules.append(request)
        return SimpleNamespace(
            settlement_resource_id="settlement-resource-a",
            pool_id="pool-a",
            resource_kind="compute.bare-metal",
            provider="bare_metal.ansible",
            attributes={
                "bare_metal_publication": {
                    "enabled": True,
                    "host_id": "machine-a",
                    "physical_host_id": "host-a",
                }
            },
        )

    async def begin_fulfillment(self, body):
        self.begins.append(body)
        if self.begin_failures:
            self.begin_failures -= 1
            raise RuntimeError("controlled failure after materialization")
        return SimpleNamespace(
            fulfillment_id="fulfillment-a",
            capacity_reservation_id="reservation-a",
            state="dispatch_pending",
        )

    async def get_fulfillment_status(self, fulfillment_id, **request):
        assert fulfillment_id == "fulfillment-a"
        return SimpleNamespace(
            state="torn_down" if self.phase == "teardown" else "active",
            failure_reason=None,
            failure_message=None,
        )

    async def get_fulfillment_result(self, fulfillment_id, **request):
        return VersionedEnvelope(
            kind="fulfillment.result.v1",
            schema_version=1,
            payload={
                "fulfillment_id": fulfillment_id,
                "capacity_reservation_id": "reservation-a",
                "state": "active",
                "provisioned_resources": [],
                "domain_result": {
                    "kind": "compute.access-delivery",
                    "schema_version": 1,
                    "payload": {
                        "endpoints": [
                            {
                                "protocol": "ssh",
                                "host": "203.0.113.10",
                                "port": 22,
                                "user": "tenant-a",
                            }
                        ],
                        "credentials": [],
                        "ready_at": "2030-01-01T00:00:01+00:00",
                    },
                },
            },
        )

    async def terminate_lease(self, capacity_reservation_id, *, reason=None):
        """The site ends the lease and converges teardown through its fulfillment."""
        self.phase = "teardown"
        self.terminations.append((capacity_reservation_id, reason))
        return SimpleNamespace(capacity_reservation_id=capacity_reservation_id, status="releasing")

    async def begin_fulfillment_teardown(self, fulfillment_id, **request):
        self.phase = "teardown"
        self.teardowns.append((fulfillment_id, request))
        return SimpleNamespace(
            fulfillment_id=fulfillment_id,
            capacity_reservation_id="reservation-a",
            state="teardown_dispatch_pending",
        )


@pytest.mark.asyncio
async def test_selected_site_lifecycle_is_idempotent_and_ends_its_lease() -> None:
    db = FakeDb()
    capacity = FakeCapacity()
    fulfillment = FakeFulfillment()
    service = BareMetalFulfillmentService(
        db=db,
        capacity_client=capacity,
        fulfillment_client=fulfillment,
    )
    begun_projection = await fulfill_domain(
        get_market_domain_contract(),
        StorefrontFulfillmentContext(
            thread_binding=StorefrontThreadBinding(
                negotiation_id="neg-a",
                listing_id="listing-a",
                site_id="site-a",
                binding=StorefrontDomainBinding(
                    offering_mode="bare_metal",
                    domain_identity=get_market_domain_contract().identity,
                    contract_major=1,
                    contract_minor=0,
                ),
            ),
            escrow_uid="escrow-a",
            buyer_principal=BUYER,
            ports=StorefrontFulfillmentPorts(
                repository=db,
                capacity_client=capacity,
                fulfillment_client=fulfillment,
            ),
        ),
    )
    begun = dict(db.lifecycle)
    repeated = await service.begin(
        negotiation_id="neg-a",
        escrow_uid="escrow-a",
        buyer_principal=BUYER,
    )

    assert begun_projection.fulfillment_id == "fulfillment-a"
    assert begun["fulfillment_id"] == "fulfillment-a"
    assert repeated == begun
    assert len(capacity.reserves) == 1
    assert capacity.reserves[0]["site"] == "site-a"
    assert capacity.reserves[0]["claim"] == {
        "gpu_model": "H200",
        "resource_id": "resource-a",
        "dimensions": {"units": 1},
        "offering_mode": "bare_metal",
    }
    assert len(fulfillment.schedules) == 1
    assert fulfillment.schedules[0].resource_id == "resource-a"
    assert fulfillment.schedules[0].requirements == {
        "resource_kind": "compute.bare-metal"
    }
    assert len(fulfillment.begins) == 1
    assert fulfillment.begins[0].fulfillment_request.payload["host_id"] == "machine-a"

    ready = await service.status(
        negotiation_id="neg-a",
        buyer_principal=BUYER,
    )
    assert ready["state"] == "active"
    assert db.receipt.status == "ready"
    assert db.result.ssh_user == "tenant-a"
    assert "host" not in db.result.model_dump()

    tearing_down = await service.teardown(
        negotiation_id="neg-a",
        buyer_principal=BUYER,
    )
    assert tearing_down["state"] == "terminating"
    repeated_teardown = await service.teardown(
        negotiation_id="neg-a",
        buyer_principal=BUYER,
    )
    torn_down = await service.status(
        negotiation_id="neg-a",
        buyer_principal=BUYER,
    )
    # Teardown ends the lease once; a repeat reports what the site has since
    # converged, and only its capacity-released callback records the release.
    assert repeated_teardown["state"] == "torn_down"
    assert fulfillment.terminations == [("reservation-a", "buyer_teardown")]
    assert fulfillment.teardowns == []
    assert torn_down["state"] == "torn_down"
    assert capacity.site_client.releases == []


@pytest.mark.asyncio
async def test_begin_retry_reuses_immutable_materialization() -> None:
    db = FakeDb()
    capacity = FakeCapacity()
    fulfillment = FakeFulfillment(begin_failures=1)
    service = BareMetalFulfillmentService(
        db=db,
        capacity_client=capacity,
        fulfillment_client=fulfillment,
    )

    with pytest.raises(RuntimeError, match="controlled failure"):
        await service.begin(
            negotiation_id="neg-a",
            escrow_uid="escrow-a",
            buyer_principal=BUYER,
        )
    recorded = db.materialization

    retried = await service.begin(
        negotiation_id="neg-a",
        escrow_uid="escrow-a",
        buyer_principal=BUYER,
    )

    assert retried["fulfillment_id"] == "fulfillment-a"
    assert db.materialization == recorded
    assert len(capacity.reserves) == 1
    assert len(fulfillment.schedules) == 1
    assert len(fulfillment.begins) == 2
    # The lease begins at commit: each attempt commits with the deal's escrow
    # before beginning, and the materialization states the window the first
    # commit recorded, not a clock of the storefront's own.
    assert [commit["deal_ref"] for commit in capacity.commits] == [
        {"escrow_uid": "escrow-a"},
        {"escrow_uid": "escrow-a"},
    ]
    start, end = capacity.committed_window
    assert (recorded.lease_start_utc, recorded.lease_end_utc) == (
        datetime.fromisoformat(start),
        datetime.fromisoformat(end),
    )


@pytest.mark.asyncio
async def test_reservation_conflicting_site_fails_before_scheduling() -> None:
    db = FakeDb()
    capacity = FakeCapacity(returned_site="site-b")
    fulfillment = FakeFulfillment()
    service = BareMetalFulfillmentService(
        db=db,
        capacity_client=capacity,
        fulfillment_client=fulfillment,
    )

    with pytest.raises(BareMetalFulfillmentError, match="conflicting site"):
        await service.begin(
            negotiation_id="neg-a",
            escrow_uid="escrow-a",
            buyer_principal=BUYER,
        )

    assert fulfillment.schedules == []
    assert fulfillment.begins == []


async def test_a_listing_naming_no_attributes_reserves_nothing() -> None:
    """The claim's attributes come only from the trusted listing record; without
    them the reservation is refused rather than made on units alone."""
    db = FakeDb()
    db.context.pop("claimed_attributes")
    capacity = FakeCapacity()
    service = BareMetalFulfillmentService(
        db=db,
        capacity_client=capacity,
        fulfillment_client=FakeFulfillment(),
    )

    with pytest.raises(BareMetalFulfillmentError, match="no attributes to claim"):
        await service.begin(
            negotiation_id="neg-a",
            escrow_uid="escrow-a",
            buyer_principal=BUYER,
        )

    assert capacity.reserves == []
