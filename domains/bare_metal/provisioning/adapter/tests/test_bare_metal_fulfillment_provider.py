from __future__ import annotations

from types import SimpleNamespace

import pytest
from arkhai_bare_metal import BARE_METAL_EXECUTOR_KIND
from market_fulfillment import (
    ProviderConfigInvalidError,
    ProviderOperationState,
    SettlementResource,
    SettlementResult,
    VersionedEnvelope,
)

from bare_metal_provisioning_adapter.services.bare_metal_fulfillment_provider import (
    BareMetalFulfillmentProvider,
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
                    "tenant_user": "buyer",
                    "host": "203.0.113.25",
                    "port": "2222",
                    "timestamp": "2030-01-01T00:00:01Z",
                    "result_message": "access granted",
                    "authentication": {"private_key": "must-not-escape"},
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
        executor_kind=BARE_METAL_EXECUTOR_KIND,
        settlement_resource_id="resource-1",
        pool_id="pool-1",
        resource_kind="compute.bare-metal",
        provider="bare_metal.ansible",
        attributes={
            "machine_id": "machine-1",
            "physical_host_id": "physical-host-1",
        },
    )


def _request(*, machine_id: str = "machine-1") -> VersionedEnvelope:
    return VersionedEnvelope(
        kind="bare_metal.v1",
        schema_version=1,
        payload={
            "kind": "bare_metal.v1",
            "escrow_uid": "escrow-1",
            "machine_id": machine_id,
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
    assert lease.machine_id == "machine-1"
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
        "kind": "bare_metal.v1",
        "action": "node_grant_access",
        "machine_id": "machine-1",
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
    assert reservation["executor_ref"]["physical_host_id"] == "physical-host-1"
    assert teardown_contract.idempotency_key == "reservation-1:reclaim-access"
    assert torn_down.provider_metadata["current_job_id"] == "job-teardown"


def test_buyer_payload_cannot_replace_selected_machine():
    provider, _ = _provider()
    with pytest.raises(
        ProviderConfigInvalidError,
        match="machine_id does not match the selected resource",
    ):
        provider.prepare_create(
            capacity_reservation_id="reservation-1",
            request=_request(machine_id="attacker-machine"),
            resource=_resource(),
            pool_config={},
        )
