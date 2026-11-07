"""Every job's submission: the host it may run against, and the identity it takes."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from compute_provisioning.hosts.service import HostNotFoundError
from compute_provisioning.jobs import JobActionRequest
from compute_provisioning.jobs.submission import (
    HostDisabledError,
    JobSubmissionService,
    contract_operation_id,
)
from compute_provisioning_contracts import JobSubmitResponse


class _Engine:
    def __init__(self) -> None:
        self.submitted: list[dict] = []

    async def submit(self, **fields) -> JobSubmitResponse:
        self.submitted.append(fields)
        return JobSubmitResponse(job_id=fields["operation_id"] or "generated", status="queued")


class _Hosts:
    def __init__(self, **hosts: bool) -> None:
        self._hosts = hosts

    def get_host(self, host_id: str):
        if host_id not in self._hosts:
            return None
        return SimpleNamespace(host_id=host_id, enabled=self._hosts[host_id])


def _service(engine: _Engine, **hosts: bool) -> JobSubmissionService:
    return JobSubmissionService(
        engine=engine, hosts=_Hosts(**hosts), job_queue_provider=lambda: "queue"
    )


def _contract(operation: str = "create") -> JobActionRequest:
    return JobActionRequest(
        capacity_reservation_id="r-1",
        offering_mode="bare_metal",
        action_kind=operation,
        idempotency_key=f"r-1:{operation}",
    )


async def _submit(service: JobSubmissionService, host_id: str, **fields):
    return await service.submit(
        offering_mode="bare_metal",
        action="node_grant_access",
        host_id=host_id,
        params={"p": 1},
        **fields,
    )


@pytest.mark.asyncio
async def test_a_job_against_an_unregistered_host_is_refused_before_the_engine() -> None:
    engine = _Engine()

    with pytest.raises(HostNotFoundError):
        await _submit(_service(engine), "missing")

    assert engine.submitted == []


@pytest.mark.asyncio
async def test_only_a_create_needs_its_host_enabled() -> None:
    """Disabling a host stops new delivery to it, not the teardown of what is
    already there or an operator's work on it."""
    engine = _Engine()
    service = _service(engine, h1=False)

    with pytest.raises(HostDisabledError):
        await _submit(service, "h1", contract=_contract("create"), require_enabled_host=True)
    teardown = await _submit(service, "h1", contract=_contract("teardown"))
    operator = await _submit(service, "h1", operation_id="op-1")

    assert [fields["host_id"] for fields in engine.submitted] == ["h1", "h1"]
    assert teardown.job_id == contract_operation_id(_contract("teardown"))
    assert operator.job_id == "op-1"


@pytest.mark.asyncio
async def test_a_contract_job_takes_the_contract_operation_id() -> None:
    engine = _Engine()
    service = _service(engine, h1=True)

    first = await _submit(service, "h1", contract=_contract())
    again = await _submit(service, "h1", contract=_contract())

    assert first.job_id == again.job_id == contract_operation_id(_contract())
    assert contract_operation_id(_contract("create")) != contract_operation_id(
        _contract("teardown")
    )
    assert engine.submitted[0]["job_queue"] == "queue"
    assert engine.submitted[0]["contract"] == _contract()


@pytest.mark.asyncio
async def test_a_contract_job_refuses_another_operation_id() -> None:
    engine = _Engine()

    with pytest.raises(ValueError, match="contract's operation id"):
        await _submit(_service(engine, h1=True), "h1", contract=_contract(), operation_id="op-9")

    assert engine.submitted == []


@pytest.mark.asyncio
async def test_an_operator_job_keeps_its_own_operation_id_or_none() -> None:
    engine = _Engine()
    service = _service(engine, h1=True)

    await _submit(service, "h1", operation_id="op-2")
    await _submit(service, "h1")

    assert [fields["operation_id"] for fields in engine.submitted] == ["op-2", None]
    assert [fields["contract"] for fields in engine.submitted] == [None, None]
