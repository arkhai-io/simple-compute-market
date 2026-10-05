"""The compute family's lease surface, over the real API and the canonical client.

One surface serves every offering mode's leases as the neutral ``LeaseView``:
register, get, list, terminate, release-oversight, retry-release, and
force-release. A lease is the tail of a capacity reservation and is addressed
by its reservation id; registration writes the tail once, and there is no
lease update. A storefront registers, reads, and terminates its own leases as
the seller; the list and the release controls are the administrator's.

The ledger's write-once and truncation rules are proven in ``kit/site``; the
lifecycle's paths by aggregate state in the service's unit suite and in
``test_lease_release_api.py``. This covers the routes, their roles, their
refusals, and the wire shape.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport
from market_fulfillment import SettlementRecord, SettlementRecordState

from compute_provisioning_client import (
    ComputeProvisioningAuthenticationError,
    ComputeProvisioningClient,
    ComputeProvisioningError,
)
from compute_provisioning_contracts import (
    LeaseForceRelease,
    LeaseRegistration,
    LeaseReleaseOversight,
    LeaseRetryRelease,
    LeaseState,
    LeaseTermination,
)
from compute_provisioning_service import container as _container_module
from compute_provisioning_service.main import app, provisioning_route_table

from .conftest import SERVICE_AUTHORITIES, STOREFRONT_SIGNER

_END = datetime(2099, 1, 1, tzinfo=timezone.utc)
_START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _committed(escrow_uid: str, *, offering_mode: str = "vm", end: datetime = _END) -> str:
    """A storefront's committed reservation, as commit leaves it before registration."""
    ledger = _container_module.resolved_capacity_ledger_service
    if "compute-kvm1-001" not in {r["resource_id"] for r in ledger.list_resources()}:
        ledger.register_resource(
            resource_id="compute-kvm1-001",
            total_units=8,
            host_id="kvm1",
            attributes={},
            pool_id="default",
        )
    reserved = ledger.reserve(
        claim={"offering_mode": offering_mode, "gpu_count": 1, "host_id": "kvm1"},
        deal_ref={"escrow_uid": escrow_uid},
    )
    assert reserved is not None
    ledger.commit(
        capacity_reservation_id=reserved["capacity_reservation_id"],
        lease_start_utc=_START.isoformat(),
        lease_end_utc=end.isoformat(),
    )
    return reserved["capacity_reservation_id"]


def _registration(capacity_reservation_id: str, *, target: str = "tenant-1", end=_END):
    return LeaseRegistration(
        capacity_reservation_id=capacity_reservation_id,
        deal_ref={"escrow_uid": "0x1"},
        executor_target=target,
        lease_start_utc=_START,
        lease_end_utc=end,
    )


def _aggregate(capacity_reservation_id: str, state: str, fulfillment_id: str) -> None:
    """A fulfillment aggregate as convergence would leave it."""
    with _container_module.resolved_session_factory() as db, db.begin():
        db.add(
            SettlementRecord(
                capacity_reservation_id=capacity_reservation_id,
                fulfillment_id=fulfillment_id,
                market="vms",
                scheduling_requirements={"resource_kind": "vm"},
                settlement_resource_id="kvm1",
                pool_id="default",
                provider="ansible",
                resource_host_id="kvm1",
                resource_attributes={},
                prepared_teardown_operation={
                    "kind": "vm.ansible.teardown.v1",
                    "schema_version": 1,
                    "payload": {},
                },
                provider_metadata={},
                state=state,
            )
        )


def _set_aggregate(fulfillment_id: str, state: str) -> None:
    with _container_module.resolved_session_factory() as db, db.begin():
        record = (
            db.query(SettlementRecord)
            .filter(SettlementRecord.fulfillment_id == fulfillment_id)
            .one()
        )
        record.state = state


@pytest_asyncio.fixture
async def seller(client_and_queue):
    """The storefront's view: the family client signed as the seller."""
    async with ComputeProvisioningClient(
        "http://test",
        signer=STOREFRONT_SIGNER,
        caller_role="seller",
        expected_authorities=SERVICE_AUTHORITIES,
        transport=ASGITransport(app=app),
    ) as client:
        yield client


class TestRegistration:
    async def test_a_registration_on_a_committed_reservation_reports_the_lease(
        self, client_and_queue, seller
    ):
        reservation_id = _committed("0xreg")

        lease = await seller.register_lease(_registration(reservation_id))

        assert lease.capacity_reservation_id == reservation_id
        assert (lease.offering_mode, lease.status, lease.executor_target) == (
            "vm",
            LeaseState.ACTIVE,
            "tenant-1",
        )

    async def test_a_registration_on_no_live_reservation_is_not_found(self, seller):
        with pytest.raises(ComputeProvisioningError) as refused:
            await seller.register_lease(_registration("missing"))

        assert refused.value.status_code == 404

    async def test_a_repeated_registration_is_returned_and_never_moves_the_end(
        self, client_and_queue, seller
    ):
        """A storefront re-registering after a truncation, as a resume pass does,
        gets the truncated lease back."""
        clients, _ = client_and_queue
        reservation_id = _committed("0xrepeat")
        await seller.register_lease(_registration(reservation_id))
        truncated_end = datetime(2030, 1, 1, tzinfo=timezone.utc)
        await clients.site.truncate_lease(
            capacity_reservation_id=reservation_id, lease_end_utc=truncated_end.isoformat()
        )

        again = await seller.register_lease(_registration(reservation_id))

        assert again.lease_end_utc == truncated_end

    async def test_a_registration_naming_another_target_is_a_conflict(
        self, client_and_queue, seller
    ):
        reservation_id = _committed("0xother")
        await seller.register_lease(_registration(reservation_id))

        with pytest.raises(ComputeProvisioningError) as refused:
            await seller.register_lease(_registration(reservation_id, target="tenant-2"))

        assert refused.value.status_code == 409
        assert (await seller.get_lease(reservation_id)).executor_target == "tenant-1"

    def test_there_is_no_lease_update_route(self):
        """A lease's end moves only through the site's truncation, and its
        executor identity and handles are fixed at registration."""
        for path in ("/api/v1/contract/leases/r-1", "/api/v1/leases/r-1"):
            with pytest.raises(ValueError):
                provisioning_route_table.resolve("PATCH", path, {})


class TestReads:
    async def test_a_lease_is_read_by_its_reservation_and_a_hold_is_not_a_lease(
        self, client_and_queue, seller
    ):
        reservation_id = _committed("0xget")
        await seller.register_lease(_registration(reservation_id))
        ledger = _container_module.resolved_capacity_ledger_service
        hold = ledger.reserve(
            claim={"offering_mode": "vm", "gpu_count": 1, "host_id": "kvm1"},
            deal_ref={"escrow_uid": "0xhold"},
        )

        assert (await seller.get_lease(reservation_id)).capacity_reservation_id == reservation_id
        with pytest.raises(ComputeProvisioningError) as refused:
            await seller.get_lease(hold["capacity_reservation_id"])
        assert refused.value.status_code == 404

    async def test_the_list_is_the_operator_s_and_filters_by_mode_and_status(
        self, client_and_queue, seller
    ):
        clients, _ = client_and_queue
        vm = _committed("0xlist-vm")
        bare_metal = _committed("0xlist-bm", offering_mode="bare_metal")

        everything = await clients.family.list_leases()
        bare_metal_only = await clients.family.list_leases(offering_mode="bare_metal")
        active = await clients.family.list_leases(status=LeaseState.ACTIVE)

        assert {vm, bare_metal} <= {lease.capacity_reservation_id for lease in everything.leases}
        assert [lease.capacity_reservation_id for lease in bare_metal_only.leases] == [bare_metal]
        assert all(lease.status == LeaseState.ACTIVE for lease in active.leases)
        with pytest.raises(ComputeProvisioningAuthenticationError):
            await seller.list_leases()


class TestRelease:
    async def test_a_storefront_terminates_its_lease_into_teardown(
        self, client_and_queue, seller
    ):
        reservation_id = _committed("0xterm")
        await seller.register_lease(_registration(reservation_id))
        _aggregate(reservation_id, SettlementRecordState.active.value, "fulfillment-term")

        lease = await seller.terminate_lease(reservation_id, LeaseTermination())

        assert (lease.status, lease.release_job_id) == (
            LeaseState.RELEASING,
            "fulfillment-term",
        )

    async def test_check_leases_releases_an_expired_lease_once_torn_down(
        self, client_and_queue
    ):
        clients, _ = client_and_queue
        reservation_id = _committed(
            "0xexpire", end=datetime.now(timezone.utc) - timedelta(seconds=5)
        )
        _aggregate(reservation_id, SettlementRecordState.active.value, "fulfillment-exp")

        await clients.family.check_leases()
        _set_aggregate("fulfillment-exp", SettlementRecordState.torn_down.value)
        await clients.family.check_leases()

        assert (await clients.family.get_lease(reservation_id)).status == LeaseState.RELEASED

    async def test_release_oversight_hands_a_lease_to_the_operator(self, client_and_queue):
        clients, _ = client_and_queue
        reservation_id = _committed("0xoversight")

        lease = await clients.family.release_lease_oversight(
            reservation_id, LeaseReleaseOversight(reason="manual inspection")
        )

        assert lease.status == LeaseState.UNMANAGED
        snapshot = _container_module.resolved_capacity_ledger_service.snapshot()
        assert snapshot[0]["available_units"] < snapshot[0]["value"]

    async def test_release_oversight_of_a_releasing_lease_is_a_conflict(
        self, client_and_queue
    ):
        clients, _ = client_and_queue
        reservation_id = _committed("0xoversight-releasing")
        _aggregate(reservation_id, SettlementRecordState.active.value, "fulfillment-ov")
        await clients.family.terminate_lease(reservation_id, LeaseTermination())

        with pytest.raises(ComputeProvisioningError) as refused:
            await clients.family.release_lease_oversight(
                reservation_id, LeaseReleaseOversight(reason="too late")
            )

        assert refused.value.status_code == 409

    async def test_retry_release_adopts_a_teardown_that_later_succeeded(
        self, client_and_queue
    ):
        clients, _ = client_and_queue
        reservation_id = _committed("0xretry")
        _aggregate(reservation_id, SettlementRecordState.active.value, "fulfillment-retry")
        await clients.family.terminate_lease(reservation_id, LeaseTermination())
        _set_aggregate("fulfillment-retry", SettlementRecordState.teardown_failed.value)
        await clients.family.check_leases()
        assert (await clients.family.get_lease(reservation_id)).status == (
            LeaseState.RELEASE_FAILED
        )

        _set_aggregate("fulfillment-retry", SettlementRecordState.torn_down.value)
        lease = await clients.family.retry_lease_release(reservation_id, LeaseRetryRelease())

        assert lease.status == LeaseState.RELEASED

    async def test_retry_release_of_a_lease_that_has_not_failed_is_a_conflict(
        self, client_and_queue
    ):
        clients, _ = client_and_queue
        reservation_id = _committed("0xretry-active")

        with pytest.raises(ComputeProvisioningError) as refused:
            await clients.family.retry_lease_release(reservation_id, LeaseRetryRelease())

        assert refused.value.status_code == 409

    async def test_the_release_controls_are_the_operator_s(self, client_and_queue, seller):
        reservation_id = _committed("0xcontrols")

        for call in (
            lambda: seller.retry_lease_release(reservation_id, LeaseRetryRelease()),
            lambda: seller.force_release_lease(
                reservation_id, LeaseForceRelease(reason="not mine")
            ),
            lambda: seller.release_lease_oversight(
                reservation_id, LeaseReleaseOversight(reason="not mine")
            ),
        ):
            with pytest.raises(ComputeProvisioningAuthenticationError):
                await call()

    async def test_force_release_frees_an_unmanaged_lease(self, client_and_queue):
        clients, _ = client_and_queue
        reservation_id = _committed("0xforce")
        _aggregate(reservation_id, SettlementRecordState.active.value, "fulfillment-force")
        await clients.family.release_lease_oversight(
            reservation_id, LeaseReleaseOversight(reason="manual inspection")
        )

        lease = await clients.family.force_release_lease(
            reservation_id, LeaseForceRelease(reason="host verified empty", evidence="console")
        )

        assert (lease.status, lease.failure_reason) == (
            LeaseState.FORCE_RELEASED,
            "admin_force_release",
        )
