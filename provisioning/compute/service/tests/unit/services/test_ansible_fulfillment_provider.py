"""Unit tests for AnsibleFulfillmentProvider.

Mocks AnsibleJobService/ResourcePoolService at the boundary (consistent
with this codebase's existing unit-test convention — see
test_job_service.py's docstring: orchestration/queue plumbing is exercised
in integration tests, not here).
"""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from market_fulfillment import (
    PhysicalSettlementRequest,
    SettlementResource,
    VersionedEnvelope,
)
from vm_provisioning_adapter.services.ansible_fulfillment_provider import AnsibleFulfillmentProvider
from vm_provisioning_adapter.services.ansible_service import AnsibleService
from market_fulfillment import (
    FulfillmentStatusFailedError,
    ProviderConfigInvalidError,
    ProviderOperationState,
)
from vm_provisioning_adapter.models.jobs_model import AnsibleJobParams


def _request() -> PhysicalSettlementRequest:
    return PhysicalSettlementRequest(
        capacity_reservation_id="alloc-1", market="vms", requirements={"vm_target":"vm-alloc-1","vm_ram":4096,"vm_vcpus":2,"vm_disk_size":"40G","ssh_pubkey":"ssh-ed25519 AAAA"}
    )


def _fulfillment_request() -> VersionedEnvelope:
    return VersionedEnvelope(
        kind="vms.fulfillment",
        schema_version=1,
        payload=dict(_request().requirements),
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
    # Real reserved_var_keys logic (not a bare MagicMock — a MagicMock's
    # .intersection(...) result is truthy, which would make every
    # _validate_extra_vars call raise). Backed by an actual AnsibleService
    # so tests exercise the same dynamic derivation production code uses.
    svc.reserved_var_keys = AnsibleService(settings=MagicMock()).reserved_var_keys
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

    async def test_create_dispatches_only_from_prepared_pool_snapshot(
        self, provider, job_service, resource_pool_service
    ):
        resource_pool_service.get_pool.return_value = _pool(
            {"playbook_path": "playbooks/custom.yaml", "extra_vars": {"region": "eu"}}
        )
        prepared = provider.prepare_create(
            "alloc-1",
            _fulfillment_request(),
            _resource(),
        )
        assert resource_pool_service.get_pool.call_count > 0

        resource_pool_service.get_pool.reset_mock()
        resource_pool_service.get_pool.return_value = _pool(
            {"playbook_path": "playbooks/changed.yaml", "extra_vars": {}}
        )
        await provider.dispatch_create(prepared)

        resource_pool_service.get_pool.assert_not_called()
        submitted_params: AnsibleJobParams = job_service.submit.await_args.args[0]
        contract = job_service.submit.await_args.kwargs["contract"]
        assert submitted_params.playbook_path == "playbooks/custom.yaml"
        assert submitted_params.provider_extra_vars == {"region": "eu"}
        assert contract.action_kind == "fulfillment_create"
        assert contract.idempotency_key == "alloc-1:fulfillment_create:v1"
        assert contract.parameters == dataclasses.asdict(submitted_params)

    def test_unknown_fulfillment_request_version_is_rejected(self, provider):
        with pytest.raises(ProviderConfigInvalidError, match="unsupported VM"):
            provider.prepare_create(
                "alloc-1",
                VersionedEnvelope(
                    kind="vms.fulfillment",
                    schema_version=2,
                    payload=dict(_request().requirements),
                ),
                _resource(),
            )

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
    async def test_teardown_is_dispatched_from_prepared_input(
        self, provider, job_service, resource_pool_service
    ):
        metadata = {
            "create_job_id": "create-job",
            "current_job_id": "create-job",
            "vm_host": "kvm1",
            "vm_target": "vm-alloc-1",
            "operation": "create",
        }
        prepared = provider.prepare_teardown(
            "alloc-1",
            _resource(),
            metadata,
        )
        resource_pool_service.get_pool.reset_mock()
        result = await provider.dispatch_teardown(prepared)

        resource_pool_service.get_pool.assert_not_called()
        assert result.provider_metadata["teardown_job_id"] == "job-1"
        submitted_params: AnsibleJobParams = job_service.submit.await_args.args[0]
        contract = job_service.submit.await_args.kwargs["contract"]
        assert submitted_params.vm_action == "vm_remove"
        assert submitted_params.vm_target == "vm-alloc-1"
        assert contract.action_kind == "fulfillment_teardown"
        assert contract.idempotency_key == "alloc-1:fulfillment_teardown:v1"


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
            assert status.detail == "provider job failed"

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
    """Collision detection is synchronous and uses the dispatch renderer's keys.

    AnsibleFulfillmentProvider derives the reserved-key set dynamically via
    AnsibleJobService.reserved_var_keys
    (which delegates to AnsibleService, the same logic _build_vm_vars uses
    to render the file), instead of a separately hand-maintained list.
    This closes a gap found during implementation review: an earlier
    hardcoded reserved-set here missed several real built-in fields —
    concretely, `executor_kind` — so a colliding extra_var could pass this
    check and only be caught later, asynchronously, when the background
    job worker rendered the vars file.
    """

    async def test_create_rejects_collision_on_a_named_builtin(
        self, provider, resource_pool_service
    ):
        resource_pool_service.get_pool.return_value = _pool(
            {"playbook_path": "playbooks/vm-operations.yaml", "extra_vars": {"vm_host": "hijacked"}}
        )
        with pytest.raises(ProviderConfigInvalidError, match="vm_host"):
            await provider.create(_request(), _resource())

    async def test_create_rejects_collision_on_a_field_the_old_hardcoded_list_missed(
        self, provider, resource_pool_service
    ):
        # executor_kind is a real built-in field (see AnsibleService._build_builtin_var_lines)
        # that was NOT in the reserved set before this fix — this is the
        # concrete gap demonstrated during implementation review.
        resource_pool_service.get_pool.return_value = _pool(
            {"playbook_path": "playbooks/vm-operations.yaml", "extra_vars": {"executor_kind": "hijacked"}}
        )
        with pytest.raises(ProviderConfigInvalidError, match="executor_kind"):
            await provider.create(_request(), _resource())

    async def test_teardown_rejects_collision_too(self, provider, resource_pool_service):
        resource_pool_service.get_pool.return_value = _pool(
            {"playbook_path": "playbooks/vm-operations.yaml", "extra_vars": {"vm_target": "hijacked"}}
        )
        with pytest.raises(ProviderConfigInvalidError, match="vm_target"):
            await provider.teardown(
                "alloc-1",
                _resource(),
                {"create_job_id": "create-job", "current_job_id": "create-job",
                 "vm_host": "kvm1", "vm_target": "vm-alloc-1", "operation": "create"},
            )

    async def test_non_colliding_extra_var_still_reaches_dispatch(
        self, provider, job_service, resource_pool_service
    ):
        resource_pool_service.get_pool.return_value = _pool(
            {"playbook_path": "playbooks/vm-operations.yaml", "extra_vars": {"region": "eu"}}
        )
        await provider.create(_request(), _resource())
        submitted_params: AnsibleJobParams = job_service.submit.await_args.args[0]
        assert submitted_params.provider_extra_vars == {"region": "eu"}

    def test_reserved_var_keys_matches_what_build_vm_vars_actually_emits(self):
        """AnsibleService.reserved_var_keys and _build_vm_vars's own
        internal collision check must never disagree — both now derive
        from the same _build_builtin_var_lines helper."""
        ansible_service = AnsibleService(settings=MagicMock())
        params = AnsibleJobParams(vm_host="kvm1", vm_action="create")
        reserved = ansible_service.reserved_var_keys(params)
        assert "executor_kind" in reserved
        assert "vm_host" in reserved

        with pytest.raises(ValueError, match="executor_kind"):
            ansible_service._build_vm_vars(
                dataclasses.replace(params, provider_extra_vars={"executor_kind": "x"})
            )

@pytest.mark.asyncio
async def test_live_credentials_rotate_with_generation_and_consume_private_rows(
    provider, job_service
):
    from vm_provisioning_operator.models import (
        CredentialListResponse,
        CredentialResponse,
    )

    job_service.wait_for_terminal_job = AsyncMock(
        return_value=SimpleNamespace(status="succeeded", error=None)
    )
    job_service.consume_private_credentials.side_effect = [
        CredentialListResponse(job_id="job-1", credentials=[]),
        CredentialListResponse(
            job_id="rotation-job",
            credentials=[
                CredentialResponse(role="tenant", password="fresh-password")
            ],
        ),
    ]
    job_service.submit.return_value = SimpleNamespace(
        job_id="rotation-job", status="queued"
    )
    metadata = {
        "create_job_id": "job-1",
        "current_job_id": "job-1",
        "vm_host": "kvm1",
        "vm_target": "vm-alloc-1",
        "operation": "create",
    }

    result = await provider.get_live_credentials(
        "reservation-1",
        _resource(),
        metadata,
        credential_generation=3,
    )

    assert result.rotated
    assert result.credentials[0].payload["password"] == "fresh-password"
    submitted_contract = job_service.submit.await_args.kwargs["contract"]
    assert submitted_contract.idempotency_key == (
        "reservation-1:credential_rotation:g3:v1"
    )
    assert job_service.submit.await_args.kwargs["credentials_private"] is True
    assert job_service.consume_private_credentials.call_args_list[-1].args == (
        "rotation-job",
    )


def test_backfilled_metadata_without_create_job_prepares_frozen_teardown(provider):
    prepared = provider.prepare_teardown(
        "reservation-legacy",
        _resource(),
        {
            "backfilled": True,
            "create_job_id": None,
            "vm_host": "kvm1",
            "vm_target": "vm-legacy",
            "teardown_job_id": None,
            "current_job_id": None,
            "operation": "create",
        },
    )

    assert prepared.kind == "ansible.vm.teardown"
    assert prepared.payload["job_params"]["vm_action"] == "vm_remove"
    assert prepared.payload["job_params"]["vm_target"] == "vm-legacy"
    assert prepared.payload["contract"]["idempotency_key"] == (
        "reservation-legacy:fulfillment_teardown:v1"
    )


def test_native_metadata_still_requires_create_job(provider):
    with pytest.raises(ValidationError):
        provider.prepare_teardown(
            "reservation-native",
            _resource(),
            {
                "vm_host": "kvm1",
                "vm_target": "vm-native",
                "current_job_id": "job-1",
                "operation": "create",
            },
        )
