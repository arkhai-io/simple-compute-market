"""A GPU guest's operator settings come from its pool alone.

`vm_passthrough_boot_gpu`, `vm_setup_wait_attempts`,
`vm_setup_wait_interval_seconds`, and `vm_autostart` are the pool's operator's:
the VM role defaults them and reads them as playbook variables, so whoever can
set a variable of that name decides whether a host's boot GPU is passed
through, how long a create waits, and whether its guest restarts with the host.
This pins that only the pool's provider configuration can: no field of a
storefront's fulfillment request and no job variable carries any of them, and
a pool's `extra_vars` reach the playbook's extra-vars document with their types
intact, so the role's type check reads what the operator wrote.
"""

from __future__ import annotations

import dataclasses

import pytest
import yaml
from compute_provisioning_ansible.codec import render_extra_vars
from market_core import VersionedEnvelope
from market_fulfillment import ProviderConfigInvalidError, SettlementResource

from vm_provisioning_adapter.codec import VmAnsibleCodec, vm_job_params
from vm_provisioning_adapter.models.fulfillment_model import VmFulfillmentRequirements
from vm_provisioning_adapter.models.jobs_model import VmJobParams
from vm_provisioning_adapter.services.vm_fulfillment_plan import VmFulfillmentPlan

SETTINGS = {
    "vm_passthrough_boot_gpu": True,
    "vm_setup_wait_attempts": 40,
    "vm_setup_wait_interval_seconds": 15,
    "vm_autostart": False,
}


def _create(*, request: dict | None = None, extra_vars: dict | None = None):
    plan = VmFulfillmentPlan(
        reserved_var_keys=VmAnsibleCodec().reserved_var_keys,
        vm_playbook_path="/opt/service/vm-operations.yaml",
    )
    payload = {"ssh_pubkey": "ssh-ed25519 AAAA", "gpu_provisioned": True, **(request or {})}
    return plan.prepare_create(
        capacity_reservation_id="alloc-1",
        request=VersionedEnvelope(kind="vm.fulfillment.request", schema_version=1, payload=payload),
        resource=SettlementResource(
            settlement_resource_id="kvm1", pool_id="pool-1", offering_mode="vm",
            resource_kind="vm", provider="vm.ansible", host_id="kvm1",
            dimensions={"gpu_count": 1},
        ),
        pool_config={
            "playbook_path": "playbooks/vm-operations.yaml",
            "requirement_delegate": "vm_management_v1",
            "extra_vars": extra_vars or {},
        },
        allocate=False,
        db=None,
    )


def test_no_field_of_a_fulfillment_request_names_a_setting() -> None:
    assert not set(VmFulfillmentRequirements.model_fields) & set(SETTINGS)


@pytest.mark.parametrize("name", sorted(SETTINGS))
def test_a_request_naming_a_setting_is_refused(name: str) -> None:
    with pytest.raises(ProviderConfigInvalidError, match=name):
        _create(request={name: SETTINGS[name]})


def test_no_job_variable_names_a_setting() -> None:
    """So a pool's setting never collides with, or is overridden by, a job's."""
    assert not {field.name for field in dataclasses.fields(VmJobParams)} & set(SETTINGS)
    params = vm_job_params(_create().parameters, host_id="kvm1")
    assert not set(VmAnsibleCodec().variables(params)) & set(SETTINGS)


def test_each_reaches_the_playbook_from_the_pools_extra_vars_with_its_type() -> None:
    prepared = _create(extra_vars=SETTINGS)
    assert prepared.parameters["provider_extra_vars"] == SETTINGS

    params = vm_job_params(prepared.parameters, host_id="kvm1")
    document = yaml.safe_load(
        render_extra_vars(VmAnsibleCodec().variables(params), params.provider_extra_vars)
    )

    assert {name: document[name] for name in SETTINGS} == SETTINGS
    assert document["vm_passthrough_boot_gpu"] is True
    assert document["vm_autostart"] is False
