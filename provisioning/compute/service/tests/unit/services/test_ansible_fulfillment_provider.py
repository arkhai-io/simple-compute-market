"""Unit tests for the Ansible fulfillment adapter boundary."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from market_fulfillment import (
    FulfillmentStatusFailedError,
    ProviderConfigInvalidError,
    ProviderOperationState,
    SettlementResource,
    SettlementResult,
    VersionedEnvelope,
)
from vm_provisioning_adapter.models.jobs_model import AnsibleJobParams
from vm_provisioning_adapter.services.ansible_fulfillment_provider import (
    AnsibleFulfillmentProvider,
)
from vm_provisioning_adapter.services.ansible_service import AnsibleService


def _request() -> VersionedEnvelope[dict]:
    return VersionedEnvelope(
        kind="vm.fulfillment.request",
        schema_version=1,
        payload={
            "capacity_reservation_id": "alloc-1",
            "vm_target": "vm-alloc-1",
            "vm_ram": 4096,
            "vm_vcpus": 2,
            "vm_disk_size": "40G",
            "ssh_pubkey": "ssh-ed25519 AAAA",
        },
    )


def _resource(**overrides) -> SettlementResource:
    values = {
        "settlement_resource_id": "kvm1",
        "pool_id": "pool-1",
        "resource_kind": "vm",
        "provider": "ansible",
        "attributes": {"vm_host": "kvm1"},
    }
    values.update(overrides)
    return SettlementResource(**values)


def _pool_config(**overrides) -> dict:
    values = {"playbook_path": "playbooks/vm-operations.yaml", "extra_vars": {}}
    values.update(overrides)
    return values


def _metadata(**overrides) -> dict:
    values = {
        "create_job_id": "job-1",
        "current_job_id": "job-1",
        "vm_host": "kvm1",
        "vm_target": "vm-alloc-1",
        "operation": "create",
    }
    values.update(overrides)
    return values


def _settlement_result(**overrides) -> SettlementResult:
    values = {
        "capacity_reservation_id": "alloc-1",
        "fulfillment_id": "fulfillment-1",
        "resource": _resource(),
        "provisioned_resources": (),
        "provider_metadata": _metadata(),
    }
    values.update(overrides)
    return SettlementResult(**values)


@pytest.fixture
def job_service():
    service = MagicMock()
    service.submit = AsyncMock(return_value=SimpleNamespace(job_id="job-1", status="queued"))
    service.reserved_var_keys = AnsibleService(settings=MagicMock()).reserved_var_keys
    return service


@pytest.fixture
def provider(job_service):
    return AnsibleFulfillmentProvider(
        job_service=job_service,
        job_queue_provider=lambda: MagicMock(),
    )


class TestCreate:
    async def test_prepare_is_side_effect_free_and_dispatch_submits(self, provider, job_service):
        prepared = provider.prepare_create(_request(), _resource(), _pool_config())
        job_service.submit.assert_not_awaited()

        result = await provider.dispatch_create(prepared)

        assert result.provider_metadata["create_job_id"] == "job-1"
        assert result.provider_metadata["vm_target"] == "vm-alloc-1"
        job_service.submit.assert_awaited_once()

    async def test_prepare_snapshots_pool_config_into_job_params(self, provider, job_service):
        prepared = provider.prepare_create(
            _request(),
            _resource(),
            _pool_config(
                playbook_path="playbooks/custom.yaml",
                extra_vars={"region": "eu"},
            ),
        )
        await provider.dispatch_create(prepared)

        submitted_params: AnsibleJobParams = job_service.submit.await_args.args[0]
        assert submitted_params.playbook_path == "playbooks/custom.yaml"
        assert submitted_params.provider_extra_vars == {"region": "eu"}

    def test_missing_playbook_path_raises_provider_config_invalid(self, provider):
        with pytest.raises(ProviderConfigInvalidError):
            provider.prepare_create(_request(), _resource(), {"extra_vars": {}})


class TestTeardown:
    async def test_prepare_is_side_effect_free_and_dispatch_submits(self, provider, job_service):
        prepared = provider.prepare_teardown(_settlement_result(), _pool_config())
        job_service.submit.assert_not_awaited()

        result = await provider.dispatch_teardown(prepared)

        assert result.provider_metadata["teardown_job_id"] == "job-1"
        submitted_params: AnsibleJobParams = job_service.submit.await_args.args[0]
        assert submitted_params.vm_action == "vm_remove"
        assert submitted_params.vm_target == "vm-alloc-1"


class TestGetStatus:
    async def test_maps_succeeded_job(self, provider, job_service):
        job_service.get_job = MagicMock(return_value=SimpleNamespace(status="succeeded", error=None))
        status = await provider.get_status("alloc-1", _resource(), _metadata())
        assert status.state is ProviderOperationState.succeeded

    async def test_maps_queued_and_running_to_pending(self, provider, job_service):
        for job_status in ("queued", "running"):
            job_service.get_job = MagicMock(return_value=SimpleNamespace(status=job_status, error=None))
            status = await provider.get_status("alloc-1", _resource(), _metadata())
            assert status.state is ProviderOperationState.pending

    async def test_maps_failed_and_cancelled_to_failed(self, provider, job_service):
        for job_status in ("failed", "cancelled"):
            job_service.get_job = MagicMock(return_value=SimpleNamespace(status=job_status, error="boom"))
            status = await provider.get_status("alloc-1", _resource(), _metadata())
            assert status.state is ProviderOperationState.failed
            assert status.detail == "boom"

    async def test_missing_job_lookup_error_maps_to_unknown(self, provider, job_service):
        job_service.get_job = MagicMock(side_effect=LookupError("job-1 not found"))
        status = await provider.get_status("alloc-1", _resource(), _metadata())
        assert status.state is ProviderOperationState.unknown

    async def test_unexpected_error_raises_status_failed(self, provider, job_service):
        job_service.get_job = MagicMock(side_effect=RuntimeError("db is down"))
        with pytest.raises(FulfillmentStatusFailedError):
            await provider.get_status("alloc-1", _resource(), _metadata())

    async def test_invalid_metadata_maps_to_unknown(self, provider):
        status = await provider.get_status("alloc-1", _resource(), {})
        assert status.state is ProviderOperationState.unknown


class TestExtraVarsCollision:
    def test_create_rejects_collision_on_a_named_builtin(self, provider):
        with pytest.raises(ProviderConfigInvalidError, match="vm_host"):
            provider.prepare_create(
                _request(),
                _resource(),
                _pool_config(extra_vars={"vm_host": "hijacked"}),
            )

    def test_create_rejects_collision_on_a_dynamically_derived_builtin(self, provider):
        with pytest.raises(ProviderConfigInvalidError, match="executor_kind"):
            provider.prepare_create(
                _request(),
                _resource(),
                _pool_config(extra_vars={"executor_kind": "hijacked"}),
            )

    def test_teardown_rejects_collision_too(self, provider):
        with pytest.raises(ProviderConfigInvalidError, match="vm_target"):
            provider.prepare_teardown(
                _settlement_result(),
                _pool_config(extra_vars={"vm_target": "hijacked"}),
            )

    async def test_non_colliding_extra_var_reaches_dispatch(self, provider, job_service):
        prepared = provider.prepare_create(
            _request(),
            _resource(),
            _pool_config(extra_vars={"region": "eu"}),
        )
        await provider.dispatch_create(prepared)
        submitted_params: AnsibleJobParams = job_service.submit.await_args.args[0]
        assert submitted_params.provider_extra_vars == {"region": "eu"}

    def test_reserved_var_keys_matches_what_build_vm_vars_actually_emits(self):
        ansible_service = AnsibleService(settings=MagicMock())
        params = AnsibleJobParams(vm_host="kvm1", vm_action="create")
        reserved = ansible_service.reserved_var_keys(params)
        assert "executor_kind" in reserved
        assert "vm_host" in reserved

        with pytest.raises(ValueError, match="executor_kind"):
            ansible_service._build_vm_vars(
                dataclasses.replace(params, provider_extra_vars={"executor_kind": "x"})
            )
