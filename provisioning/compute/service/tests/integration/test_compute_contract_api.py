from datetime import datetime, timedelta, timezone

import pytest
from compute_provisioning.leases import lease_view as _lease_view
from httpx import ASGITransport

from compute_provisioning_service import container as _container_module
from compute_provisioning_client import (
    ComputeProvisioningClient,
    ComputeProvisioningError,
)
from compute_provisioning_contracts import LeaseState
from market_site.ledger import ALLOCATION_MODE_EXCLUSIVE

from compute_provisioning_service.main import app

from .conftest import SERVICE_AUTHORITIES, STOREFRONT_SIGNER


def _compute_provisioning_client(base_url: str, *, transport):
    return ComputeProvisioningClient(
        base_url,
        signer=STOREFRONT_SIGNER,
        caller_role="seller",
        expected_authorities=SERVICE_AUTHORITIES,
        transport=transport,
    )


def _leased_vm_reservation() -> dict:
    ledger = _container_module.resolved_capacity_ledger_service
    ledger.register_resource(
        resource_id="contract-kvm1",
        total_units=1,
        host_id="kvm1", attributes={},
        pool_id="default",
    )
    reserved = ledger.reserve(
        claim={"offering_mode": "vm"},
        deal_ref={"escrow_uid": "escrow-contract", "listing_id": "listing-1"},
        lease_duration_seconds=3600,
    )
    return ledger.commit(
        resource_id="contract-kvm1",
        capacity_reservation_id=reserved["capacity_reservation_id"],
        lease_end_utc=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        idempotency_ref="escrow-contract",
    )

def _leased_bare_metal_reservation() -> dict:
    ledger = _container_module.resolved_capacity_ledger_service
    ledger.register_resource(
        resource_id="contract-bare-metal-1",
        total_units=1,
        host_id="bm-contract-1", attributes={
            "physical_host_id": "physical-contract-1",
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE},
        pool_id="default",
    )
    reserved = ledger.reserve(
        claim={
            "offering_mode": "bare_metal",
            "physical_host_id": "physical-contract-1",
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
        },
        deal_ref={"escrow_uid": "escrow-bare-contract"},
        lease_duration_seconds=3600,
    )
    committed = ledger.commit(
        resource_id="contract-bare-metal-1",
        capacity_reservation_id=reserved["capacity_reservation_id"],
        lease_end_utc=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        idempotency_ref="escrow-bare-contract",
    )
    # The target is recorded as a fulfillment's activation records it.
    with _container_module.resolved_session_factory() as db:
        ledger.record_executor_target_in_session(
            db, committed["capacity_reservation_id"], "bm-contract-1"
        )
        db.commit()
    return ledger.get_reservation(committed["capacity_reservation_id"])




@pytest.mark.asyncio
async def test_a_lease_retains_its_action_target_alongside_the_mode(
    client_and_queue,
):
    """The `executor_` target is the abstraction's own, so the selector rename
    must not have reached it. Asserted on a committed reservation because a
    silent loss here would only surface at release time."""
    reservation = _leased_bare_metal_reservation()

    assert reservation["offering_mode"] == "bare_metal"
    assert reservation["executor_target"] == "bm-contract-1"


async def test_the_lease_view_serializes_every_reachable_reservation_state():
    """Every ``ReservationState`` member projects onto a ``LeaseState``, and a
    freshly registered lease, raw state ``"leased"``, reads as ``"active"``."""
    from market_site.db import ReservationState

    expected = {
        "reserved": LeaseState.PENDING,
        "provisioning": LeaseState.PENDING,
        "provisioning_failed": LeaseState.PROVISIONING_FAILED,
        "leased": LeaseState.ACTIVE,
        "releasing": LeaseState.RELEASING,
        "released": LeaseState.RELEASED,
        "release_failed": LeaseState.RELEASE_FAILED,
        "unmanaged": LeaseState.UNMANAGED,
        "force_released": LeaseState.FORCE_RELEASED,
    }
    assert {member.value for member in ReservationState} == set(expected)

    for raw_state, want in expected.items():
        view = _lease_view({
            "capacity_reservation_id": "reservation-1",
            "offering_mode": "vm",
            "state": raw_state,
            "lease_end_utc": "2099-01-01T00:00:00Z",
        })
        assert view.status == want, f"{raw_state!r} should map to {want!r}"


@pytest.mark.asyncio
def _create_fulfillment_aggregate(
    capacity_reservation_id: str,
    *,
    fulfillment_id: str,
    state: str = "active",
) -> None:
    """Persist a real `SettlementRecord` for the client-contract tests below.

    The original test only monkeypatched
    `FulfillmentOrchestrator.begin_fulfillment_teardown` and never
    exercised the real aggregate at all, so it could not have caught a
    routing, serialization, or state-machine regression in the endpoint
    itself -- only that the client reaches *some* handler. This helper
    lets the tests below drive the real orchestrator instead.
    """

    from market_fulfillment import SettlementRecord, SettlementRecordState

    session_factory = _container_module.resolved_session_factory
    with session_factory() as db:
        db.add(
            SettlementRecord(
                capacity_reservation_id=capacity_reservation_id,
                fulfillment_id=fulfillment_id,
                market="vms",
                scheduling_requirements={"resource_kind": "vm"},
                settlement_resource_id="kvm1",
                pool_id="pool-1",
                provider="ansible",
                resource_host_id="kvm1", resource_attributes={},
                fulfillment_request={
                    "kind": "vm.fulfillment.request",
                    "schema_version": 1,
                    "payload": {},
                },
                prepared_teardown_operation={
                    "kind": "vm.ansible.teardown.v1",
                    "schema_version": 1,
                    "payload": {},
                },
                provider_metadata={"current_job_id": "job-1"},
                state=getattr(SettlementRecordState, state).value,
            )
        )
        db.commit()


async def test_begin_fulfillment_teardown_client_drives_the_real_aggregate_idempotently(
    client_and_queue,
):
    reservation = _leased_vm_reservation()
    fulfillment_id = "fulfillment-client-teardown"
    _create_fulfillment_aggregate(
        reservation["capacity_reservation_id"], fulfillment_id=fulfillment_id,
    )

    async with _compute_provisioning_client("http://test", transport=ASGITransport(app=app)) as client:
        first = await client.begin_fulfillment_teardown(fulfillment_id)
        repeated = await client.begin_fulfillment_teardown(fulfillment_id)

    assert first.fulfillment_id == fulfillment_id
    assert first.state == "teardown_dispatch_pending"
    assert repeated.state == "teardown_dispatch_pending"

    from market_fulfillment import SettlementRecord

    with _container_module.resolved_session_factory() as db:
        record = db.get(SettlementRecord, reservation["capacity_reservation_id"])
        assert record.state == "teardown_dispatch_pending"


async def test_begin_fulfillment_teardown_client_maps_unknown_fulfillment_to_404(
    client_and_queue,
):
    async with _compute_provisioning_client("http://test", transport=ASGITransport(app=app)) as client:
        with pytest.raises(ComputeProvisioningError) as exc_info:
            await client.begin_fulfillment_teardown("no-such-fulfillment")

    assert exc_info.value.status_code == 404


async def test_begin_fulfillment_teardown_client_maps_non_active_aggregate_to_409(
    client_and_queue,
):
    reservation = _leased_vm_reservation()
    fulfillment_id = "fulfillment-client-conflict"
    _create_fulfillment_aggregate(
        reservation["capacity_reservation_id"],
        fulfillment_id=fulfillment_id,
        state="failed",
    )

    async with _compute_provisioning_client("http://test", transport=ASGITransport(app=app)) as client:
        with pytest.raises(ComputeProvisioningError) as exc_info:
            await client.begin_fulfillment_teardown(fulfillment_id)

    assert exc_info.value.status_code == 409


