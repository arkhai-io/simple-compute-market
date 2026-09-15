"""A bare-metal access job names the lease generation it belongs to.

The host's lease units, encrypted volume and runtime view are all named from
the generation. If a pool could choose that value, a pool could aim one lease's
grant at another lease's prepared environment, so the generation is a built-in
job variable: emitted by the service and reserved against pool-supplied
extra-vars rather than merged with them.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from vm_provisioning_adapter.models.jobs_model import AnsibleJobParams
from vm_provisioning_adapter.services.ansible_service import AnsibleService


def _params(**overrides) -> AnsibleJobParams:
    base = dict(
        vm_host="bm1",
        vm_action="node_grant_access",
        offering_mode="bare_metal",
        executor_action="node_grant_access",
        executor_target="bm1",
        ssh_user="arkhai-70f5f19cca87f7e6",
        lease_generation="res-91f2",
    )
    base.update(overrides)
    return AnsibleJobParams(**base)


def _vars_text(params: AnsibleJobParams) -> str:
    return AnsibleService(MagicMock())._build_vm_vars(params)


def test_the_lease_generation_reaches_the_playbook():
    rendered = _vars_text(_params())

    assert 'bare_metal_lease_generation: "res-91f2"' in rendered


def test_a_job_without_a_generation_states_none():
    """Absence is silence, not an empty string the role would treat as a name."""
    rendered = _vars_text(_params(lease_generation=None))

    assert "bare_metal_lease_generation" not in rendered


def test_the_generation_is_reserved_against_pool_supplied_vars():
    service = AnsibleService(MagicMock())

    reserved = service.reserved_var_keys(_params())

    assert "bare_metal_lease_generation" in reserved


def test_a_pool_cannot_override_the_generation():
    params = _params(provider_extra_vars={"bare_metal_lease_generation": "res-other"})

    with pytest.raises(ValueError, match="bare_metal_lease_generation"):
        _vars_text(params)
