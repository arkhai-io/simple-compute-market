"""Unit tests for the Ansible fulfillment adapter boundary."""

from __future__ import annotations

import dataclasses
import json
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
        "executor_kind": "vm",
        "resource_kind": "vm",
        "provider": "ansible",
        "attributes": {"vm_host": "kvm1"},
    }
    values.update(overrides)
    return SettlementResource(**values)


def _pool_config(**overrides) -> dict:
    values = {"playbook_path": "playbooks/vm-operations.yaml", "requirement_delegate": "vm_management_v1", "extra_vars": {}}
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
        prepared = provider.prepare_create(capacity_reservation_id="alloc-1", request=_request(), resource=_resource(), pool_config=_pool_config())
        job_service.submit.assert_not_awaited()

        result = await provider.dispatch_create(prepared)

        assert result.provider_metadata["create_job_id"] == "job-1"
        assert result.provider_metadata["vm_target"] == "vm-alloc-1"
        job_service.submit.assert_awaited_once()

    async def test_prepare_snapshots_pool_config_into_job_params(self, provider, job_service):
        prepared = provider.prepare_create(
            capacity_reservation_id="alloc-1",
            request=_request(),
            resource=_resource(),
            pool_config=_pool_config(
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
            provider.prepare_create(capacity_reservation_id="alloc-1", request=_request(), resource=_resource(), pool_config={"extra_vars": {}})


class TestSizingPrecedence:
    """vm_ram/vm_vcpus/vm_disk_size/gpu_provisioned/vm_gpu_count are derived
    from the reservation's own committed dimensions (SettlementResource
    .dimensions), never from the caller-supplied fulfillment request: a
    reservation's hold is placed with the terminal, negotiated shape
    already, so a caller-supplied copy could only ever restate it, never
    legitimately override it. Precedence: reservation dimensions, else
    the pool's configured default (RAM/vCPU/disk only -- GPU has no
    pool-level default), else left unset (Ansible/inventory group_vars
    resolve it)."""

    async def test_reservation_dimensions_win_over_pool_default(self, provider, job_service):
        request = _request()
        resource = _resource(dimensions={
            "gpu_count": 1, "vcpu_count": 2, "ram_gb": 4, "disk_gb": 40,
        })
        prepared = provider.prepare_create(
            capacity_reservation_id="alloc-1", request=request, resource=resource,
            pool_config=_pool_config(
                default_vm_ram=8192, default_vm_vcpus=4, default_vm_disk_size="80G",
            ),
        )
        await provider.dispatch_create(prepared)

        submitted_params: AnsibleJobParams = job_service.submit.await_args.args[0]
        assert submitted_params.vm_ram == 4096  # 4 GB -> MiB
        assert submitted_params.vm_vcpus == 2
        assert submitted_params.vm_disk_size == "40G"
        assert submitted_params.gpu_provisioned is True
        assert submitted_params.vm_gpu_count == 1

    async def test_pool_default_used_when_reservation_has_no_dimensions(self, provider, job_service):
        request = _request()
        resource = _resource(dimensions={})
        prepared = provider.prepare_create(
            capacity_reservation_id="alloc-1", request=request, resource=resource,
            pool_config=_pool_config(
                default_vm_ram=8192, default_vm_vcpus=4, default_vm_disk_size="80G",
            ),
        )
        await provider.dispatch_create(prepared)

        submitted_params: AnsibleJobParams = job_service.submit.await_args.args[0]
        assert submitted_params.vm_ram == 8192
        assert submitted_params.vm_vcpus == 4
        assert submitted_params.vm_disk_size == "80G"
        assert submitted_params.gpu_provisioned is None
        assert submitted_params.vm_gpu_count is None

    async def test_sizing_left_unset_when_neither_dimensions_nor_pool_specify_it(self, provider, job_service):
        request = _request()
        resource = _resource(dimensions={})
        prepared = provider.prepare_create(
            capacity_reservation_id="alloc-1", request=request, resource=resource, pool_config=_pool_config(),
        )
        await provider.dispatch_create(prepared)

        submitted_params: AnsibleJobParams = job_service.submit.await_args.args[0]
        assert submitted_params.vm_ram is None
        assert submitted_params.vm_vcpus is None
        assert submitted_params.vm_disk_size is None
        assert submitted_params.gpu_provisioned is None
        assert submitted_params.vm_gpu_count is None

    async def test_request_supplied_sizing_is_ignored_even_when_present(self, provider, job_service):
        """Regression test for the fix itself: a fulfillment request
        carrying vm_ram/vm_vcpus/vm_disk_size directly (the old trusted
        path -- ``_request()``'s payload still carries these, matching
        what a pre-fix caller could have sent) must not influence the
        submitted job at all once a reservation's own dimensions
        disagree. Only the committed reservation is trusted."""
        request = _request()  # payload carries vm_ram=4096, vm_vcpus=2, vm_disk_size="40G"
        resource = _resource(dimensions={
            "gpu_count": 0, "vcpu_count": 8, "ram_gb": 32, "disk_gb": 200,
        })
        prepared = provider.prepare_create(
            capacity_reservation_id="alloc-1", request=request, resource=resource,
            pool_config=_pool_config(),
        )
        await provider.dispatch_create(prepared)

        submitted_params: AnsibleJobParams = job_service.submit.await_args.args[0]
        # The reservation's committed shape wins, not the request payload's.
        assert submitted_params.vm_vcpus == 8
        assert submitted_params.vm_ram == 32 * 1024
        assert submitted_params.vm_disk_size == "200G"
        assert submitted_params.gpu_provisioned is False
        assert submitted_params.vm_gpu_count == 0


class TestRelayAccessPath:
    """Exactly one access path is selected, and never zero.

    The failure this replaces: two paths guarded by different conditions, and a
    configuration satisfying neither produced a VM with no external route and
    reported success. Relay location now comes from the relay a pool
    references, resolved by the execution read, and is not selectable per
    request.
    """

    class _Allocator:
        def __init__(self, port=6100):
            self.port = port
            self.calls = []

        def allocate(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(
                id="lease-1", relay_id=kwargs["relay_id"], remote_port=self.port
            )

    def _relay_pool_config(self, **overrides):
        config = _pool_config()
        config.update(
            {
                "relay_id": "site-a",
                "relay_addr": "203.0.113.9",
                "relay_port": 7000,
                "vm_port_range_start": 6100,
                "vm_port_range_count": 100,
                "relay_token": "admission-token",
            }
        )
        config.update(overrides)
        return config

    async def test_no_accepted_operation_carries_a_token(self, job_service):
        """The credential must not reach the persisted, readable snapshot.

        Asserted over the serialized envelope rather than the dataclass,
        because that is what is written to the job's params column and handed
        back by the job endpoints.
        """
        provider = AnsibleFulfillmentProvider(
            job_service=job_service,
            job_queue_provider=lambda: MagicMock(),
            port_allocator=self._Allocator(),
        )
        prepared = provider.prepare_create(
            capacity_reservation_id="alloc-1", request=_request(),
            resource=_resource(), pool_config=self._relay_pool_config(),
        )
        assert "admission-token" not in json.dumps(prepared.payload)

    async def test_a_pool_with_no_relay_takes_the_direct_path(self, provider, job_service):
        prepared = provider.prepare_create(
            capacity_reservation_id="alloc-1", request=_request(),
            resource=_resource(), pool_config=_pool_config(),
        )
        await provider.dispatch_create(prepared)

        submitted: AnsibleJobParams = job_service.submit.await_args.args[0]
        assert submitted.relay_addr is None
        assert submitted.vm_remote_port is None

    async def test_a_relay_backed_pool_forwards_the_relay_and_a_leased_port(
        self, job_service
    ):
        allocator = self._Allocator(port=6142)
        provider = AnsibleFulfillmentProvider(
            job_service=job_service,
            job_queue_provider=lambda: MagicMock(),
            port_allocator=allocator,
        )
        prepared = provider.prepare_create(
            capacity_reservation_id="alloc-1", request=_request(),
            resource=_resource(), pool_config=self._relay_pool_config(),
        )
        await provider.dispatch_create(prepared)

        submitted: AnsibleJobParams = job_service.submit.await_args.args[0]
        assert submitted.relay_id == "site-a"
        assert submitted.vm_remote_port == 6142
        # The endpoint and the token are deliberately absent. What is submitted
        # is persisted and returned by the job endpoints, so a token here would
        # be published; it is resolved at execution instead.
        assert submitted.relay_addr is None
        assert submitted.relay_token is None

    def test_validation_leases_nothing(self, job_service):
        """Validation answers whether a request would be accepted. Acquiring on
        the way to the answer lets a caller who only ever asks exhaust a finite
        window without a single accepted fulfillment."""
        allocator = self._Allocator()
        provider = AnsibleFulfillmentProvider(
            job_service=job_service,
            job_queue_provider=lambda: MagicMock(),
            port_allocator=allocator,
        )
        provider.prepare_create(
            capacity_reservation_id="alloc-1", request=_request(),
            resource=_resource(), pool_config=self._relay_pool_config(),
            allocate=False,
        )
        assert allocator.calls == []

    def test_validation_still_rejects_a_partial_relay(self, job_service):
        """Purity is about acquiring, not about checking. Every rejection that
        acceptance performs must still run, or validation stops answering the
        question it exists for."""
        provider = AnsibleFulfillmentProvider(
            job_service=job_service,
            job_queue_provider=lambda: MagicMock(),
            port_allocator=self._Allocator(),
        )
        with pytest.raises(ProviderConfigInvalidError):
            provider.prepare_create(
                capacity_reservation_id="alloc-1", request=_request(),
                resource=_resource(),
                pool_config=self._relay_pool_config(relay_token=None),
                allocate=False,
            )

    def test_the_lease_records_the_pool_and_host(self, job_service):
        """Both are what the rebinding rules look leases up by.

        A lease without a pool leaves the rule refusing a pool repoint unable
        to find anything — permissive, silently, and only observable by
        repointing a pool that is carrying tunnels and watching it succeed.
        """
        allocator = self._Allocator()
        provider = AnsibleFulfillmentProvider(
            job_service=job_service,
            job_queue_provider=lambda: MagicMock(),
            port_allocator=allocator,
        )
        provider.prepare_create(
            capacity_reservation_id="alloc-1", request=_request(),
            resource=_resource(), pool_config=self._relay_pool_config(),
        )

        call = allocator.calls[0]
        assert call["pool_id"] == _resource().pool_id
        assert call["host_name"] == "kvm1"

    def test_the_port_is_leased_before_dispatch(self, job_service):
        """Allocating after dispatch would let a crash between the two leave a
        port bound on the relay that no record claims."""
        allocator = self._Allocator()
        provider = AnsibleFulfillmentProvider(
            job_service=job_service,
            job_queue_provider=lambda: MagicMock(),
            port_allocator=allocator,
        )
        provider.prepare_create(
            capacity_reservation_id="alloc-1", request=_request(),
            resource=_resource(), pool_config=self._relay_pool_config(),
        )

        assert allocator.calls
        assert allocator.calls[0]["relay_id"] == "site-a"
        assert allocator.calls[0]["owner_id"] == "alloc-1"
        job_service.submit.assert_not_awaited()

    @pytest.mark.parametrize(
        "missing, expected",
        [
            ({"relay_token": None}, "admission token"),
            ({"relay_addr": None}, "relay address"),
            ({"vm_port_range_start": None}, "port window start"),
            ({"vm_port_range_count": None}, "port window size"),
        ],
    )
    def test_a_partial_relay_configuration_is_rejected_before_dispatch(
        self, job_service, missing, expected
    ):
        provider = AnsibleFulfillmentProvider(
            job_service=job_service,
            job_queue_provider=lambda: MagicMock(),
            port_allocator=self._Allocator(),
        )
        with pytest.raises(ProviderConfigInvalidError) as excinfo:
            provider.prepare_create(
                capacity_reservation_id="alloc-1", request=_request(),
                resource=_resource(),
                pool_config=self._relay_pool_config(**missing),
            )
        assert expected in str(excinfo.value)
        assert "site-a" in str(excinfo.value)

    def test_a_request_cannot_select_a_relay(self, provider, job_service):
        """Relay location is a durable property of the deployment. A request
        carrying relay-shaped keys does not become a relay-backed VM."""
        request = _request()
        request.payload["connectivity"] = {
            "frp_server_addr": "relay.example.com:7000",
            "frp_domain": "buyer-vm.example.com",
            "frp_dashboard_password": "s3cr3t",
        }
        prepared = provider.prepare_create(
            capacity_reservation_id="alloc-1", request=request,
            resource=_resource(), pool_config=_pool_config(),
        )
        params = prepared.payload["parameters"]
        assert params["relay_id"] is None
        assert params["vm_remote_port"] is None


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
                capacity_reservation_id="alloc-1",
                request=_request(),
                resource=_resource(),
                pool_config=_pool_config(extra_vars={"vm_host": "hijacked"}),
            )

    def test_create_rejects_collision_on_a_dynamically_derived_builtin(self, provider):
        with pytest.raises(ProviderConfigInvalidError, match="executor_kind"):
            provider.prepare_create(
                capacity_reservation_id="alloc-1",
                request=_request(),
                resource=_resource(),
                pool_config=_pool_config(extra_vars={"executor_kind": "hijacked"}),
            )

    def test_teardown_rejects_collision_too(self, provider):
        with pytest.raises(ProviderConfigInvalidError, match="vm_target"):
            provider.prepare_teardown(
                _settlement_result(),
                _pool_config(extra_vars={"vm_target": "hijacked"}),
            )

    async def test_non_colliding_extra_var_reaches_dispatch(self, provider, job_service):
        prepared = provider.prepare_create(
            capacity_reservation_id="alloc-1",
            request=_request(),
            resource=_resource(),
            pool_config=_pool_config(extra_vars={"region": "eu"}),
        )
        await provider.dispatch_create(prepared)
        submitted_params: AnsibleJobParams = job_service.submit.await_args.args[0]
        assert submitted_params.provider_extra_vars == {"region": "eu"}

    def test_reserved_var_keys_matches_what_build_vm_vars_actually_emits(self):
        ansible_service = AnsibleService(settings=MagicMock())
        params = AnsibleJobParams(
            vm_host="kvm1", vm_action="create", executor_kind="vm"
        )
        reserved = ansible_service.reserved_var_keys(params)
        assert "executor_kind" in reserved
        assert "vm_host" in reserved

        with pytest.raises(ValueError, match="executor_kind"):
            ansible_service._build_vm_vars(
                dataclasses.replace(params, provider_extra_vars={"executor_kind": "x"})
            )


class TestPreparedEnvelope:
    async def test_dispatch_rejects_malformed_typed_parameters(self, provider):
        malformed = VersionedEnvelope(
            kind="vm.ansible.create.v1",
            schema_version=1,
            payload={
                "capacity_reservation_id": "alloc-1",
                "action": "create",
                "parameters": {"vm_action": "create"},
            },
        )

        with pytest.raises(ProviderConfigInvalidError):
            await provider.dispatch_create(malformed)

    async def test_executor_contract_uses_empty_deal_ref_and_deterministic_key(
        self, provider, job_service
    ):
        prepared = provider.prepare_create(
            capacity_reservation_id="alloc-1",
            request=_request(),
            resource=_resource(),
            pool_config=_pool_config(),
        )

        await provider.dispatch_create(prepared)

        contract = job_service.submit.await_args.kwargs["contract"]
        assert contract.deal_ref == {}
        assert contract.idempotency_key == "alloc-1:create"


class TestRequirementDelegateRegistry:
    def test_unknown_delegate_is_rejected(self, provider):
        with pytest.raises(ProviderConfigInvalidError, match="unknown Ansible requirement delegate"):
            provider.prepare_create(
                capacity_reservation_id="alloc-1",
                request=_request(),
                resource=_resource(dimensions={"ram_gb": 4}),
                pool_config=_pool_config(requirement_delegate="not_registered"),
            )

    def test_invalid_dimension_is_rejected_by_delegate(self, provider):
        with pytest.raises(ProviderConfigInvalidError, match="ram_gb"):
            provider.prepare_create(
                capacity_reservation_id="alloc-1",
                request=_request(),
                resource=_resource(dimensions={"ram_gb": "4.5"}),
                pool_config=_pool_config(),
            )


class TestTeardownReadsTheLease:
    """Teardown targets where the port actually went.

    The rebinding rules make disagreement between a lease and its pool hard to
    reach through the API, which is the point of them — but "hard to reach"
    is not "impossible", and a lease is the only record of where a port was
    bound. Resolving the relay from pool configuration at teardown would
    release against a relay the port never occupied and leave bound the one it
    did, on a path that runs after the VM is already gone.
    """

    class _Allocator:
        def __init__(self, relay_id="site-a", port=6100):
            self._lease = SimpleNamespace(
                id="lease-1", relay_id=relay_id, remote_port=port
            )
            self.lookups = []

        def find_active_lease(self, *, owner_kind, owner_id):
            self.lookups.append((owner_kind, owner_id))
            return self._lease

        def allocate(self, **kwargs):
            return self._lease

    class _NoLeaseAllocator:
        def find_active_lease(self, *, owner_kind, owner_id):
            return None

    def _pool_on(self, relay_id):
        config = _pool_config()
        config["relay_id"] = relay_id
        return config

    def test_teardown_uses_the_leased_relay_not_the_pools(self, job_service):
        """The pool now points at site-b; the VM's port is bound on site-a."""
        allocator = self._Allocator(relay_id="site-a")
        provider = AnsibleFulfillmentProvider(
            job_service=job_service,
            job_queue_provider=lambda: MagicMock(),
            port_allocator=allocator,
        )

        prepared = provider.prepare_teardown(
            _settlement_result(), self._pool_on("site-b")
        )

        assert prepared.payload["parameters"]["relay_id"] == "site-a"
        assert allocator.lookups == [("fulfillment", "alloc-1")]

    def test_teardown_of_a_direct_nat_vm_names_no_relay(self, job_service):
        provider = AnsibleFulfillmentProvider(
            job_service=job_service,
            job_queue_provider=lambda: MagicMock(),
            port_allocator=self._NoLeaseAllocator(),
        )

        prepared = provider.prepare_teardown(_settlement_result(), _pool_config())

        assert prepared.payload["parameters"]["relay_id"] is None

    def test_teardown_after_the_lease_is_released_names_no_relay(self, job_service):
        """A released lease means the relay work is already done; teardown has
        nothing further to reload."""
        provider = AnsibleFulfillmentProvider(
            job_service=job_service,
            job_queue_provider=lambda: MagicMock(),
            port_allocator=self._NoLeaseAllocator(),
        )

        prepared = provider.prepare_teardown(
            _settlement_result(), self._pool_on("site-b")
        )

        assert prepared.payload["parameters"]["relay_id"] is None

