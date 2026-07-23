"""Versioned wire models for compute provisioning commands and lifecycle state."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

COMPUTE_PROVISIONING_CONTRACT_VERSION = "1.0"
SUPPORTED_COMPUTE_PROVISIONING_MAJOR_VERSIONS = frozenset({1})


def contract_major(version: str) -> int:
    """Return a validated semantic-contract major version."""
    try:
        major = int(version.split(".", 1)[0])
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid compute provisioning contract version: {version!r}") from exc
    if major not in SUPPORTED_COMPUTE_PROVISIONING_MAJOR_VERSIONS:
        supported = ", ".join(str(value) for value in sorted(SUPPORTED_COMPUTE_PROVISIONING_MAJOR_VERSIONS))
        raise ValueError(
            f"unsupported compute provisioning contract major {major}; supported majors: {supported}"
        )
    return major


class VersionedContractModel(BaseModel):
    contract_version: str = COMPUTE_PROVISIONING_CONTRACT_VERSION

    @model_validator(mode="after")
    def _validate_contract_version(self) -> "VersionedContractModel":
        contract_major(self.contract_version)
        return self


class FulfillmentScheduleRequest(VersionedContractModel):
    capacity_reservation_id: str = Field(min_length=1)
    market: str = Field(min_length=1)
    requirements: dict[str, Any] = Field(default_factory=dict)
    resource_id: str | None = None


class SettlementResourceView(VersionedContractModel):
    capacity_reservation_id: str = Field(min_length=1)
    settlement_resource_id: str = Field(min_length=1)
    pool_id: str = Field(min_length=1)
    resource_kind: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    attributes: dict[str, Any] = Field(default_factory=dict)


class FulfillmentRequestEnvelope(BaseModel):
    kind: str = Field(min_length=1)
    schema_version: int = Field(ge=1)
    payload: dict[str, Any]

    model_config = {"extra": "forbid", "frozen": True}


class FulfillmentBeginRequest(VersionedContractModel):
    capacity_reservation_id: str = Field(min_length=1)
    market: str = Field(min_length=1)
    fulfillment_request: FulfillmentRequestEnvelope

    model_config = {"extra": "forbid"}


class FulfillmentAcceptanceView(VersionedContractModel):
    capacity_reservation_id: str = Field(min_length=1)
    fulfillment_id: str = Field(min_length=1)
    state: str = Field(min_length=1)


class FulfillmentValidationIssueView(BaseModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    field: str | None = None


class FulfillmentDryRunView(VersionedContractModel):
    valid: bool
    issues: list[FulfillmentValidationIssueView] = Field(default_factory=list)


class ExecutorKind(str, Enum):
    VM = "vm"
    BARE_METAL = "bare_metal"


class JobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class LeaseState(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    RELEASING = "releasing"
    RELEASED = "released"
    RELEASE_FAILED = "release_failed"
    UNMANAGED = "unmanaged"


class ExecutorActionEnvelope(VersionedContractModel):
    capacity_reservation_id: str = Field(min_length=1)
    deal_ref: dict[str, Any]
    executor_kind: str = Field(min_length=1)
    action_kind: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    parameters: dict[str, Any]



class JobAccepted(VersionedContractModel):
    job_id: str
    status: JobState = JobState.QUEUED
    capacity_reservation_id: str
    deal_ref: dict[str, Any]
    executor_kind: str
    action_kind: str
    idempotency_key: str


class ProvisioningErrorEnvelope(BaseModel):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class LogsReference(BaseModel):
    kind: Literal["inline", "url", "object"]
    reference: str


class CredentialEnvelope(BaseModel):
    executor_kind: str
    credential_kind: str
    value: dict[str, Any]


class ResultEnvelope(BaseModel):
    executor_kind: str
    result_kind: str
    value: dict[str, Any]


class ProvisioningJob(VersionedContractModel):
    job_id: str
    status: JobState
    capacity_reservation_id: str
    deal_ref: dict[str, Any]
    executor_kind: str
    action_kind: str
    idempotency_key: str
    result: ResultEnvelope | None = None
    credentials: list[CredentialEnvelope] = Field(default_factory=list)
    error: ProvisioningErrorEnvelope | None = None
    logs_reference: LogsReference | None = None
    retry_count: int = 0
    max_retries: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class LeaseRegistration(VersionedContractModel):
    capacity_reservation_id: str
    deal_ref: dict[str, Any]
    executor_kind: str
    executor_target: str
    lease_start_utc: datetime | None = None
    lease_end_utc: datetime
    create_job_id: str | None = None


class LeaseView(LeaseRegistration):
    status: LeaseState
    release_job_id: str | None = None
    failure_reason: str | None = None
    failure_message: str | None = None


class LeaseTermination(VersionedContractModel):
    reason: str | None = None
    max_retries: int | None = Field(default=None, ge=0)


class LeaseRetryRelease(VersionedContractModel):
    reason: str | None = None
    max_retries: int | None = Field(default=None, ge=0)


class LeaseForceRelease(VersionedContractModel):
    reason: str = Field(min_length=1)
    evidence: str | None = None


class LifecycleEvent(VersionedContractModel):
    event_id: str = Field(min_length=1)
    capacity_reservation_id: str = Field(min_length=1)
    deal_ref: dict[str, Any]
    executor_kind: str = Field(min_length=1)
    event_kind: str = Field(min_length=1)
    payload: dict[str, Any]
    occurred_at: datetime

