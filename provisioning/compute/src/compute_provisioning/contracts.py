"""Versioned wire models for compute provisioning commands and lifecycle state."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from market_fulfillment import VersionedEnvelope

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
    PROVISIONING_FAILED = "provisioning_failed"
    FORCE_RELEASED = "force_released"




_RESERVATION_TO_LEASE_STATE: dict[str, LeaseState] = {
    "reserved": LeaseState.PENDING,
    "provisioning": LeaseState.PENDING,
    "leased": LeaseState.ACTIVE,
    "releasing": LeaseState.RELEASING,
    "released": LeaseState.RELEASED,
    "release_failed": LeaseState.RELEASE_FAILED,
    "unmanaged": LeaseState.UNMANAGED,
    "provisioning_failed": LeaseState.PROVISIONING_FAILED,
    "force_released": LeaseState.FORCE_RELEASED,
}

def lease_state_for_reservation_state(state: str) -> LeaseState:
    """Project an internal reservation state onto the public lease contract."""
    try:
        return _RESERVATION_TO_LEASE_STATE[state]
    except KeyError as exc:
        raise ValueError(f"unsupported reservation state for lease projection: {state!r}") from exc


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


# ---------------------------------------------------------------------------
# Fulfillment scheduling and acceptance.
#
# These wrap `kit/fulfillment`'s `PhysicalSettlementScheduler.schedule_resource`
# and `FulfillmentOrchestrator`'s validate/begin/status/result surface —
# domain-neutral scheduling and fulfillment behavior owned by the kit, mirrored
# here as this service's versioned wire contract the same way every other
# endpoint family in this file is. `contract_version` (via
# `VersionedContractModel`) is this file's own wire-compatibility axis; it is
# deliberately independent of `market_fulfillment`'s own
# `VersionedEnvelope`/`schema_version` on `fulfillment_request` and the result
# envelope, not collapsed into it.
# ---------------------------------------------------------------------------


class FulfillmentScheduleRequest(VersionedContractModel):
    capacity_reservation_id: str = Field(min_length=1)
    market: str = Field(min_length=1)
    requirements: dict[str, Any] = Field(default_factory=dict)
    resource_id: str | None = None


class FulfillmentScheduleResponse(VersionedContractModel):
    settlement_resource_id: str
    pool_id: str
    resource_kind: str
    provider: str
    attributes: dict[str, Any] = Field(default_factory=dict)


class FulfillmentRequestBody(VersionedContractModel):
    capacity_reservation_id: str = Field(min_length=1)
    market: str = Field(min_length=1)
    fulfillment_request: VersionedEnvelope[Any]


class FulfillmentAcceptanceResponse(VersionedContractModel):
    fulfillment_id: str
    capacity_reservation_id: str
    state: str


class FulfillmentStatusResponse(VersionedContractModel):
    fulfillment_id: str
    capacity_reservation_id: str
    state: str
    failure_reason: str | None = None
    failure_message: str | None = None


class FulfillmentValidationResponse(VersionedContractModel):
    valid: bool
    issues: list[dict[str, Any]]

