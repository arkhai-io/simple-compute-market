"""Unit tests for AnsibleFulfillmentProvider.

Mocks AnsibleJobService/ResourcePoolService at the boundary (consistent
with this codebase's existing unit-test convention — see
test_job_service.py's docstring: orchestration/queue plumbing is exercised
in integration tests, not here).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from compute_provisioning import PhysicalSettlementRequest, SettlementResource
from services.ansible_fulfillment_provider import AnsibleFulfillmentProvider
from services.ansible_service import AnsibleService
from market_resource_pools import (
    FulfillmentStatusFailedError,
    ProviderConfigInvalidError,
    ProviderOperationState,
)
from models.jobs_model import AnsibleJobParams


def _request() -> PhysicalSettlementRequest:
    return PhysicalSettlementRequest(
        allocation_id="alloc-1", agreement_id="agreement-1", market="vms", requirements={"vm_target":"vm-alloc-1","vm_ram":4096,"vm_vcpus":2,"vm_disk_size":"40G","ssh_pubkey":"ssh-ed25519 AAAA"}
    )


def _resource(**overrides) -> SettlementResource:
    defaults = dict(
        settlement_resource_id="kvm1",
        pool_id="pool-1",
        resource_kind="vm",
        provider="ansible",
        attributes={"vm_host": "kvm1"},
    )
    defaults.update(overrides)
    return SettlementResource(**defaults)


def _pool(provider_config: dict | None = None):
    return SimpleNamespace(
        enabled=True, provider="ansible",
        provider_config=(
            {"playbook_path": "playbooks/vm-operations.yaml", "extra_vars": {}}
            if provider_config is None
            else provider_config
        )
    )


@pytest.fixture
def job_service():
    svc = MagicMock()
    svc.submit = AsyncMock(return_value=SimpleNamespace(job_id="job-1", status="queued"))
    return svc


@pytest.fixture
def resource_pool_service():
    svc = MagicMock()
    svc.get_pool = MagicMock(return_value=_pool())
    return svc


@pytest.fixture
def provider(job_service, resource_pool_service):
    return AnsibleFulfillmentProvider(
        job_service=job_service,
        resource_pool_service=resource_pool_service,
        job_queue_provider=lambda: MagicMock(),
    )


class TestCreate:
    async def test_create_is_dispatch_only(self, provider, job_service):
        result = await provider.create(_request(), _resource())
        assert result.provider_metadata["create_job_id"] == "job-1"
        assert result.provider_metadata["vm_target"] == "vm-alloc-1"
        job_service.submit.assert_awaited_once()

    async def test_create_snapshots_pool_config_into_job_params(
        self, provider, job_service, resource_pool_service
    ):
        resource_pool_service.get_pool.return_value = _pool(
            {"playbook_path": "playbooks/custom.yaml", "extra_vars": {"region": "eu"}}
        )
        await provider.create(_request(), _resource())

        submitted_params: AnsibleJobParams = job_service.submit.await_args.args[0]
        assert submitted_params.playbook_path == "playbooks/custom.yaml"
        assert submitted_params.provider_extra_vars == {"region": "eu"}

        # A later pool edit does not change what was already submitted —
        # the provider read the pool once, at dispatch time.
        resource_pool_service.get_pool.return_value = _pool(
            {"playbook_path": "playbooks/changed.yaml", "extra_vars": {}}
        )
        assert submitted_params.playbook_path == "playbooks/custom.yaml"

    async def test_missing_pool_raises_provider_config_invalid(
        self, provider, resource_pool_service
    ):
        resource_pool_service.get_pool.return_value = None
        with pytest.raises(ProviderConfigInvalidError):
            await provider.create(_request(), _resource())

    async def test_missing_playbook_path_raises_provider_config_invalid(
        self, provider, resource_pool_service
    ):
        resource_pool_service.get_pool.return_value = _pool({"extra_vars": {}})
        with pytest.raises(ProviderConfigInvalidError):
            await provider.create(_request(), _resource())


class TestTeardown:
    async def test_teardown_is_dispatch_only(self, provider, job_service):
        result = await provider.teardown("alloc-1", _resource(), {"create_job_id":"create-job","current_job_id":"create-job","vm_host":"kvm1","vm_target":"vm-alloc-1","operation":"create"})
        assert result.provider_metadata["teardown_job_id"] == "job-1"
        submitted_params: AnsibleJobParams = job_service.submit.await_args.args[0]
        assert submitted_params.vm_action == "vm_remove"
        assert submitted_params.vm_target == "vm-alloc-1"


class TestGetStatus:
    async def test_maps_succeeded_job(self, provider, job_service):
        job_service.get_job = MagicMock(
            return_value=SimpleNamespace(status="succeeded", error=None)
        )
        status = await provider.get_status("alloc-1", _resource(), {"job_id": "job-1"})
        assert status.state is ProviderOperationState.succeeded

    async def test_maps_queued_and_running_to_pending(self, provider, job_service):
        for job_status in ("queued", "running"):
            job_service.get_job = MagicMock(
                return_value=SimpleNamespace(status=job_status, error=None)
            )
            status = await provider.get_status("alloc-1", _resource(), {"job_id": "job-1"})
            assert status.state is ProviderOperationState.pending

    async def test_maps_failed_and_cancelled_to_failed(self, provider, job_service):
        for job_status in ("failed", "cancelled"):
            job_service.get_job = MagicMock(
                return_value=SimpleNamespace(status=job_status, error="boom")
            )
            status = await provider.get_status("alloc-1", _resource(), {"job_id": "job-1"})
            assert status.state is ProviderOperationState.failed
            assert status.detail == "boom"

    async def test_missing_job_lookup_error_maps_to_unknown(self, provider, job_service):
        job_service.get_job = MagicMock(side_effect=LookupError("job-1 not found"))
        status = await provider.get_status("alloc-1", _resource(), {"job_id": "job-1"})
        assert status.state is ProviderOperationState.unknown

    async def test_unexpected_error_raises_status_failed(self, provider, job_service):
        job_service.get_job = MagicMock(side_effect=RuntimeError("db is down"))
        with pytest.raises(FulfillmentStatusFailedError):
            await provider.get_status("alloc-1", _resource(), {"job_id": "job-1"})

    async def test_missing_job_id_maps_to_unknown(self, provider):
        status = await provider.get_status("alloc-1", _resource(), {})
        assert status.state is ProviderOperationState.unknown


class TestExtraVarsCollision:
    """Collision detection lives in AnsibleService._build_vm_vars, which
    only runs when the background job worker actually renders the vars
    file (see job_service.py's _process_job) — not synchronously from
    create(), consistent with create() being dispatch-only. A collision
    therefore surfaces later as a failed job, observable via get_status,
    not as an exception from create(). Exercised directly against the
    mechanism here; full end-to-end surfacing is job_service's own concern.
    """

    def test_colliding_extra_var_raises_value_error(self):
        ansible_service = AnsibleService(settings=MagicMock())
        params = AnsibleJobParams(
            vm_host="kvm1",
            vm_action="create",
            provider_extra_vars={"vm_host": "should-not-override"},
        )
        with pytest.raises(ValueError, match="vm_host"):
            ansible_service._build_vm_vars(params)

    def test_non_colliding_extra_var_is_included(self):
        ansible_service = AnsibleService(settings=MagicMock())
        params = AnsibleJobParams(
            vm_host="kvm1", vm_action="create", provider_extra_vars={"region": "eu"}
        )
        rendered = ansible_service._build_vm_vars(params)
        assert "region:" in rendered
