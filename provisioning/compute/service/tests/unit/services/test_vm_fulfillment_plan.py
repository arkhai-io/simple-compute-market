"""VM's fulfillment plan: what a VM's create and teardown jobs run.

The provider mechanics (submission, contract identity, status, delivery) are the
compute family's and are tested with its job-backed provider; these are VM's
own rules.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from market_core import VersionedEnvelope
from market_fulfillment import ProviderConfigInvalidError, SettlementResource

from vm_provisioning_adapter.codec import VmAnsibleCodec
from vm_provisioning_adapter.services.vm_fulfillment_plan import VmFulfillmentPlan


def _request(**overrides) -> VersionedEnvelope:
    payload = {
        "vm_target": "vm-alloc-1",
        "vm_ram": 4096,
        "vm_vcpus": 2,
        "vm_disk_size": "40G",
        "ssh_pubkey": "ssh-ed25519 AAAA",
        **overrides,
    }
    return VersionedEnvelope(kind="vm.fulfillment.request", schema_version=1, payload=payload)


def _resource(**overrides) -> SettlementResource:
    values = {
        "settlement_resource_id": "kvm1", "pool_id": "pool-1", "offering_mode": "vm",
        "resource_kind": "vm", "provider": "ansible", "host_id": "kvm1",
    }
    values.update(overrides)
    return SettlementResource(**values)


def _pool_config(**overrides) -> dict:
    values = {
        "playbook_path": "playbooks/vm-operations.yaml",
        "requirement_delegate": "vm_management_v1",
        "extra_vars": {},
    }
    values.update(overrides)
    return values


def _relay_pool_config(**overrides) -> dict:
    relay = {
        "relay_id": "site-a", "relay_addr": "203.0.113.9", "relay_port": 7000,
        "vm_port_range_start": 6100, "vm_port_range_count": 100,
        "relay_token": "admission-token",
    }
    return _pool_config(**{**relay, **overrides})


class _Allocator:
    def __init__(self, *, relay_id: str = "site-a", port: int = 6100, leased: bool = True):
        self.allocated: list[dict] = []
        self._lease = (
            SimpleNamespace(id="lease-1", relay_id=relay_id, remote_port=port) if leased else None
        )

    def allocate(self, **kwargs):
        self.allocated.append(kwargs)
        return SimpleNamespace(id="lease-1", relay_id=kwargs["relay_id"], remote_port=6100)

    def find_active_lease(self, *, owner_kind, owner_id):
        return self._lease


def _plan(allocator=None) -> VmFulfillmentPlan:
    return VmFulfillmentPlan(
        reserved_var_keys=VmAnsibleCodec().reserved_var_keys, port_allocator=allocator
    )


def _create(plan, *, resource=None, pool_config=None, request=None, allocate=True):
    return plan.prepare_create(
        capacity_reservation_id="alloc-1",
        request=request or _request(),
        resource=resource or _resource(),
        pool_config=pool_config if pool_config is not None else _pool_config(),
        allocate=allocate,
    )


def _teardown(plan, *, pool_config=None):
    return plan.prepare_teardown(
        capacity_reservation_id="alloc-1",
        resource=_resource(),
        host_id="kvm1",
        executor_target="vm-alloc-1",
        create_parameters={},
        pool_config=pool_config if pool_config is not None else _pool_config(),
    )


class TestCreate:
    def test_a_create_runs_on_the_host_and_names_the_guest(self):
        prepared = _create(_plan())

        assert (prepared.offering_mode, prepared.action) == ("vm", "create")
        assert (prepared.host_id, prepared.executor_target) == ("kvm1", "vm-alloc-1")
        assert prepared.parameters["playbook_path"] == "playbooks/vm-operations.yaml"
        assert prepared.parameters["escrow_uid"] == "alloc-1"
        json.dumps(prepared.parameters)  # stored as the job's parameters

    def test_another_offering_mode_and_a_missing_playbook_are_refused(self):
        with pytest.raises(ProviderConfigInvalidError, match="offering mode"):
            _create(_plan(), resource=_resource(offering_mode="bare_metal"))
        with pytest.raises(ProviderConfigInvalidError, match="pool configuration"):
            _create(_plan(), pool_config={"extra_vars": {}})


class TestSizingPrecedence:
    """Sizing comes from the reservation's committed dimensions, else the pool's
    defaults, else is left unset; never from the request."""

    def test_reservation_dimensions_win_over_the_request_and_pool_defaults(self):
        prepared = _create(
            _plan(),
            resource=_resource(dimensions={"vcpu_count": 8, "ram_gb": 16, "disk_gb": 200}),
            pool_config=_pool_config(default_vm_ram=1024, default_vm_vcpus=1),
        )

        assert prepared.parameters["vm_vcpus"] == 8
        assert prepared.parameters["vm_ram"] != 4096

    def test_pool_defaults_fill_what_the_reservation_does_not_commit(self):
        prepared = _create(
            _plan(),
            pool_config=_pool_config(
                default_vm_ram=2048, default_vm_vcpus=3, default_vm_disk_size="30G"
            ),
        )

        assert (prepared.parameters["vm_ram"], prepared.parameters["vm_vcpus"]) == (2048, 3)
        assert prepared.parameters["vm_disk_size"] == "30G"

    def test_sizing_is_left_unset_when_neither_specifies_it(self):
        prepared = _create(_plan())

        assert prepared.parameters["vm_ram"] is None
        assert prepared.parameters["vm_vcpus"] is None

    def test_an_unknown_requirement_delegate_is_refused(self):
        with pytest.raises(ProviderConfigInvalidError):
            _create(_plan(), pool_config=_pool_config(requirement_delegate="no-such-delegate"))


class TestRelayAccessPath:
    def test_a_pool_with_no_relay_takes_the_direct_path(self):
        prepared = _create(_plan(_Allocator()))

        assert prepared.parameters["relay_id"] is None
        assert prepared.parameters["vm_remote_port"] is None

    def test_a_relay_backed_pool_leases_a_port_and_records_no_token(self):
        allocator = _Allocator()
        prepared = _create(_plan(allocator), pool_config=_relay_pool_config())

        assert prepared.parameters["relay_id"] == "site-a"
        assert prepared.parameters["vm_remote_port"] == 6100
        assert allocator.allocated == [{
            "relay_id": "site-a", "owner_kind": "fulfillment", "owner_id": "alloc-1",
            "host_id": "kvm1", "pool_id": "pool-1",
        }]
        assert "admission-token" not in json.dumps(prepared.parameters)

    def test_validation_leases_nothing_and_still_refuses_a_partial_relay(self):
        allocator = _Allocator()

        _create(_plan(allocator), pool_config=_relay_pool_config(), allocate=False)
        with pytest.raises(ProviderConfigInvalidError, match="no admission token"):
            _create(
                _plan(allocator), pool_config=_relay_pool_config(relay_token=None), allocate=False
            )

        assert allocator.allocated == []

    def test_a_relay_backed_pool_without_an_allocator_is_refused(self):
        with pytest.raises(ProviderConfigInvalidError, match="without a port allocator"):
            _create(_plan(None), pool_config=_relay_pool_config())

    def test_a_request_cannot_select_a_relay(self):
        prepared = _create(
            _plan(_Allocator()),
            request=_request(connectivity={"relay_addr": "198.51.100.1", "relay_port": 7000}),
        )

        assert prepared.parameters["relay_id"] is None


class TestExtraVariables:
    def test_a_pool_variable_replacing_a_job_variable_is_refused(self):
        with pytest.raises(ProviderConfigInvalidError, match="vm_target"):
            _create(_plan(), pool_config=_pool_config(extra_vars={"vm_target": "other"}))
        with pytest.raises(ProviderConfigInvalidError, match="vm_target"):
            _teardown(_plan(), pool_config=_pool_config(extra_vars={"vm_target": "other"}))

    def test_a_non_colliding_variable_is_carried(self):
        prepared = _create(_plan(), pool_config=_pool_config(extra_vars={"machine_id": "m"}))

        assert prepared.parameters["provider_extra_vars"] == {"machine_id": "m"}


class TestTeardown:
    def test_a_teardown_removes_the_recorded_guest_from_its_host(self):
        prepared = _teardown(_plan())

        assert prepared.action == "vm_remove"
        assert (prepared.host_id, prepared.executor_target) == ("kvm1", "vm-alloc-1")
        assert prepared.parameters["vm_target"] == "vm-alloc-1"
        assert prepared.parameters["playbook_path"] == "playbooks/vm-operations.yaml"

    def test_the_relay_is_the_leases_not_the_pools(self):
        prepared = _teardown(
            _plan(_Allocator(relay_id="site-a")), pool_config=_pool_config(relay_id="site-b")
        )

        assert prepared.parameters["relay_id"] == "site-a"

    def test_a_released_lease_or_a_direct_vm_names_no_relay(self):
        assert _teardown(_plan(_Allocator(leased=False))).parameters["relay_id"] is None
        assert _teardown(_plan(None)).parameters["relay_id"] is None
