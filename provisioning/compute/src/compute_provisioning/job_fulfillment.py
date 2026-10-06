"""Job-backed fulfillment: one provider for every domain that delivers through jobs.

``JobFulfillmentProvider`` implements the fulfillment kit's provider protocol
over the family's job authority. It submits, tracks, and delivers; a domain
contributes only a ``JobFulfillmentPlan``, which turns a settled resource into a
``PreparedJob`` and a create job's parameters into its teardown, and the codec
its executor runs with, which reports a successful create as a
``CreateJobResult``.

What the provider owns, the same for every domain:

- **One prepared operation and one metadata shape.** A prepared job names the
  host it runs on (``host_id``) and what it acts on (``executor_target``). The
  fulfillment's metadata records both, and teardown addresses exactly them.
- **Teardown undoes what create ran.** The domain prepares a teardown from the
  parameters its create job was submitted with, read back from the job
  authority, so nothing about the create need be copied into the metadata. A
  fulfillment whose create job cannot be found has nothing to undo by, and its
  teardown preparation fails as a configuration error.
- **Submission.** Every job goes through ``JobSubmissionService`` under a
  contract whose identity is the reservation and the operation, so a retried
  dispatch finds the job it already submitted. A create needs its host enabled;
  a teardown does not.
- **Status.** One table over ``JobStatus``. A create job that succeeded is a
  successful create only if its result is a ``CreateJobResult`` carrying valid
  ``DeliveryEvidence``; otherwise the create has failed. The result's detail is
  the domain's operator data and is never read here. An executor that reported success with output nobody
  can read may still have left something running, so the fulfillment is failed
  and holds its capacity as any failed create does, rather than becoming active
  with a delivery that cannot be produced.
- **One provisioned resource,** the one ``executor_target`` names.
- **The delivery,** assembled from the create job's evidence and its
  credentials, each reduced to ``DeliveredCredential``'s allowlisted fields.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from compute_provisioning_contracts import (
    ACCESS_DELIVERY_KIND,
    ACCESS_DELIVERY_SCHEMA_VERSION,
    AccessDelivery,
    CREATE_JOB_RESULT_KIND,
    CreateJobResult,
    DeliveredCredential,
    DeliveryEvidence,
    JobCredentialsResponse,
    JobStatusResponse,
)
from market_core import VersionedEnvelope
from market_fulfillment import (
    CredentialFetchFailedError,
    FulfillmentCreateFailedError,
    FulfillmentProvider,
    FulfillmentResult,
    FulfillmentStatusFailedError,
    FulfillmentTeardownFailedError,
    ProviderConfigInvalidError,
    ProviderOperationState,
    ProviderStatus,
    ProvisionedResourceDescriptor,
    SettlementResource,
    SettlementResult,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from compute_provisioning.jobs.action_request import JobActionRequest
from compute_provisioning.jobs.db import JobStatus
from compute_provisioning.jobs.submission import JobSubmissionService

#: The kind and schema version of a prepared job-backed operation.
JOB_OPERATION_KIND = "compute.job-fulfillment.operation"
JOB_OPERATION_SCHEMA_VERSION = 1

Operation = Literal["create", "teardown"]

_STATUS: Mapping[str, ProviderOperationState] = {
    JobStatus.queued.value: ProviderOperationState.pending,
    JobStatus.running.value: ProviderOperationState.pending,
    JobStatus.succeeded.value: ProviderOperationState.succeeded,
    JobStatus.failed.value: ProviderOperationState.failed,
    JobStatus.cancelled.value: ProviderOperationState.failed,
}


@dataclass(frozen=True)
class PreparedJob:
    """One job a domain's plan prepared: where it runs, what it acts on, and how."""

    offering_mode: str
    #: The executor action, which the executor table routes on.
    action: str
    #: The host the job runs against.
    host_id: str
    #: What the job acts on: the provisioned resource, and teardown's target.
    executor_target: str
    #: The job's opaque parameters, which the domain's codec reads.
    parameters: Mapping[str, Any] = field(default_factory=dict)


class JobFulfillmentPlan(Protocol):
    """What a domain contributes to job-backed fulfillment.

    Each method validates as it prepares and raises
    ``ProviderConfigInvalidError`` for anything it refuses.
    """

    def prepare_create(
        self,
        *,
        capacity_reservation_id: str,
        request: VersionedEnvelope[Any],
        resource: SettlementResource,
        pool_config: dict[str, Any],
        allocate: bool,
    ) -> PreparedJob:
        """The create job for a settled resource.

        ``allocate=False`` asks for every rejection with nothing acquired, as the
        fulfillment kit's ``prepare_create`` defines it.
        """
        ...

    def prepare_teardown(
        self,
        *,
        capacity_reservation_id: str,
        resource: SettlementResource,
        host_id: str,
        executor_target: str,
        create_parameters: Mapping[str, Any],
        pool_config: dict[str, Any],
    ) -> PreparedJob:
        """The job that undoes a create, against the host and target it recorded."""
        ...


class JobReader(Protocol):
    """The job authority's reads this provider uses."""

    def get_job(self, job_id: str) -> JobStatusResponse: ...

    def get_credentials(self, job_id: str) -> JobCredentialsResponse: ...


class JobFulfillmentMetadata(BaseModel):
    """What a job-backed fulfillment records about its jobs."""

    model_config = ConfigDict(extra="forbid")

    create_job_id: str = Field(min_length=1)
    teardown_job_id: str | None = None
    current_job_id: str = Field(min_length=1)
    operation: Operation
    host_id: str = Field(min_length=1)
    executor_target: str = Field(min_length=1)


class PreparedJobOperation(BaseModel):
    """A prepared job, as the fulfillment kit freezes it before dispatch."""

    model_config = ConfigDict(extra="forbid")

    capacity_reservation_id: str = Field(min_length=1)
    operation: Operation
    offering_mode: str = Field(min_length=1)
    action: str = Field(min_length=1)
    host_id: str = Field(min_length=1)
    executor_target: str = Field(min_length=1)
    parameters: dict[str, Any]
    # A teardown's create job, kept on the teardown's metadata.
    create_job_id: str | None = Field(default=None, min_length=1)


def job_contract(
    capacity_reservation_id: str, operation: Operation, offering_mode: str
) -> JobActionRequest:
    """The contract a fulfillment's job is submitted under.

    Its identity is the reservation and the operation, the same for every
    domain, so one fulfillment's create, or its teardown, is one job.
    """
    return JobActionRequest(
        capacity_reservation_id=capacity_reservation_id,
        offering_mode=offering_mode,
        action_kind=operation,
        idempotency_key=f"{capacity_reservation_id}:{operation}",
    )


def delivery_evidence(job: JobStatusResponse) -> DeliveryEvidence:
    """A create job's delivery evidence; ``ValueError`` if it reported none usable."""
    result = job.result
    if result is None:
        raise ValueError(f"job {job.job_id} reported no result")
    if result.result_kind != CREATE_JOB_RESULT_KIND:
        raise ValueError(
            f"job {job.job_id} reported a {result.result_kind!r} result, "
            f"not {CREATE_JOB_RESULT_KIND!r}"
        )
    try:
        evidence = CreateJobResult.model_validate(result.value).evidence
    except ValidationError as exc:
        raise ValueError(f"job {job.job_id} reported an invalid create result: {exc}") from exc
    if evidence is None:
        raise ValueError(f"job {job.job_id} reported no delivery evidence")
    return evidence


_DELIVERED_FIELDS = tuple(name for name in DeliveredCredential.model_fields if name != "role")


def delivered_credential(role: str, value: Mapping[str, Any]) -> DeliveredCredential:
    """A stored credential reduced to the fields a delivery may carry."""
    return DeliveredCredential(
        role=role,
        **{name: value[name] for name in _DELIVERED_FIELDS if value.get(name) is not None},
    )


def _metadata(provider_metadata: Mapping[str, Any]) -> JobFulfillmentMetadata:
    try:
        return JobFulfillmentMetadata.model_validate(dict(provider_metadata or {}))
    except ValidationError as exc:
        raise ProviderConfigInvalidError(f"invalid job fulfillment metadata: {exc}") from exc


def _operation(prepared: VersionedEnvelope[Any], expected: Operation) -> PreparedJobOperation:
    if prepared.kind != JOB_OPERATION_KIND or prepared.schema_version != JOB_OPERATION_SCHEMA_VERSION:
        raise ProviderConfigInvalidError(
            f"unsupported {expected} operation {prepared.kind!r} v{prepared.schema_version}"
        )
    try:
        operation = PreparedJobOperation.model_validate(prepared.payload)
    except ValidationError as exc:
        raise ProviderConfigInvalidError(f"invalid {expected} operation: {exc}") from exc
    if operation.operation != expected:
        raise ProviderConfigInvalidError(
            f"prepared operation is a {operation.operation}, not a {expected}"
        )
    return operation


def _envelope(operation: PreparedJobOperation) -> VersionedEnvelope[Any]:
    return VersionedEnvelope(
        kind=JOB_OPERATION_KIND,
        schema_version=JOB_OPERATION_SCHEMA_VERSION,
        payload=operation.model_dump(mode="json"),
    )


def teardown_operation(
    capacity_reservation_id: str, prepared: PreparedJob, *, create_job_id: str
) -> VersionedEnvelope[Any]:
    """A prepared teardown, as the fulfillment kit freezes it before dispatch.

    For a caller that already holds the teardown job, such as a backfill
    recording one for a fulfillment created before this provider existed. Its
    dispatch reads no job: only preparing a teardown reads the create job.
    """
    return _envelope(
        PreparedJobOperation(
            capacity_reservation_id=capacity_reservation_id,
            operation="teardown",
            offering_mode=prepared.offering_mode,
            action=prepared.action,
            host_id=prepared.host_id,
            executor_target=prepared.executor_target,
            parameters=dict(prepared.parameters),
            create_job_id=create_job_id,
        )
    )


def _checked(prepared: PreparedJob, resource: SettlementResource) -> PreparedJob:
    if prepared.offering_mode != resource.offering_mode:
        raise ProviderConfigInvalidError(
            f"prepared job is for offering mode {prepared.offering_mode!r}, "
            f"but the selected resource is {resource.offering_mode!r}"
        )
    if not prepared.host_id.strip() or not prepared.executor_target.strip():
        raise ProviderConfigInvalidError("a prepared job names its host and its target")
    return prepared


class JobFulfillmentProvider(FulfillmentProvider):
    """The compute family's fulfillment provider over the job authority."""

    # Every job runs against a registered host, so a declaration naming none
    # has nowhere to run.
    needs_host = True

    def __init__(
        self,
        *,
        plan: JobFulfillmentPlan,
        submission: JobSubmissionService,
        jobs: JobReader,
    ) -> None:
        self._plan = plan
        self._submission = submission
        self._jobs = jobs

    # Create.

    def prepare_create(
        self,
        *,
        capacity_reservation_id: str,
        request: VersionedEnvelope[Any],
        resource: SettlementResource,
        pool_config: dict[str, Any],
        allocate: bool = True,
    ) -> VersionedEnvelope[Any]:
        prepared = _checked(
            self._plan.prepare_create(
                capacity_reservation_id=capacity_reservation_id,
                request=request,
                resource=resource,
                pool_config=pool_config,
                allocate=allocate,
            ),
            resource,
        )
        return _envelope(
            PreparedJobOperation(
                capacity_reservation_id=capacity_reservation_id,
                operation="create",
                offering_mode=prepared.offering_mode,
                action=prepared.action,
                host_id=prepared.host_id,
                executor_target=prepared.executor_target,
                parameters=dict(prepared.parameters),
            )
        )

    async def dispatch_create(self, prepared: VersionedEnvelope[Any]) -> FulfillmentResult:
        operation = _operation(prepared, "create")
        try:
            response = await self._submit(operation, require_enabled_host=True)
        except Exception as exc:
            raise FulfillmentCreateFailedError(str(exc)) from exc
        return FulfillmentResult(
            JobFulfillmentMetadata(
                create_job_id=response.job_id,
                current_job_id=response.job_id,
                operation="create",
                host_id=operation.host_id,
                executor_target=operation.executor_target,
            ).model_dump(mode="json")
        )

    def resolve_executor_job_id(self, provider_metadata: dict[str, Any]) -> str | None:
        """The create job this fulfillment dispatched.

        Read defensively rather than through ``JobFulfillmentMetadata``: a
        partially written row from a failed dispatch yields no handle rather
        than a validation error inside the transaction surfacing it.
        """
        job_id = (provider_metadata or {}).get("create_job_id")
        return str(job_id) if job_id else None

    def resolve_provisioned_resources(self, provider_metadata: dict[str, Any]) -> tuple[str, ...]:
        return (_metadata(provider_metadata).executor_target,)

    # Teardown.

    def prepare_teardown(
        self,
        settlement_result: SettlementResult,
        pool_config: dict[str, Any],
    ) -> VersionedEnvelope[Any]:
        metadata = _metadata(settlement_result.provider_metadata)
        resource = settlement_result.resource
        if resource.host_id != metadata.host_id:
            raise ProviderConfigInvalidError(
                "fulfillment metadata names another host than the selected resource"
            )
        try:
            create_job = self._jobs.get_job(metadata.create_job_id)
        except LookupError as exc:
            raise ProviderConfigInvalidError(
                f"create job {metadata.create_job_id} was not found, "
                "so there is nothing to prepare its teardown from"
            ) from exc
        prepared = _checked(
            self._plan.prepare_teardown(
                capacity_reservation_id=settlement_result.capacity_reservation_id,
                resource=resource,
                host_id=metadata.host_id,
                executor_target=metadata.executor_target,
                create_parameters=dict(create_job.params),
                pool_config=pool_config,
            ),
            resource,
        )
        if (prepared.host_id, prepared.executor_target) != (
            metadata.host_id,
            metadata.executor_target,
        ):
            raise ProviderConfigInvalidError(
                "a teardown must address the host and target its create recorded"
            )
        return teardown_operation(
            settlement_result.capacity_reservation_id,
            prepared,
            create_job_id=metadata.create_job_id,
        )

    async def dispatch_teardown(self, prepared: VersionedEnvelope[Any]) -> FulfillmentResult:
        operation = _operation(prepared, "teardown")
        if operation.create_job_id is None:
            raise ProviderConfigInvalidError("a prepared teardown names the create it undoes")
        try:
            response = await self._submit(operation, require_enabled_host=False)
        except Exception as exc:
            raise FulfillmentTeardownFailedError(str(exc)) from exc
        return FulfillmentResult(
            JobFulfillmentMetadata(
                create_job_id=operation.create_job_id,
                teardown_job_id=response.job_id,
                current_job_id=response.job_id,
                operation="teardown",
                host_id=operation.host_id,
                executor_target=operation.executor_target,
            ).model_dump(mode="json")
        )

    # Status and delivery.

    async def get_status(
        self,
        capacity_reservation_id: str,
        resource: SettlementResource,
        provider_metadata: dict[str, Any],
    ) -> ProviderStatus:
        del capacity_reservation_id, resource
        try:
            metadata = _metadata(provider_metadata)
        except ProviderConfigInvalidError as exc:
            return ProviderStatus(ProviderOperationState.unknown, str(exc))
        try:
            job = self._jobs.get_job(metadata.current_job_id)
        except LookupError:
            return ProviderStatus(
                ProviderOperationState.unknown, f"job {metadata.current_job_id} not found"
            )
        except Exception as exc:
            raise FulfillmentStatusFailedError(str(exc)) from exc
        state = _STATUS.get(job.status, ProviderOperationState.unknown)
        if state is ProviderOperationState.succeeded and metadata.operation == "create":
            try:
                delivery_evidence(job)
            except ValueError as exc:
                return ProviderStatus(
                    ProviderOperationState.failed,
                    f"the create job succeeded without usable delivery evidence: {exc}",
                )
        return ProviderStatus(state, job.error)

    async def fetch_credentials(
        self,
        provider_metadata: dict[str, Any],
        provisioned_resources: tuple[ProvisionedResourceDescriptor, ...],
    ) -> VersionedEnvelope[Any]:
        """The delivery of an active fulfillment, read from its create job.

        Declared async by the provider protocol; the job authority here is this
        process's own database, so nothing is awaited.
        """
        del provisioned_resources
        try:
            metadata = _metadata(provider_metadata)
            job = self._jobs.get_job(metadata.create_job_id)
            evidence = delivery_evidence(job)
            stored = self._jobs.get_credentials(metadata.create_job_id).credentials
            delivery = AccessDelivery(
                endpoints=evidence.endpoints,
                credentials=tuple(
                    delivered_credential(credential.credential_kind, credential.value)
                    for credential in stored
                ),
                ready_at=evidence.ready_at,
            )
        except Exception as exc:
            raise CredentialFetchFailedError(str(exc)) from exc
        return VersionedEnvelope(
            kind=ACCESS_DELIVERY_KIND,
            schema_version=ACCESS_DELIVERY_SCHEMA_VERSION,
            payload=delivery.model_dump(mode="json"),
        )

    async def _submit(self, operation: PreparedJobOperation, *, require_enabled_host: bool):
        return await self._submission.submit(
            offering_mode=operation.offering_mode,
            action=operation.action,
            host_id=operation.host_id,
            params=operation.parameters,
            contract=job_contract(
                operation.capacity_reservation_id,
                operation.operation,
                operation.offering_mode,
            ),
            require_enabled_host=require_enabled_host,
        )


__all__ = [
    "JOB_OPERATION_KIND",
    "JOB_OPERATION_SCHEMA_VERSION",
    "JobFulfillmentMetadata",
    "JobFulfillmentPlan",
    "JobFulfillmentProvider",
    "JobReader",
    "PreparedJob",
    "PreparedJobOperation",
    "delivered_credential",
    "delivery_evidence",
    "job_contract",
    "teardown_operation",
]
