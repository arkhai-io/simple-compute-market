"""Bare metal's default mock output, driven through the real executor and codec."""

from __future__ import annotations

import asyncio

import pytest
from arkhai_bare_metal import NODE_GRANT_ACCESS_ACTION, NODE_RECLAIM_ACCESS_ACTION
from compute_provisioning.jobs import JobFailure, JobSuccess
from compute_provisioning.jobs.executor_mock import MockRule
from compute_provisioning_ansible import MockAnsibleRunner
from compute_provisioning_contracts import (
    DELIVERY_EVIDENCE_RESULT_KIND,
    AccessEndpoint,
    DeliveryEvidence,
)

from bare_metal_provisioning_adapter.codec import BareMetalJobParams
from bare_metal_provisioning_adapter.services.mock_output import (
    DEFAULT_MOCK_SSH_USER,
    bare_metal_mock_output,
)

from execution import HOST, executor, job_run


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
    assert outcome.result.result_kind == DELIVERY_EVIDENCE_RESULT_KIND
    evidence = DeliveryEvidence.model_validate(outcome.result.value)
    assert evidence.endpoints == (
        AccessEndpoint(protocol="ssh", host="10.0.0.5", port=2201, user="tenant-a"),
    )


@pytest.mark.asyncio
async def test_default_grant_without_a_tenant_names_the_mock_user() -> None:
    outcome = await _execute(
        _mock(),
        _params(NODE_GRANT_ACCESS_ACTION, ssh_user=None),
    )

    assert outcome.result.value["endpoints"][0]["user"] == DEFAULT_MOCK_SSH_USER


@pytest.mark.asyncio
async def test_default_reclaim_reports_the_reclaim_and_its_policy() -> None:
    outcome = await _execute(
        _mock(),
        _params(NODE_RECLAIM_ACCESS_ACTION, reclaim_policy="lock_user"),
    )

    assert outcome.result.value["action"] == NODE_RECLAIM_ACCESS_ACTION
    assert outcome.result.value["status"] == "success"
    assert outcome.result.value["reclaim_policy"] == "lock_user"


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

    assert outcome.result.result_kind == DELIVERY_EVIDENCE_RESULT_KIND
    assert bare_metal.list_rules() == []
