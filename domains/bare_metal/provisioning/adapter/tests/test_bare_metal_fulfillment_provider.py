from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from arkhai_bare_metal import BARE_METAL_OFFERING_MODE, NODE_GRANT_ACCESS_ACTION
from market_fulfillment import (
    ProviderConfigInvalidError,
    ProviderOperationState,
    SettlementResource,
    SettlementResult,
    VersionedEnvelope,
)

from vm_provisioning_adapter.models.jobs_model import AnsibleJobParams
from vm_provisioning_adapter.services.job_service import AnsibleJobService

from bare_metal_provisioning_adapter.services.bare_metal_fulfillment_provider import (
    BareMetalFulfillmentProvider,
)
from bare_metal_provisioning_adapter.services.bare_metal_mock_executor import (
    BareMetalMockAnsibleService,
)


class FakeOperations:
    def __init__(self) -> None:
        self.create = []
        self.teardown = []

    async def grant_access(self, lease, *, contract=None):
        self.create.append((lease, contract))
        return SimpleNamespace(job_id="job-create")

    async def reclaim_access(self, reservation, *, contract=None):
        self.teardown.append((reservation, contract))
        return SimpleNamespace(job_id="job-teardown")


class FakeJobs:
    def __init__(self) -> None:
        self.jobs = {
            "job-create": SimpleNamespace(
                status="succeeded",
                error=None,
                result={
                    "tenant_user": None,
                    "host": "203.0.113.25",
                    "ssh_port": None,
                    "timestamp": "2030-01-01T00:00:01Z",
                    "result_message": "access granted",
                    "authentication": {"private_key": "must-not-escape"},
                    "ansible_result": {
                        "action": "node_grant_access",
                        "host": "203.0.113.25",
                        "port": 2222,
                        "ssh_user": "buyer",
                        "status": "success",
                        "timestamp": "2030-01-01T00:00:01Z",
                    },
                },
            ),
            "job-teardown": SimpleNamespace(
                status="succeeded",
                error=None,
                result={"result_message": "access reclaimed"},
            ),
        }

    def get_job(self, job_id):
        return self.jobs[job_id]


def _resource() -> SettlementResource:
    return SettlementResource(
        offering_mode=BARE_METAL_OFFERING_MODE,
        settlement_resource_id="resource-1",
        pool_id="pool-1",
        resource_kind="compute.bare-metal",
        provider="bare_metal.ansible",
        host_id="machine-1",
        attributes={
            "physical_host_id": "physical-host-1",
            "bare_metal_publication": {"enabled": True},
        },
    )


def _request(*, host_id: str = "machine-1") -> VersionedEnvelope:
    return VersionedEnvelope(
        kind="bare_metal.v2",
        schema_version=1,
        payload={
            "kind": "bare_metal.v2",
            "escrow_uid": "escrow-1",
            "host_id": host_id,
            "physical_host_id": "physical-host-1",
            "lease_start_utc": "2030-01-01T00:00:00Z",
            "lease_end_utc": "2030-01-02T00:00:00Z",
            "access_method": "ssh",
            "ssh_public_key": "ssh-ed25519 buyer",
        },
    )


def _provider() -> tuple[BareMetalFulfillmentProvider, FakeOperations]:
    operations = FakeOperations()
    return (
        BareMetalFulfillmentProvider(
            operations_service=operations,
            job_service=FakeJobs(),
        ),
        operations,
    )


@pytest.mark.asyncio
async def test_selected_resource_drives_idempotent_grant_result_and_teardown():
    provider, operations = _provider()
    resource = _resource()
    prepared = provider.prepare_create(
        capacity_reservation_id="reservation-1",
        request=_request(),
        resource=resource,
        pool_config={},
    )

    created = await provider.dispatch_create(prepared)
    lease, create_contract = operations.create[0]
    assert lease.host_id == "machine-1"
    assert lease.physical_host_id == "physical-host-1"
    assert create_contract.idempotency_key == "reservation-1:grant-access"
    assert provider.resolve_provisioned_resources(created.provider_metadata) == (
        "physical-host-1",
    )
    assert (
        await provider.get_status(
            "reservation-1",
            resource,
            created.provider_metadata,
        )
    ).state is ProviderOperationState.succeeded

    public_result = await provider.fetch_credentials(created.provider_metadata, ())
    assert public_result.payload == {
        "kind": "bare_metal.v2",
        "action": "node_grant_access",
        "host_id": "machine-1",
        "physical_host_id": "physical-host-1",
        "ssh_user": "buyer",
        "host": "203.0.113.25",
        "port": 2222,
        "escrow_uid": "escrow-1",
        "access_grant_ref": "job-create",
        "lease_expires_at": "2030-01-02T00:00:00Z",
        "timestamp": "2030-01-01T00:00:01Z",
        "status": "success",
        "details": {"result_message": "access granted"},
    }
    assert "authentication" not in str(public_result.payload)
    assert "ssh_public_key" not in str(public_result.payload)

    teardown = provider.prepare_teardown(
        SettlementResult(
            capacity_reservation_id="reservation-1",
            fulfillment_id="fulfillment-1",
            resource=resource,
            provisioned_resources=(),
            provider_metadata=created.provider_metadata,
        ),
        {},
    )
    torn_down = await provider.dispatch_teardown(teardown)
    reservation, teardown_contract = operations.teardown[0]
    assert reservation["executor_target"] == "machine-1"
    assert reservation["executor_ref"] == {
        "physical_host_id": "physical-host-1",
        "ssh_public_key": "ssh-ed25519 buyer",
        "access_method": "ssh",
        "ssh_user": "arkhai-e726d1da85038f5c",
    }
    assert reservation["access_ref"] == lease.access_ref
    assert teardown_contract.idempotency_key == "reservation-1:reclaim-access"
    assert torn_down.provider_metadata["current_job_id"] == "job-teardown"


def test_buyer_payload_cannot_replace_selected_machine():
    provider, _ = _provider()
    with pytest.raises(
        ProviderConfigInvalidError,
        match="host_id does not match the selected resource",
    ):
        provider.prepare_create(
            capacity_reservation_id="reservation-1",
            request=_request(host_id="attacker-machine"),
            resource=_resource(),
            pool_config={},
        )


async def _mock_grant_job_result() -> dict:
    """The result a grant job records when the bare-metal mock runs it.

    The mock's default output is parsed by the real result parser and stored
    through the job service's result payload, exactly as the job service does
    for any run, so this is what the provider reads after a mock-profile grant.
    """
    host = SimpleNamespace(
        host_id="machine-1",
        ssh_host="198.51.100.7",
        ssh_port=2201,
        public_host="203.0.113.7",
    )
    params = AnsibleJobParams(
        host_id="machine-1",
        vm_action=NODE_GRANT_ACCESS_ACTION,
        offering_mode=BARE_METAL_OFFERING_MODE,
        executor_action=NODE_GRANT_ACCESS_ACTION,
        physical_host_id="physical-host-1",
        escrow_uid="escrow-1",
        ssh_user="tenant-a",
    )
    mock = BareMetalMockAnsibleService(MagicMock())
    mock.write_inventory([host])
    run = mock.start_playbook(
        playbook_path=Path("/playbooks/node-access.yaml"),
        inventory_path=Path("/tmp/inventory"),
        extra_vars_path=Path("/tmp/vars"),
        limit=params.host_id,
    )
    run._params = params
    output = await mock.wait_for_playbook(run, timeout_seconds=5)
    run_result = mock.parse_playbook_result(
        output, params, tenant_address=host.public_host
    )
    job_service = AnsibleJobService(
        settings=MagicMock(),
        session_factory=MagicMock(),
        executors=MagicMock(),
        host_service=MagicMock(),
    )
    return job_service._build_result_payload(run_result)


@pytest.mark.asyncio
async def test_a_mock_profile_grant_reads_as_the_buyers_access_result():
    jobs = FakeJobs()
    jobs.jobs["job-create"] = SimpleNamespace(
        status="succeeded", error=None, result=await _mock_grant_job_result()
    )
    provider = BareMetalFulfillmentProvider(
        operations_service=FakeOperations(), job_service=jobs
    )
    created = await provider.dispatch_create(
        provider.prepare_create(
            capacity_reservation_id="reservation-1",
            request=_request(),
            resource=_resource(),
            pool_config={},
        )
    )

    result = await provider.fetch_credentials(created.provider_metadata, ())

    payload = result.payload
    assert payload["action"] == NODE_GRANT_ACCESS_ACTION
    assert payload["host_id"] == "machine-1"
    assert payload["physical_host_id"] == "physical-host-1"
    assert payload["ssh_user"] == "tenant-a"
    assert payload["host"] == "198.51.100.7"
    assert payload["port"] == 2201
    assert payload["access_grant_ref"] == "job-create"
    assert payload["status"] == "success"
    assert payload["timestamp"]
