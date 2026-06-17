"""Coverage for provisioning-client endpoints not exercised elsewhere.

These tests use the public ProvisioningClient against the in-process FastAPI app
with lower provisioning layers mocked by the integration fixture.  That keeps
the client wheel lightweight while making the service integration suite the
contract authority for every public client operation.
"""

from __future__ import annotations

from datetime import datetime, timezone

import container as _container_module
import pytest

from provisioning_client.models import CreateVmRequest, HostCreate


HOST = "kvm1"
VM_NAME = "agent-vm-01"


async def _register_host(client) -> None:
    await client.register_host(
        HostCreate(
            name=HOST,
            kvm_host="10.0.0.1",
            ssh_user="root",
            ssh_key_value="~/.ssh/id_ed25519",
        )
    )


class TestVmClientEndpointCoverage:
    async def test_all_vm_operation_client_methods_submit_jobs(self, client_and_queue):
        client, _ = client_and_queue
        await _register_host(client)

        submissions = [
            await client.list_vms(HOST),
            await client.start_vm(HOST, VM_NAME),
            await client.shutdown_vm(HOST, VM_NAME),
            await client.reboot_vm(HOST, VM_NAME),
            await client.destroy_vm(HOST, VM_NAME),
            await client.undefine_vm(HOST, VM_NAME),
            await client.monitor_vm(HOST, VM_NAME),
            await client.reset_password(HOST, VM_NAME),
            await client.check_capacity(HOST),
        ]

        assert all(submit.status == "queued" for submit in submissions)
        assert all(submit.job_id for submit in submissions)


class TestHostClientEndpointCoverage:
    async def test_import_hosts_from_path_uses_client_contract(self, client_and_queue, tmp_path):
        client, _ = client_and_queue
        inventory = tmp_path / "hosts.ini"
        inventory.write_text(
            "[kvm_hosts]\n"
            "kvm1 ansible_host=10.0.0.1 ansible_user=root "
            "ansible_ssh_private_key_file=~/.ssh/id_ed25519\n"
        )

        result = await client.import_hosts_from_path(inventory, ssh_key_type="path")

        assert result.total == 1
        assert result.hosts[0].name == HOST


class TestJobClientEndpointCoverage:
    async def test_job_list_logs_and_cancel_use_client_contract(self, client_and_queue):
        client, _ = client_and_queue
        submit = await client.create_vm(HOST, CreateVmRequest(vm_target=VM_NAME))

        jobs = await client.list_jobs(limit=5)
        assert jobs.total >= 1
        assert any(job.job_id == submit.job_id for job in jobs.jobs)

        logs = await client.get_job_logs(submit.job_id)
        assert logs.job_id == submit.job_id

        cancel = await client.cancel_job(submit.job_id)
        assert cancel["job_id"] == submit.job_id
        assert "status" in cancel


class TestSystemClientEndpointCoverage:
    async def test_lease_watchdog_pause_resume_use_client_contract(self, client_and_queue):
        client, _ = client_and_queue

        paused = await client.pause_lease_watchdog()
        resumed = await client.resume_lease_watchdog()

        assert paused["paused"] is True
        assert resumed["paused"] is False


class TestCapacityClientEndpointCoverage:
    async def test_capacity_read_and_truncate_methods_use_client_contract(self, client_and_queue):
        client, _ = client_and_queue
        ledger = _container_module.resolved_capacity_ledger_service
        ledger.register_resource(
            resource_id="compute-kvm1-001",
            total_units=8,
            attributes={"vm_host": HOST},
        )
        reserved = ledger.reserve(
            claim={"gpu_count": 1},
            deal_ref={"escrow_uid": "escrow-client-capacity"},
        )
        assert reserved is not None
        committed = ledger.commit(
            allocation_id=reserved["allocation_id"],
            resource_id=reserved["resource_id"],
            lease_end_utc="2099-01-01T00:00:00+00:00",
        )
        assert committed is not None

        snapshot = await client.capacity_snapshot()
        allocations = await client.list_capacity_allocations(
            escrow_uid="escrow-client-capacity"
        )
        allocation = await client.get_capacity_allocation(reserved["allocation_id"])
        truncated = await client.truncate_capacity_lease(
            reserved["allocation_id"],
            datetime(2099, 1, 2, tzinfo=timezone.utc).isoformat(),
        )

        assert snapshot[0]["resource_id"] == "compute-kvm1-001"
        assert allocations["total"] == 1
        assert allocation["allocation_id"] == reserved["allocation_id"]
        assert truncated["allocation_id"] == reserved["allocation_id"]


class TestLeaseClientEndpointCoverage:
    async def test_terminate_lease_uses_client_contract(self, client_and_queue):
        client, _ = client_and_queue
        ledger = _container_module.resolved_capacity_ledger_service
        if "compute-kvm1-001" not in {r["resource_id"] for r in ledger.list_resources()}:
            ledger.register_resource(
                resource_id="compute-kvm1-001",
                total_units=8,
                attributes={"vm_host": HOST},
            )
        reserved = ledger.reserve(
            claim={"gpu_count": 1},
            deal_ref={"escrow_uid": "escrow-client-terminate"},
        )
        assert reserved is not None

        lease = await client.register_lease(
            resource_id=reserved["resource_id"],
            allocation_id=reserved["allocation_id"],
            escrow_uid="escrow-client-terminate",
            vm_host=HOST,
            vm_target=VM_NAME,
            lease_end_utc=datetime(2099, 1, 1, tzinfo=timezone.utc),
        )

        terminated = await client.terminate_lease(lease["id"], reason="client coverage")

        assert terminated["id"] == lease["id"]
        assert terminated["status"] == "releasing"
