from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bare_metal_provisioning_adapter.services.ansible_fulfillment_provider import (
    BareMetalAnsibleFulfillmentProvider,
)
from market_fulfillment import (
    ProviderConfigInvalidError,
    ProviderOperationState,
    SettlementResource,
    VersionedEnvelope,
)


def _resource(**overrides) -> SettlementResource:
    values = {
        "settlement_resource_id": "resource-1",
        "pool_id": "pool-1",
        "resource_kind": "bare_metal",
        "provider": "ansible",
        "attributes": {
            "bare_metal_publication": {
                "machine_id": "machine-1",
                "physical_host_id": "host-1",
            }
        },
    }
    values.update(overrides)
    return SettlementResource(**values)


def _request() -> VersionedEnvelope:
    return VersionedEnvelope(
        kind="bare_metal.v1",
        schema_version=1,
        payload={
            "duration_seconds": 3600,
            "access_method": "ssh",
            "ssh_public_key": "ssh-ed25519 AAAA",
        },
    )


@pytest.fixture
def job_service():
    service = MagicMock()
    service.reserved_var_keys.return_value = set()
    service.submit = AsyncMock(return_value=SimpleNamespace(job_id="job-1"))
    service.get_job.return_value = SimpleNamespace(status="succeeded", error=None)
    return service


@pytest.fixture
def pool_service():
    service = MagicMock()
    service.get_pool.return_value = SimpleNamespace(
        enabled=True,
        provider="ansible",
        provider_config={
            "playbook_path": "playbooks/bare-metal.yaml",
            "extra_vars": {"tenant_group": "customers"},
        },
    )
    return service


@pytest.fixture
def provider(job_service, pool_service):
    return BareMetalAnsibleFulfillmentProvider(
        job_service=job_service,
        resource_pool_service=pool_service,
        job_queue_provider=lambda: object(),
    )


def test_prepare_snapshots_selected_machine_and_pool_configuration(provider):
    prepared = provider.prepare_create("reservation-1", _request(), _resource())

    assert prepared.kind == "ansible.bare_metal.create"
    params = prepared.payload["job_params"]
    assert params["vm_host"] == "machine-1"
    assert params["physical_host_id"] == "host-1"
    assert params["ssh_public_key"] == "ssh-ed25519 AAAA"
    assert params["playbook_path"] == "playbooks/bare-metal.yaml"
    assert params["provider_extra_vars"] == {"tenant_group": "customers"}
    contract = prepared.payload["contract"]
    assert contract["idempotency_key"] == (
        "reservation-1:fulfillment_create:v1"
    )
    assert contract["parameters"] == params


@pytest.mark.asyncio
async def test_dispatch_uses_snapshot_without_rereading_pool(
    provider, job_service, pool_service
):
    prepared = provider.prepare_create("reservation-1", _request(), _resource())
    pool_service.reset_mock()

    result = await provider.dispatch_create(prepared)

    pool_service.get_pool.assert_not_called()
    submitted = job_service.submit.await_args.args[0]
    assert dataclasses.asdict(submitted) == prepared.payload["job_params"]
    assert result.provisioned_resource_refs == ("machine-1",)
    assert result.provider_metadata["current_job_id"] == "job-1"


def test_provider_rejects_non_bare_metal_resource(provider):
    with pytest.raises(ProviderConfigInvalidError, match="resource_kind"):
        provider.prepare_create(
            "reservation-1",
            _request(),
            _resource(resource_kind="compute.gpu"),
        )


def test_teardown_preserves_selected_identity(provider):
    create = provider.prepare_create("reservation-1", _request(), _resource())
    metadata = {
        "create_job_id": "job-1",
        "current_job_id": "job-1",
        "machine_id": "machine-1",
        "physical_host_id": "host-1",
        "operation": "create",
        "teardown_job_id": None,
    }

    teardown = provider.prepare_teardown(
        "reservation-1", _resource(), metadata
    )

    assert teardown.kind == "ansible.bare_metal.teardown"
    assert teardown.payload["job_params"]["vm_action"] == "node_reclaim_access"
    assert teardown.payload["contract"]["idempotency_key"] == (
        "reservation-1:fulfillment_teardown:v1"
    )


@pytest.mark.asyncio
async def test_status_is_normalized(provider):
    status = await provider.get_status(
        "reservation-1",
        _resource(),
        {
            "create_job_id": "job-1",
            "current_job_id": "job-1",
            "machine_id": "machine-1",
            "physical_host_id": "host-1",
            "operation": "create",
        },
    )
    assert status.state is ProviderOperationState.succeeded
