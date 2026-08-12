from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport

from compute_provisioning_service import container as _container_module
from compute_provisioning import (
    ComputeProvisioningClient,
    ComputeProvisioningError,
    ExecutorActionEnvelope,
)
from arkhai_bare_metal import NODE_GRANT_ACCESS_ACTION
from market_site.ledger import ALLOCATION_MODE_EXCLUSIVE

from compute_provisioning_service.main import app
from vm_provisioning_adapter.services.ansible_service import AnsibleError

from vm_provisioning_operator.models import HostCreate
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
        attributes={"vm_host": "kvm1"},
    )
    reserved = ledger.reserve(
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
        attributes={
            "machine_id": "bm-contract-1",
            "physical_host_id": "physical-contract-1",
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
        },
    )
    reserved = ledger.reserve(
        claim={
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
    return app.container.site_authority().update_reservation_fields(
        capacity_reservation_id=committed["capacity_reservation_id"],
        executor_kind="bare_metal",
        executor_target="bm-contract-1",
        executor_ref={"physical_host_id": "physical-contract-1"},
    )




def _vm_action(reservation: dict, **overrides) -> ExecutorActionEnvelope:
    values = {
        "capacity_reservation_id": reservation["capacity_reservation_id"],
        "deal_ref": reservation["deal_ref"],
        "executor_kind": "vm",
        "action_kind": "create",
        "idempotency_key": "create-contract-vm",
        "parameters": {"vm_target": "tenant-contract", "ssh_pubkey": "ssh-ed25519 test"},
    }
    values.update(overrides)
    return ExecutorActionEnvelope(**values)


@pytest.mark.asyncio
async def test_contract_submission_is_idempotent_and_correlated(client_and_queue):
    legacy_client, _ = client_and_queue
    await legacy_client.register_host(HostCreate(
        name="kvm1",
        kvm_host="127.0.0.1",
        ssh_user="ubuntu",
        ssh_key_type="path",
        ssh_key_value="/tmp/test-key",
    ))
    reservation = _leased_vm_reservation()

    async with _compute_provisioning_client("http://test", transport=ASGITransport(app=app)) as client:
        first = await client.submit_action(_vm_action(reservation))
        duplicate = await client.submit_action(_vm_action(reservation))
        job = await client.poll_until_complete(first.job_id, timeout=5, poll_interval=0.01)
        credentials = await client.get_job_credentials(first.job_id)

    assert duplicate.job_id == first.job_id
    assert job.capacity_reservation_id == reservation["capacity_reservation_id"]
    assert job.deal_ref["escrow_uid"] == "escrow-contract"
    assert job.executor_kind == "vm"
    assert job.action_kind == "create"
    assert job.result is not None and job.result.result_kind == "vm_create"
    assert {credential.credential_kind for credential in credentials} == {"root", "tenant"}


@pytest.mark.asyncio
async def test_bare_metal_uses_same_executor_neutral_client(client_and_queue):
    legacy_client, _ = client_and_queue
    await legacy_client.register_host(HostCreate(
        name="bm-contract-1",
        kvm_host="192.0.2.10",
        ssh_user="root",
        ssh_key_type="path",
        ssh_key_value="/tmp/test-key",
    ))
    reservation = _leased_bare_metal_reservation()
    action = ExecutorActionEnvelope(
        capacity_reservation_id=reservation["capacity_reservation_id"],
        deal_ref=reservation["deal_ref"],
        executor_kind="bare_metal",
        action_kind=NODE_GRANT_ACCESS_ACTION,
        idempotency_key="grant-contract-bare-metal",
        parameters={"access_ref": {"ssh_user": "tenant"}},
    )

    async with _compute_provisioning_client("http://test", transport=ASGITransport(app=app)) as client:
        accepted = await client.submit_action(action)
        job = await client.poll_until_complete(
            accepted.job_id, timeout=5, poll_interval=0.01
        )

    assert job.capacity_reservation_id == reservation["capacity_reservation_id"]
    assert job.executor_kind == "bare_metal"
    assert job.action_kind == NODE_GRANT_ACCESS_ACTION
    assert job.result is not None
    assert job.result.result_kind == "bare_metal_access"


@pytest.mark.asyncio
async def test_executor_mismatch_fails_before_job_submission(client_and_queue):
    reservation = _leased_vm_reservation()
    async with _compute_provisioning_client("http://test", transport=ASGITransport(app=app)) as client:
        with pytest.raises(ComputeProvisioningError) as exc_info:
            await client.submit_action(_vm_action(reservation, executor_kind="bare_metal"))
    assert exc_info.value.status_code == 409
    assert "reservation executor is 'vm'" in str(exc_info.value)


@pytest.mark.asyncio
async def test_terminal_executor_error_uses_structured_contract_envelope(
    client_and_queue, fake_ansible
):
    legacy_client, _ = client_and_queue
    await legacy_client.register_host(HostCreate(
        name="kvm1",
        kvm_host="127.0.0.1",
        ssh_user="ubuntu",
        ssh_key_type="path",
        ssh_key_value="/tmp/test-key",
    ))
    fake_ansible.wait_for_playbook.side_effect = AnsibleError(
        "executor exploded", "", ""
    )
    reservation = _leased_vm_reservation()
    action = _vm_action(
        reservation,
        idempotency_key="terminal-error-contract",
        parameters={
            "vm_target": "tenant-error",
            "ssh_pubkey": "ssh-ed25519 test",
            "max_retries": 0,
        },
    )

    async with _compute_provisioning_client("http://test", transport=ASGITransport(app=app)) as client:
        accepted = await client.submit_action(action)
        job = await client.get_job(accepted.job_id)

    assert job.status.value == "failed"
    assert job.error is not None
    assert job.error.code == "executor_error"
    assert "executor exploded" in job.error.message
    assert job.error.retryable is False


@pytest.mark.asyncio
async def test_unsupported_contract_major_reports_supported_version(client_and_queue):
    reservation = _leased_vm_reservation()
    transport = ASGITransport(app=app)
    async with __import__("httpx").AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/actions",
            json={
                **_vm_action(reservation).model_dump(mode="json"),
                "contract_version": "2.0",
            },
        )
    assert response.status_code == 422
    assert "supported majors: 1" in response.text


async def test_contract_lease_view_serializes_every_reachable_reservation_state():
    """`_lease_view`'s `status=str(reservation.get("state"))`
    passed market_site's raw `ReservationState` values straight through
    into `LeaseView.status: LeaseState`, whose members didn't cover them
    -- most immediately, a freshly-registered lease is always raw state
    `"leased"`, which `LeaseState` didn't have at all, so
    `ComputeProvisioningClient.register_lease` (what the VM storefront
    actually calls) failed with a 422 on every call. Confirms every
    `ReservationState` member now round-trips through `_lease_view` into a
    valid `LeaseState`, and specifically that `"leased"` maps to
    `"active"`, matching `leases_controller._LEASE_STATUS`'s mapping for
    the VM-domain-branded lease surface.
    """
    from compute_provisioning.contracts import LeaseState
    from compute_provisioning_service.controllers.compute_contract_controller import (
        _lease_view,
    )
    from vm_provisioning_adapter.controllers.leases_controller import (
        _lease_view as _vm_lease_view,
    )
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
            "state": raw_state,
            "lease_end_utc": "2099-01-01T00:00:00Z",
        })
        assert view.status == want, f"{raw_state!r} should map to {want!r}"
        vm_view = _vm_lease_view({
            "capacity_reservation_id": "reservation-1",
            "resource_id": "resource-1",
            "state": raw_state,
            "lease_end_utc": "2099-01-01T00:00:00Z",
        })
        assert vm_view.status == want.value


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
                resource_attributes={"vm_host": "kvm1"},
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


async def test_contract_register_lease_never_sends_executor_ref_and_it_self_heals(
    client_and_queue,
):
    """The generic `/contract/leases` path -- the one
    `ComputeProvisioningClient.register_lease` and the VM storefront
    actually use, distinct from the VM-domain-branded `/leases` surface --
    has no `executor_ref` field on its request contract at all. Confirms
    that omission is harmless: `executor_ref` is expected to self-heal in
    `market_site.ledger._sync_executor_fields` from the `vm_host` already
    set on the reservation at commit time, and `executor_target` (backing
    `vm_target`, which has no independent write path) is retained exactly
    as sent.
    """
    from compute_provisioning import LeaseRegistration

    reservation = _leased_vm_reservation()
    transport = ASGITransport(app=app)
    async with _compute_provisioning_client("http://test", transport=transport) as client:
        registration = LeaseRegistration(
            capacity_reservation_id=reservation["capacity_reservation_id"],
            deal_ref={"escrow_uid": "escrow-contract"},
            executor_kind="vm",
            executor_target="tenant-self-heal",
            lease_end_utc=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        assert not hasattr(registration, "executor_ref")
        await client.register_lease(registration)

    ledger = _container_module.resolved_capacity_ledger_service
    row = ledger.get_reservation(reservation["capacity_reservation_id"])
    assert row["vm_target"] == "tenant-self-heal"
    assert row["executor_ref"] == {"vm_host": "kvm1"}
