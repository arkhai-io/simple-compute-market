"""The family's job-backed fulfillment provider, against a fake plan and job authority."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from compute_provisioning.job_fulfillment import (
    JOB_OPERATION_KIND,
    JobFulfillmentProvider,
    PreparedJob,
)
from compute_provisioning.jobs.db import JobStatus
from compute_provisioning.jobs.submission import JobSubmissionService, contract_operation_id
from compute_provisioning_contracts import (
    ACCESS_DELIVERY_KIND,
    DELIVERY_EVIDENCE_RESULT_KIND,
    AccessDelivery,
    CredentialEnvelope,
    JobCredentialsResponse,
    JobStatusResponse,
    JobSubmitResponse,
    ResultEnvelope,
)
from market_core import VersionedEnvelope
from market_fulfillment import (
    CredentialFetchFailedError,
    FulfillmentCreateFailedError,
    ProviderConfigInvalidError,
    ProviderOperationState,
    SettlementResource,
    SettlementResult,
)

_READY = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
_EVIDENCE = ResultEnvelope(
    offering_mode="fake",
    result_kind=DELIVERY_EVIDENCE_RESULT_KIND,
    value={
        "endpoints": [{"protocol": "ssh", "host": "203.0.113.7", "port": 2201, "user": "t"}],
        "ready_at": _READY.isoformat(),
    },
)


class _Plan:
    def __init__(self) -> None:
        self.teardown_inputs: dict | None = None
        self.teardown_target: str | None = None

    def prepare_create(self, *, capacity_reservation_id, request, resource, pool_config, allocate):
        if request.payload.get("refuse"):
            raise ProviderConfigInvalidError("refused")
        return PreparedJob(
            offering_mode=request.payload.get("mode", "fake"),
            action="make",
            host_id=resource.host_id,
            executor_target=f"guest-{capacity_reservation_id}",
            parameters={"size": request.payload.get("size", 1), "allocate": allocate},
        )

    def prepare_teardown(
        self, *, capacity_reservation_id, resource, host_id, executor_target,
        create_parameters, pool_config,
    ):
        self.teardown_inputs = dict(create_parameters)
        return PreparedJob(
            offering_mode="fake",
            action="unmake",
            host_id=host_id,
            executor_target=self.teardown_target or executor_target,
            parameters={"undo": dict(create_parameters)},
        )


class _Jobs:
    """The job engine's submission and reads, in memory."""

    def __init__(self) -> None:
        self.jobs: dict[str, JobStatusResponse] = {}
        self.credentials: dict[str, list[CredentialEnvelope]] = {}
        self.submitted: list[dict] = []

    async def submit(self, **fields) -> JobSubmitResponse:
        self.submitted.append(fields)
        job_id = fields["operation_id"]
        self.jobs.setdefault(
            job_id,
            JobStatusResponse(
                job_id=job_id, status="queued", params=dict(fields["params"]),
                host_id=fields["host_id"],
            ),
        )
        return JobSubmitResponse(job_id=job_id, status="queued")

    def finish(self, job_id: str, status: str, *, result=None, error=None, credentials=()):
        self.jobs[job_id] = self.jobs[job_id].model_copy(
            update={"status": status, "result": result, "error": error}
        )
        self.credentials[job_id] = list(credentials)

    def get_job(self, job_id: str) -> JobStatusResponse:
        if job_id not in self.jobs:
            raise LookupError(job_id)
        return self.jobs[job_id]

    def get_credentials(self, job_id: str) -> JobCredentialsResponse:
        return JobCredentialsResponse(job_id=job_id, credentials=self.credentials.get(job_id, []))


class _Hosts:
    def __init__(self) -> None:
        self.enabled = True

    def get_host(self, host_id):
        return SimpleNamespace(host_id=host_id, enabled=self.enabled)


def _resource(host_id: str = "h1", mode: str = "fake") -> SettlementResource:
    return SettlementResource(
        offering_mode=mode, settlement_resource_id="s-1", pool_id="p", resource_kind="k",
        provider="fake.jobs", host_id=host_id,
    )


def _provider():
    plan, jobs, hosts = _Plan(), _Jobs(), _Hosts()
    submission = JobSubmissionService(engine=jobs, hosts=hosts, job_queue_provider=lambda: None)
    return JobFulfillmentProvider(plan=plan, submission=submission, jobs=jobs), plan, jobs, hosts


def _request(**payload) -> VersionedEnvelope:
    return VersionedEnvelope(kind="fake.request", schema_version=1, payload=payload)


async def _created(provider, jobs, reservation: str = "r-1"):
    prepared = provider.prepare_create(
        capacity_reservation_id=reservation, request=_request(size=4),
        resource=_resource(), pool_config={},
    )
    result = await provider.dispatch_create(prepared)
    return result.provider_metadata


def _settled(metadata: dict, host_id: str = "h1") -> SettlementResult:
    return SettlementResult(
        capacity_reservation_id="r-1", fulfillment_id="f-1", resource=_resource(host_id),
        provisioned_resources=(), provider_metadata=metadata,
    )


@pytest.mark.asyncio
async def test_a_create_is_submitted_under_the_reservation_and_operation():
    provider, _, jobs, _ = _provider()

    metadata = await _created(provider, jobs)

    submitted = jobs.submitted[0]
    contract = submitted["contract"]
    assert (contract.action_kind, contract.idempotency_key) == ("create", "r-1:create")
    assert submitted["operation_id"] == contract_operation_id(contract)
    assert (submitted["action"], submitted["host_id"]) == ("make", "h1")
    assert submitted["params"] == {"size": 4, "allocate": True}
    assert metadata == {
        "create_job_id": contract_operation_id(contract),
        "teardown_job_id": None,
        "current_job_id": contract_operation_id(contract),
        "operation": "create",
        "host_id": "h1",
        "executor_target": "guest-r-1",
    }
    assert provider.resolve_provisioned_resources(metadata) == ("guest-r-1",)
    assert provider.resolve_executor_job_id(metadata) == contract_operation_id(contract)


@pytest.mark.asyncio
async def test_a_redispatched_create_names_the_job_already_submitted():
    provider, _, jobs, _ = _provider()

    first = await _created(provider, jobs)
    again = await _created(provider, jobs)

    assert first == again


def test_preparation_refuses_a_job_for_another_offering_mode():
    provider, *_ = _provider()

    with pytest.raises(ProviderConfigInvalidError, match="offering mode"):
        provider.prepare_create(
            capacity_reservation_id="r-1", request=_request(mode="other"),
            resource=_resource(), pool_config={},
        )


@pytest.mark.asyncio
async def test_a_disabled_host_refuses_a_create_but_not_a_teardown():
    provider, _, jobs, hosts = _provider()
    metadata = await _created(provider, jobs)
    jobs.finish(metadata["create_job_id"], "succeeded", result=_EVIDENCE)
    hosts.enabled = False

    with pytest.raises(FulfillmentCreateFailedError, match="disabled"):
        await provider.dispatch_create(
            provider.prepare_create(
                capacity_reservation_id="r-2", request=_request(),
                resource=_resource(), pool_config={},
            )
        )
    teardown = await provider.dispatch_teardown(
        provider.prepare_teardown(_settled(metadata), {})
    )

    assert teardown.provider_metadata["operation"] == "teardown"


@pytest.mark.asyncio
async def test_a_teardown_is_prepared_from_the_parameters_its_create_ran_with():
    provider, plan, jobs, _ = _provider()
    metadata = await _created(provider, jobs)

    prepared = provider.prepare_teardown(_settled(metadata), {})
    result = await provider.dispatch_teardown(prepared)

    assert plan.teardown_inputs == {"size": 4, "allocate": True}
    submitted = jobs.submitted[-1]
    assert submitted["contract"].idempotency_key == "r-1:teardown"
    assert (submitted["action"], submitted["params"]) == (
        "unmake", {"undo": {"size": 4, "allocate": True}}
    )
    assert result.provider_metadata["create_job_id"] == metadata["create_job_id"]
    assert result.provider_metadata["teardown_job_id"] == submitted["operation_id"]
    assert result.provider_metadata["executor_target"] == "guest-r-1"


@pytest.mark.asyncio
async def test_a_teardown_whose_create_job_is_missing_is_a_configuration_error():
    provider, _, jobs, _ = _provider()
    metadata = await _created(provider, jobs)
    jobs.jobs.clear()

    with pytest.raises(ProviderConfigInvalidError, match="nothing to prepare its teardown from"):
        provider.prepare_teardown(_settled(metadata), {})


@pytest.mark.asyncio
async def test_a_teardown_must_address_what_its_create_recorded():
    provider, plan, jobs, _ = _provider()
    metadata = await _created(provider, jobs)

    with pytest.raises(ProviderConfigInvalidError, match="another host"):
        provider.prepare_teardown(_settled(metadata, host_id="h2"), {})
    plan.teardown_target = "someone-else"
    with pytest.raises(ProviderConfigInvalidError, match="host and target its create recorded"):
        provider.prepare_teardown(_settled(metadata), {})


@pytest.mark.parametrize(
    ("status", "state"),
    [
        (JobStatus.queued, ProviderOperationState.pending),
        (JobStatus.running, ProviderOperationState.pending),
        (JobStatus.succeeded, ProviderOperationState.succeeded),
        (JobStatus.failed, ProviderOperationState.failed),
        (JobStatus.cancelled, ProviderOperationState.failed),
    ],
)
@pytest.mark.asyncio
async def test_status_follows_the_job(status, state):
    provider, _, jobs, _ = _provider()
    metadata = await _created(provider, jobs)
    jobs.finish(metadata["create_job_id"], status.value, result=_EVIDENCE, error="e")

    reported = await provider.get_status("r-1", _resource(), metadata)

    assert reported.state is state


@pytest.mark.parametrize(
    "result",
    [
        None,
        ResultEnvelope(offering_mode="fake", result_kind="fake_fact", value={"host": "x"}),
        ResultEnvelope(
            offering_mode="fake",
            result_kind=DELIVERY_EVIDENCE_RESULT_KIND,
            value={"endpoints": [], "ready_at": _READY.isoformat()},
        ),
    ],
    ids=["no-result", "another-kind", "no-endpoint"],
)
@pytest.mark.asyncio
async def test_a_create_that_succeeded_without_usable_evidence_has_failed(result):
    provider, _, jobs, _ = _provider()
    metadata = await _created(provider, jobs)
    jobs.finish(metadata["create_job_id"], "succeeded", result=result)

    reported = await provider.get_status("r-1", _resource(), metadata)

    assert reported.state is ProviderOperationState.failed
    assert "without usable delivery evidence" in reported.detail


@pytest.mark.asyncio
async def test_a_teardown_succeeds_without_evidence():
    provider, _, jobs, _ = _provider()
    metadata = await _created(provider, jobs)
    teardown = (
        await provider.dispatch_teardown(provider.prepare_teardown(_settled(metadata), {}))
    ).provider_metadata
    jobs.finish(teardown["teardown_job_id"], "succeeded")

    reported = await provider.get_status("r-1", _resource(), teardown)

    assert reported.state is ProviderOperationState.succeeded


@pytest.mark.asyncio
async def test_an_unknown_job_or_unreadable_metadata_is_unknown():
    provider, _, jobs, _ = _provider()
    metadata = await _created(provider, jobs)
    jobs.jobs.clear()

    assert (await provider.get_status("r-1", _resource(), metadata)).state is (
        ProviderOperationState.unknown
    )
    assert (await provider.get_status("r-1", _resource(), {"x": 1})).state is (
        ProviderOperationState.unknown
    )


@pytest.mark.parametrize(
    "envelope",
    [
        VersionedEnvelope(kind="vm.ansible.create.v1", schema_version=2, payload={}),
        VersionedEnvelope(kind=JOB_OPERATION_KIND, schema_version=1, payload={"operation": "x"}),
    ],
    ids=["another-kind", "malformed"],
)
@pytest.mark.asyncio
async def test_an_undecodable_operation_is_refused(envelope):
    provider, _, jobs, _ = _provider()

    with pytest.raises(ProviderConfigInvalidError):
        await provider.dispatch_create(envelope)
    assert jobs.submitted == []


@pytest.mark.asyncio
async def test_a_create_cannot_be_dispatched_as_a_teardown():
    provider, _, jobs, _ = _provider()
    prepared = provider.prepare_create(
        capacity_reservation_id="r-1", request=_request(), resource=_resource(), pool_config={},
    )

    with pytest.raises(ProviderConfigInvalidError, match="not a teardown"):
        await provider.dispatch_teardown(prepared)


@pytest.mark.asyncio
async def test_the_delivery_carries_the_evidence_and_only_allowlisted_credential_fields():
    provider, _, jobs, _ = _provider()
    metadata = await _created(provider, jobs)
    jobs.finish(
        metadata["create_job_id"],
        "succeeded",
        result=_EVIDENCE,
        credentials=(
            CredentialEnvelope(
                offering_mode="fake",
                credential_kind="tenant",
                value={
                    "password": "p",
                    "key_type": "ed25519",
                    "ssh_key_path_host": "/var/keys/guest-r-1",
                    "anything_new": "x",
                },
            ),
            CredentialEnvelope(offering_mode="fake", credential_kind="root", value={}),
        ),
    )

    envelope = await provider.fetch_credentials(metadata, ())

    assert envelope.kind == ACCESS_DELIVERY_KIND
    delivery = AccessDelivery.model_validate(envelope.payload)
    assert [credential.model_dump() for credential in delivery.credentials] == [
        {"role": "tenant", "password": "p", "key_type": "ed25519"},
        {"role": "root", "password": None, "key_type": None},
    ]
    assert delivery.endpoints[0].port == 2201
    assert delivery.ready_at == _READY
    assert "ssh_key_path_host" not in str(envelope.payload)


@pytest.mark.asyncio
async def test_a_delivery_without_evidence_is_a_credential_fetch_failure():
    provider, _, jobs, _ = _provider()
    metadata = await _created(provider, jobs)
    jobs.finish(metadata["create_job_id"], "succeeded")

    with pytest.raises(CredentialFetchFailedError):
        await provider.fetch_credentials(metadata, ())
