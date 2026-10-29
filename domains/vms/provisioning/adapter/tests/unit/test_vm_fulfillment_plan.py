"""VM's fulfillment plan: what a VM's create and teardown jobs run.

The provider mechanics (submission, contract identity, status, delivery) are the
compute family's and are tested with its job-backed provider; these are VM's
own rules.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from market_core import VersionedEnvelope
from market_fulfillment import ProviderConfigInvalidError, SettlementResource

from vm_provisioning_adapter.codec import VmAnsibleCodec
from vm_provisioning_adapter.guest_names import (
    GUEST_NAME_LENGTH,
    fulfillment_guest_name,
    guest_login,
)
from vm_provisioning_adapter.runtime import VmProvisioningRuntime
from vm_provisioning_adapter.services.vm_fulfillment_plan import VmFulfillmentPlan


def _request(**overrides) -> VersionedEnvelope:
    payload = {
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
        "resource_kind": "vm", "provider": "vm.ansible", "host_id": "kvm1",
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

    def allocate_in_session(self, db, **kwargs):
        self.allocated.append(kwargs)
        return SimpleNamespace(id="lease-1", relay_id=kwargs["relay_id"], remote_port=6100)

    def find_active_lease(self, *, owner_kind, owner_id):
        return self._lease


SERVICE_PLAYBOOK = "/opt/service/vm-operations.yaml"


def _plan(allocator=None, *, vm_playbook_path=SERVICE_PLAYBOOK) -> VmFulfillmentPlan:
    return VmFulfillmentPlan(
        reserved_var_keys=VmAnsibleCodec().reserved_var_keys,
        vm_playbook_path=vm_playbook_path,
        port_allocator=allocator,
    )


GUEST = fulfillment_guest_name("alloc-1")
_ACCEPTANCE_SESSION = object()


def _create(
    plan, *, resource=None, pool_config=None, request=None, allocate=True,
    reservation="alloc-1", db=_ACCEPTANCE_SESSION,
):
    return plan.prepare_create(
        capacity_reservation_id=reservation,
        request=request or _request(),
        resource=resource or _resource(),
        pool_config=pool_config if pool_config is not None else _pool_config(),
        allocate=allocate,
        db=db,
    )


def _teardown(plan, *, pool_config=None):
    return plan.prepare_teardown(
        capacity_reservation_id="alloc-1",
        resource=_resource(),
        host_id="kvm1",
        executor_target=GUEST,
        create_parameters={},
        pool_config=pool_config if pool_config is not None else _pool_config(),
    )


class TestCreate:
    def test_a_create_runs_on_the_host_and_names_the_guest(self):
        prepared = _create(_plan())

        assert (prepared.offering_mode, prepared.action) == ("vm", "create")
        assert (prepared.host_id, prepared.executor_target) == ("kvm1", GUEST)
        assert prepared.parameters["playbook_path"] == "playbooks/vm-operations.yaml"
        assert prepared.parameters["escrow_uid"] == "alloc-1"
        json.dumps(prepared.parameters)  # stored as the job's parameters

    def test_another_offering_mode_and_a_blank_playbook_are_refused(self):
        with pytest.raises(ProviderConfigInvalidError, match="offering mode"):
            _create(_plan(), resource=_resource(offering_mode="bare_metal"))
        with pytest.raises(ProviderConfigInvalidError, match="pool configuration"):
            _create(_plan(), pool_config=_pool_config(playbook_path=""))


class TestPlaybookFrozenAtPreparation:
    """A job runs the pool's playbook when the pool states one, and otherwise the
    service's as configured when the job is prepared."""

    @pytest.mark.parametrize("prepare", [_create, _teardown], ids=["create", "teardown"])
    def test_a_pool_stating_no_playbook_freezes_the_services(self, prepare):
        prepared = prepare(_plan(), pool_config=_pool_config(playbook_path=None))

        assert prepared.parameters["playbook_path"] == SERVICE_PLAYBOOK

    @pytest.mark.parametrize("prepare", [_create, _teardown], ids=["create", "teardown"])
    def test_a_pools_own_playbook_wins_over_the_services(self, prepare):
        prepared = prepare(_plan(), pool_config=_pool_config())

        assert prepared.parameters["playbook_path"] == "playbooks/vm-operations.yaml"

    def test_each_job_takes_the_playbook_configured_when_it_is_prepared(self):
        """The path is written into the job's stored parameters, which the VM
        codec runs in preference to the executor's playbook; so a job prepared
        after the service is reconfigured takes the new path, and one prepared
        before keeps the old."""
        pool = _pool_config(playbook_path=None)
        created = _create(_plan(), pool_config=pool)

        reconfigured = _plan(vm_playbook_path="/opt/service/vm-operations-v2.yaml")
        teardown = _teardown(reconfigured, pool_config=pool)

        assert created.parameters["playbook_path"] == SERVICE_PLAYBOOK
        assert teardown.parameters["playbook_path"] == "/opt/service/vm-operations-v2.yaml"

    def test_the_runtime_gives_its_plan_the_services_configured_playbook(self):
        runtime = VmProvisioningRuntime(
            config=SimpleNamespace(resolved_vm_playbook_path=Path("/opt/service/vm.yaml")),
            session_factory=None,
            job_queue_provider=lambda: None,
            ansible_service=None,
            codec=VmAnsibleCodec(),
            host_authority=None,
            pool_config_handler=None,
            job_engine=None,
            job_submission=None,
            vm_operations_service=None,
            host_operations_service=None,
            relay_port_allocator=None,
            relay_service=None,
        )

        prepared = _create(
            runtime.fulfillment_plan(), pool_config=_pool_config(playbook_path=None)
        )

        assert prepared.parameters["playbook_path"] == "/opt/service/vm.yaml"

    @pytest.mark.parametrize("prepare", [_create, _teardown], ids=["create", "teardown"])
    def test_no_playbook_from_the_pool_or_the_service_is_refused(self, prepare):
        with pytest.raises(ProviderConfigInvalidError, match="vm_playbook_path"):
            prepare(_plan(vm_playbook_path=None), pool_config=_pool_config(playbook_path=None))


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

    def test_a_reservation_without_a_gpu_count_provisions_no_gpu(self):
        prepared = _create(
            _plan(), resource=_resource(dimensions={"vcpu_count": 8, "ram_gb": 32})
        )

        assert prepared.parameters["vm_vcpus"] == 8
        # Stored unset, as every sizing field nothing commits is.
        assert prepared.parameters["vm_gpu_count"] is None
        assert prepared.parameters["gpu_provisioned"] is None

    def test_a_reservation_with_a_gpu_count_provisions_its_gpus(self):
        prepared = _create(_plan(), resource=_resource(dimensions={"gpu_count": 2}))

        assert prepared.parameters["vm_gpu_count"] == 2
        assert prepared.parameters["gpu_provisioned"] is True

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

    def test_relay_allocation_requires_the_acceptance_session(self):
        allocator = _Allocator()
        with pytest.raises(ProviderConfigInvalidError, match="acceptance session"):
            _create(_plan(allocator), pool_config=_relay_pool_config(), db=None)
        assert allocator.allocated == []

    def test_a_request_naming_a_relay_is_refused_before_a_port_is_leased(self):
        allocator = _Allocator()
        # A documentation-range address and a placeholder token, never real.
        with pytest.raises(ProviderConfigInvalidError, match="connectivity"):
            _create(
                _plan(allocator),
                pool_config=_relay_pool_config(),
                request=_request(
                    connectivity={"relay_addr": "198.51.100.1", "relay_token": "caller-token"}
                ),
            )

        assert allocator.allocated == []


class TestGuestName:
    """Provisioning names the guest; every playbook use of the name accepts it."""

    def test_the_derivation_never_changes(self):
        """A retried fulfillment names its guest again; a changed namespace,
        prefix, or algorithm would rename a guest prepared by an earlier
        release."""
        assert fulfillment_guest_name("alloc-1") == "tenant-ea780533c5915a9b85ba26b9"

    def test_the_name_is_stable_per_reservation_and_distinct_across_them(self):
        assert fulfillment_guest_name("alloc-1") == fulfillment_guest_name("alloc-1")
        names = {fulfillment_guest_name(f"reservation-{index}") for index in range(1000)}
        assert len(names) == 1000

    def test_the_name_satisfies_the_hostname_login_and_shell_rules(self):
        for reservation in ("alloc-1", "01890a5d-ac96-774b-bcce-b302099a8057", "x" * 200):
            name = fulfillment_guest_name(reservation)
            assert len(name) == GUEST_NAME_LENGTH == 31
            # A hostname label, in characters the shell takes literally.
            assert re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", name)
            # The tenant login the playbook derives: useradd's limit is 32.
            login = guest_login(name)
            assert len(login) <= 32 and login[0].isalpha()

    def test_no_name_contains_another(self):
        # Every create deletes each /tmp file whose name contains its guest's.
        names = [fulfillment_guest_name(f"reservation-{index}") for index in range(200)]
        assert not any(a != b and a in b for a in names for b in names)

    def test_a_create_names_the_guest_from_its_reservation(self):
        assert _create(_plan()).executor_target == GUEST
        assert _create(_plan(), allocate=False).executor_target == GUEST
        other = _create(_plan(), reservation="alloc-2")
        assert other.executor_target == fulfillment_guest_name("alloc-2") != GUEST
        assert other.parameters["vm_target"] == other.executor_target

    def test_a_request_naming_the_guest_is_refused(self):
        with pytest.raises(ProviderConfigInvalidError, match="vm_target"):
            _create(_plan(), request=_request(vm_target="tenant-ab12"))


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
        assert (prepared.host_id, prepared.executor_target) == ("kvm1", GUEST)
        assert prepared.parameters["vm_target"] == GUEST
        assert prepared.parameters["playbook_path"] == "playbooks/vm-operations.yaml"

    def test_the_relay_is_the_leases_not_the_pools(self):
        prepared = _teardown(
            _plan(_Allocator(relay_id="site-a")), pool_config=_pool_config(relay_id="site-b")
        )

        assert prepared.parameters["relay_id"] == "site-a"

    def test_a_released_lease_or_a_direct_vm_names_no_relay(self):
        assert _teardown(_plan(_Allocator(leased=False))).parameters["relay_id"] is None
        assert _teardown(_plan(None)).parameters["relay_id"] is None
