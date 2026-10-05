"""Coverage for provisioning-client endpoints not exercised elsewhere.

These tests use the canonical typed clients against the in-process FastAPI app
with lower provisioning layers mocked by the integration fixture.  That keeps
the client wheel lightweight while making the service integration suite the
contract authority for every public client operation.
"""

from __future__ import annotations
from compute_provisioning_ansible import ssh_connection

from datetime import datetime, timezone

from arkhai_bare_metal import NODE_GRANT_ACCESS_ACTION
from bare_metal_provisioning_adapter.services.mock_output import bare_metal_mock_output
from compute_provisioning_ansible import MockAnsibleRunner
from compute_provisioning.jobs.db import JobRecord
from compute_provisioning_service import container as _container_module
import pytest

from vm_provisioning_operator.models import CreateVmRequest
from compute_provisioning_contracts import HostCreate


HOST = "kvm1"
VM_NAME = "agent-vm-01"


async def _register_host(client) -> None:
    await client.family.register_host(
        HostCreate(
            host_id=HOST,
            connection=ssh_connection(ssh_host="10.0.0.1", ssh_user="root", key_path="~/.ssh/id_ed25519"),
        )
    )


class TestVmClientEndpointCoverage:
    async def test_all_vm_operation_client_methods_submit_jobs(self, client_and_queue):
        client, _ = client_and_queue
        await _register_host(client)

        submissions = [
            await client.vm.list_vms(HOST),
            await client.vm.start_vm(HOST, VM_NAME),
            await client.vm.shutdown_vm(HOST, VM_NAME),
            await client.vm.reboot_vm(HOST, VM_NAME),
            await client.vm.destroy_vm(HOST, VM_NAME),
            await client.vm.undefine_vm(HOST, VM_NAME),
            await client.vm.monitor_vm(HOST, VM_NAME),
            await client.vm.reset_password(HOST, VM_NAME),
            await client.vm.check_capacity(HOST),
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

        result = await client.host_import.import_hosts_from_path(inventory, ssh_key_type="path")

        assert result.total == 1
        assert result.hosts[0].host_id == HOST


class TestJobClientEndpointCoverage:
    async def test_job_list_logs_and_cancel_use_client_contract(self, client_and_queue):
        client, _ = client_and_queue
        submit = await client.vm.create_vm(HOST, CreateVmRequest(vm_target=VM_NAME))

        jobs = await client.family.list_jobs(limit=5)
        assert jobs.total >= 1
        assert any(job.job_id == submit.job_id for job in jobs.jobs)

        logs = await client.family.get_job_logs(submit.job_id)
        assert logs.job_id == submit.job_id

        cancel = await client.family.cancel_job(submit.job_id)
        assert cancel["job_id"] == submit.job_id
        assert "status" in cancel

    async def test_the_job_list_reads_in_either_creation_order(self, client_and_queue):
        """Two jobs are given distinct creation times, since two submissions in
        quick succession may share one; the list then reads them in each order."""
        client, _ = client_and_queue
        older = await client.vm.create_vm(HOST, CreateVmRequest(vm_target="vm-older"))
        newer = await client.vm.create_vm(HOST, CreateVmRequest(vm_target="vm-newer"))
        with _container_module.resolved_session_factory() as db, db.begin():
            for job_id, minute in ((older.job_id, 1), (newer.job_id, 2)):
                db.get(JobRecord, job_id).created_at = datetime(
                    2026, 1, 1, 0, minute, tzinfo=timezone.utc
                )

        ascending = await client.family.list_jobs(sort="created_at_asc", limit=10)
        descending = await client.family.list_jobs(sort="created_at_desc", limit=10)

        ours = {older.job_id, newer.job_id}
        assert [j.job_id for j in ascending.jobs if j.job_id in ours] == [
            older.job_id,
            newer.job_id,
        ]
        assert [j.job_id for j in descending.jobs if j.job_id in ours] == [
            newer.job_id,
            older.job_id,
        ]


class TestSystemClientEndpointCoverage:
    async def test_lease_watchdog_pause_resume_use_client_contract(self, client_and_queue):
        client, _ = client_and_queue

        paused = await client.family.pause_lease_watchdog()
        resumed = await client.family.resume_lease_watchdog()

        assert paused["paused"] is True
        assert resumed["paused"] is False


class TestCapacityClientEndpointCoverage:
    async def test_capacity_read_and_truncate_methods_use_client_contract(self, client_and_queue):
        client, _ = client_and_queue
        ledger = _container_module.resolved_capacity_ledger_service
        ledger.register_resource(
            resource_id="compute-kvm1-001",
            total_units=8,
            host_id=HOST, attributes={},
            pool_id="default",
        )
        reserved = ledger.reserve(
            claim={
                "offering_mode": "vm",
                "gpu_count": 1,
                "host_id": HOST,
            },
            deal_ref={"escrow_uid": "escrow-client-capacity"},
        )
        assert reserved is not None
        committed = ledger.commit(
            capacity_reservation_id=reserved["capacity_reservation_id"],
            resource_id="compute-kvm1-001",
            lease_end_utc="2099-01-01T00:00:00+00:00",
        )
        assert committed is not None

        # An operator reads and truncates through the site client, signed as admin.
        snapshot = await client.site.snapshot()
        reservations = await client.site.list_reservations(escrow_uid="escrow-client-capacity")
        reservation = await client.site.get_reservation(reserved["capacity_reservation_id"])
        truncated = await client.site.truncate_lease(
            capacity_reservation_id=reserved["capacity_reservation_id"],
            lease_end_utc=datetime(2098, 12, 31, tzinfo=timezone.utc).isoformat(),
        )

        assert snapshot[0]["resource_id"] == "compute-kvm1-001"
        assert len(reservations) == 1
        assert reservation["capacity_reservation_id"] == reserved["capacity_reservation_id"]
        assert truncated["capacity_reservation_id"] == reserved["capacity_reservation_id"]


class TestBareMetalTestRouteCoverage:
    """Every ``/test/bare-metal`` route through its signed route contract.

    The integration test client signs each request by resolving the route
    contract, so a contract that no longer matches its mounted route, or an
    authorization that refuses the administrator, fails here.
    """

    @pytest.fixture
    def bare_metal_runner(self):
        return MockAnsibleRunner(default_output=bare_metal_mock_output)

    async def test_rule_and_evaluate_routes_use_their_route_contracts(
        self, test_client, bare_metal_runner
    ):
        _register_host_record("bm-node-1")

        added = await test_client.add_bare_metal_mock_rule(
            rule_id="coverage-gate",
            match={"action": NODE_GRANT_ACCESS_ACTION},
            pause_before_result=True,
        )
        listed = await test_client.list_bare_metal_mock_rules()
        evaluated = await test_client.evaluate_bare_metal_job(
            "bm-node-1", action=NODE_GRANT_ACCESS_ACTION
        )
        resumed = await test_client.resume_bare_metal_rule("coverage-gate")
        deleted = await test_client.delete_bare_metal_mock_rule("coverage-gate")

        assert added == {"rule_id": "coverage-gate", "status": "added"}
        assert [(rule["rule_id"], rule["waiting"]) for rule in listed] == [
            ("coverage-gate", 0)
        ]
        assert evaluated["rule_matched"] == "coverage-gate"
        assert evaluated["host_exists"] is True
        assert resumed == {"rule_id": "coverage-gate", "resumed": True}
        assert deleted == {"rule_id": "coverage-gate", "deleted": True}
        assert bare_metal_runner.list_rules() == []


def _register_host_record(host_id: str) -> None:
    _container_module.resolved_host_authority.register_host(
        HostCreate(
            host_id=host_id,
            connection=ssh_connection(ssh_host="192.0.2.10", ssh_user="root", key_path="/fake/id_ed25519"),
            gpu_count=0,
        )
    )
