"""Bare metal's default mock output, driven through the real executor and codec."""

from __future__ import annotations

import asyncio

import pytest
from arkhai_bare_metal import NODE_GRANT_ACCESS_ACTION, NODE_RECLAIM_ACCESS_ACTION
from compute_provisioning.jobs import JobFailure, JobSuccess
from compute_provisioning.jobs.executor_mock import MockRule
from compute_provisioning_ansible import MockAnsibleRunner, MockPlaybook, read_fact
from compute_provisioning_ansible.runner import extract_fact, inventory_target
from compute_provisioning_contracts import (
    CREATE_JOB_RESULT_KIND,
    AccessEndpoint,
    CreateJobResult,
)

from bare_metal_provisioning_adapter.codec import BareMetalJobParams
from bare_metal_provisioning_adapter.services.mock_output import (
    DEFAULT_MOCK_SSH_USER,
    bare_metal_mock_output,
)

from execution import HOST, executor, host_with, job_run


def _mock() -> MockAnsibleRunner:
    """The bare-metal mock runner, as the bare-metal runtime composes it."""
    return MockAnsibleRunner(default_output=bare_metal_mock_output)


def _params(action: str, **overrides) -> BareMetalJobParams:
    values = {
        "action": action,
        "host_id": HOST.host_id,
        "physical_host_id": "physical-1",
        "escrow_uid": "escrow-1",
        "ssh_user": "tenant-a",
    }
    values.update(overrides)
    return BareMetalJobParams(**values)


async def _execute(mock, params: BareMetalJobParams):
    return await executor(mock).execute(job_run(params))


@pytest.mark.asyncio
async def test_default_grant_reports_the_access_fact_for_the_registered_host() -> None:
    outcome = await _execute(
        _mock(), _params(NODE_GRANT_ACCESS_ACTION)
    )

    assert isinstance(outcome, JobSuccess)
    assert outcome.credentials == ()
    assert outcome.result.result_kind == CREATE_JOB_RESULT_KIND
    created = CreateJobResult.model_validate(outcome.result.value)
    assert created.detail["physical_host_id"] == "physical-1"
    # The buyer's endpoint is the host's tenant-facing address with its
    # connection port; the fact's own host and port, the provisioner's route,
    # stay detail.
    assert created.evidence.endpoints == (
        AccessEndpoint(protocol="ssh", host="203.0.113.5", port=2201, user="tenant-a"),
    )
    assert (created.detail["host"], created.detail["port"]) == ("10.0.0.5", "2201")


@pytest.mark.asyncio
async def test_default_grant_reaches_a_host_on_its_tenant_route() -> None:
    host = host_with(public_host="192.0.2.10", public_port=22)

    outcome = await executor(_mock()).execute(job_run(_params(NODE_GRANT_ACCESS_ACTION), host))

    (endpoint,) = CreateJobResult.model_validate(outcome.result.value).evidence.endpoints
    assert (endpoint.host, endpoint.port, endpoint.user) == ("192.0.2.10", 22, "tenant-a")


@pytest.mark.parametrize("action", [NODE_GRANT_ACCESS_ACTION, NODE_RECLAIM_ACCESS_ACTION])
def test_the_default_output_is_the_shipped_yaml_form(action) -> None:
    """A ``var:`` fact in the YAML format, which only the ``msg:`` JSON block
    beside it carries as JSON, as the packaged configuration prints them."""
    params = _params(action)
    stdout = bare_metal_mock_output(
        MockPlaybook(
            parameters=params.model_dump(mode="json"),
            limit=HOST.host_id,
            hosts={HOST.host_id: inventory_target(HOST)},
        )
    )
    fact_name = f"{action}_data"

    assert f"    {fact_name}:\n" in stdout and f'"{fact_name}":' not in stdout
    assert "    msg: |-\n" in stdout
    assert extract_fact(stdout, fact_name) is None
    fact = read_fact(stdout, fact_name, action=action)
    assert (fact["action"], fact["host_id"], fact["ssh_user"], fact["status"]) == (
        action, HOST.host_id, "tenant-a", "success",
    )


@pytest.mark.asyncio
async def test_default_grant_for_a_job_naming_no_tenant_reports_no_evidence() -> None:
    """The role refuses such a grant; a default output naming the mock account
    for it matches no account the job names, so it yields no evidence."""
    outcome = await _execute(
        _mock(),
        _params(NODE_GRANT_ACCESS_ACTION, ssh_user=None),
    )

    assert outcome.result.value["evidence"] is None
    assert outcome.result.value["detail"]["ssh_user"] == DEFAULT_MOCK_SSH_USER


@pytest.mark.asyncio
async def test_default_reclaim_reports_the_reclaim_and_its_policy() -> None:
    outcome = await _execute(
        _mock(),
        _params(NODE_RECLAIM_ACCESS_ACTION, reclaim_policy="lock_user"),
    )

    assert outcome.result.value["action"] == NODE_RECLAIM_ACCESS_ACTION
    assert outcome.result.value["status"] == "success"
    assert outcome.result.value["reclaim_policy"] == "lock_user"
    assert outcome.result.value["account_present"] == "true"


@pytest.mark.asyncio
async def test_a_rule_holds_then_fails_a_grant() -> None:
    mock = _mock()
    mock.add_rule(
        MockRule(
            rule_id="gate",
            match={"action": NODE_GRANT_ACCESS_ACTION},
            pause_before_result=True,
            fail_with="host unreachable",
        )
    )

    running = asyncio.create_task(_execute(mock, _params(NODE_GRANT_ACCESS_ACTION)))
    await asyncio.wait_for(mock.rules.wait_until_held("gate"), timeout=1.0)
    assert not running.done()

    mock.resume_rule("gate")
    outcome = await asyncio.wait_for(running, timeout=1.0)
    assert isinstance(outcome, JobFailure)
    assert outcome.error.message == "host unreachable"
    assert outcome.error.retryable is False


@pytest.mark.asyncio
async def test_a_rule_for_another_domains_runner_never_meets_a_bare_metal_job() -> None:
    bare_metal = _mock()
    vm = MockAnsibleRunner(default_output=lambda playbook: "")
    vm.add_rule(MockRule(rule_id="vm-any", match={}, fail_with="vm only"))

    outcome = await _execute(bare_metal, _params(NODE_GRANT_ACCESS_ACTION))

    assert outcome.result.result_kind == CREATE_JOB_RESULT_KIND
    assert bare_metal.list_rules() == []
