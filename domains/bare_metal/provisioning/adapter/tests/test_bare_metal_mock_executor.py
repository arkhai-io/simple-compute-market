from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from arkhai_bare_metal import (
    BARE_METAL_OFFERING_MODE,
    NODE_GRANT_ACCESS_ACTION,
    NODE_RECLAIM_ACCESS_ACTION,
)
from compute_provisioning.jobs.executor_mock import MockRule
from vm_provisioning_adapter.models.jobs_model import AnsibleJobParams
from compute_provisioning_ansible.runner import AnsibleError
from vm_provisioning_adapter.services.ansible_job_executor import AnsibleJobExecutor
from vm_provisioning_adapter.services.mock_ansible_service import (
    ProgrammableMockAnsibleService,
)

from bare_metal_provisioning_adapter.services.bare_metal_mock_executor import (
    DEFAULT_MOCK_SSH_USER,
    BareMetalMockAnsibleService,
)

HOST = SimpleNamespace(
    host_id="bm-node-1",
    ssh_host="10.0.0.5",
    ssh_port=2201,
    public_host="203.0.113.5",
)


def _params(action: str, **overrides) -> AnsibleJobParams:
    values = {
        "host_id": HOST.host_id,
        "vm_action": action,
        "offering_mode": BARE_METAL_OFFERING_MODE,
        "executor_action": action,
        "physical_host_id": "physical-1",
        "escrow_uid": "escrow-1",
        "ssh_user": "tenant-a",
    }
    values.update(overrides)
    return AnsibleJobParams(**values)


async def _run(mock, params):
    mock.write_inventory([HOST])
    run = mock.start_playbook(
        playbook_path=Path("/playbooks/node-access.yaml"),
        inventory_path=Path("/tmp/inventory"),
        extra_vars_path=Path("/tmp/vars"),
        limit=params.host_id,
    )
    run._params = params
    result = await mock.wait_for_playbook(run, timeout_seconds=5)
    return mock.parse_playbook_result(
        result, params, tenant_address=HOST.public_host
    )


def _job_payload(run_result) -> dict:
    return AnsibleJobExecutor.build_result_payload(run_result)


@pytest.mark.asyncio
async def test_default_grant_parses_into_the_fields_fulfillment_reads() -> None:
    mock = BareMetalMockAnsibleService(MagicMock())

    run_result = await _run(mock, _params(NODE_GRANT_ACCESS_ACTION))
    fact = run_result.ansible_result
    payload = _job_payload(run_result)

    assert fact["action"] == NODE_GRANT_ACCESS_ACTION
    assert fact["ssh_user"] == "tenant-a"
    assert fact["host"] == HOST.ssh_host
    assert fact["port"] == str(HOST.ssh_port)
    assert fact["physical_host_id"] == "physical-1"
    assert payload["host"] == HOST.ssh_host
    assert payload["ansible_result"]["port"] == str(HOST.ssh_port)
    assert run_result.host_ip == HOST.public_host


@pytest.mark.asyncio
async def test_default_grant_without_a_tenant_names_the_mock_user() -> None:
    mock = BareMetalMockAnsibleService(MagicMock())

    run_result = await _run(mock, _params(NODE_GRANT_ACCESS_ACTION, ssh_user=None))

    assert run_result.ansible_result["ssh_user"] == DEFAULT_MOCK_SSH_USER


@pytest.mark.asyncio
async def test_default_reclaim_parses_as_a_reclaim() -> None:
    mock = BareMetalMockAnsibleService(MagicMock())

    run_result = await _run(mock, _params(NODE_RECLAIM_ACCESS_ACTION))

    assert run_result.ansible_result["action"] == NODE_RECLAIM_ACCESS_ACTION
    assert run_result.ansible_result["status"] == "success"


@pytest.mark.asyncio
async def test_a_rule_holds_then_fails_a_grant() -> None:
    mock = BareMetalMockAnsibleService(MagicMock())
    mock.add_rule(
        MockRule(
            rule_id="gate",
            match={"executor_action": NODE_GRANT_ACCESS_ACTION},
            pause_before_result=True,
            fail_with="host unreachable",
        )
    )

    running = asyncio.create_task(_run(mock, _params(NODE_GRANT_ACCESS_ACTION)))
    await asyncio.wait_for(mock.rules.wait_until_held("gate"), timeout=1.0)
    assert not running.done()

    mock.resume_rule("gate")
    with pytest.raises(AnsibleError, match="host unreachable"):
        await asyncio.wait_for(running, timeout=1.0)


@pytest.mark.asyncio
async def test_rules_are_per_adapter() -> None:
    bare_metal = BareMetalMockAnsibleService(MagicMock())
    vm = ProgrammableMockAnsibleService(MagicMock())
    vm.add_rule(MockRule(rule_id="vm-any", match={}, fail_with="vm only"))

    run_result = await _run(bare_metal, _params(NODE_GRANT_ACCESS_ACTION))

    assert run_result.ansible_result["action"] == NODE_GRANT_ACCESS_ACTION
    assert bare_metal.list_rules() == []
    assert [rule["rule_id"] for rule in vm.list_rules()] == ["vm-any"]
