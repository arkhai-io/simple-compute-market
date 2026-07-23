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

    async with ComputeProvisioningClient(
        "http://test", transport=ASGITransport(app=app)
    ) as client:
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
async def test_contract_idempotency_key_rejects_changed_command(client_and_queue):
    legacy_client, _ = client_and_queue
    await legacy_client.register_host(HostCreate(
        name="kvm1",
        kvm_host="127.0.0.1",
        ssh_user="ubuntu",
        ssh_key_type="path",
        ssh_key_value="/tmp/test-key",
    ))
    reservation = _leased_vm_reservation()

    async with ComputeProvisioningClient(
        "http://test", transport=ASGITransport(app=app)
    ) as client:
        await client.submit_action(_vm_action(reservation))
        with pytest.raises(ComputeProvisioningError) as raised:
            await client.submit_action(
                _vm_action(
                    reservation,
                    parameters={
                        "vm_target": "different-target",
                        "ssh_pubkey": "ssh-ed25519 test",
                    },
                )
            )

    assert raised.value.status_code == 422
    assert "different executor command" in str(raised.value)


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

    async with ComputeProvisioningClient(
        "http://test", transport=ASGITransport(app=app)
    ) as client:
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
    async with ComputeProvisioningClient(
        "http://test", transport=ASGITransport(app=app)
    ) as client:
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

    async with ComputeProvisioningClient(
        "http://test", transport=ASGITransport(app=app)
    ) as client:
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
