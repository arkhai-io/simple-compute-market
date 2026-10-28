"""Versioned wire models for compute provisioning commands and lifecycle state."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from market_core import VersionedEnvelope

# Each major is accepted alone, and a model stating another is refused by its
# version, naming the major supported, never coerced: the majors differ in what
# their models carry (a schedule response's ``host_id``, the lease states, the
# offering mode's name), so a party reading another major's model as this one
# would misread it rather than see that the two disagree.
# See openspec/specs/compute-provisioning-contract/spec.md.
COMPUTE_PROVISIONING_CONTRACT_VERSION = "3.0"
SUPPORTED_COMPUTE_PROVISIONING_MAJOR_VERSIONS = frozenset({3})


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


class LeaseState(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    RELEASING = "releasing"
    RELEASED = "released"
    RELEASE_FAILED = "release_failed"
    UNMANAGED = "unmanaged"
    FORCE_RELEASED = "force_released"


_RESERVATION_TO_LEASE_STATE: dict[str, LeaseState] = {
    "reserved": LeaseState.PENDING,
    "leased": LeaseState.ACTIVE,
    "releasing": LeaseState.RELEASING,
    "released": LeaseState.RELEASED,
    "release_failed": LeaseState.RELEASE_FAILED,
    "unmanaged": LeaseState.UNMANAGED,
    "force_released": LeaseState.FORCE_RELEASED,
}

def lease_state_for_reservation_state(state: str) -> LeaseState:
    """Project an internal reservation state onto the public lease contract."""
    try:
        return _RESERVATION_TO_LEASE_STATE[state]
    except KeyError as exc:
        raise ValueError(f"unsupported reservation state for lease projection: {state!r}") from exc


class CredentialEnvelope(BaseModel):
    offering_mode: str
    credential_kind: str
    value: dict[str, Any]


class ResultEnvelope(BaseModel):
    offering_mode: str
    result_kind: str
    value: dict[str, Any]


class LeaseView(VersionedContractModel):
    """A lease as the site records it: its tail, window, and lifecycle evidence.

    No route writes a lease. Commit records its window, from the commit on;
    provisioning records its executor target when the fulfillment becomes
    active; and the lease lifecycle records release. The create and release
    handles are lifecycle evidence, written only by fulfillment and the lease
    lifecycle.
    """

    capacity_reservation_id: str
    deal_ref: dict[str, Any]
    offering_mode: str
    executor_target: str
    lease_start_utc: datetime | None = None
    lease_end_utc: datetime
    create_job_id: str | None = None
    status: LeaseState
    release_job_id: str | None = None
    failure_reason: str | None = None
    failure_message: str | None = None


class LeaseListResponse(BaseModel):
    leases: list[LeaseView]
    total: int


class LeaseReleaseOversight(VersionedContractModel):
    """Hand a leased reservation to an operator: the lifecycle stops releasing it."""

    reason: str = Field(min_length=1)


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
    offering_mode: str = Field(min_length=1)
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
    """The resource scheduling bound a reservation to.

    ``host_id`` is the host the resource's declaration names, absent when it
    names none, as a resource in a pool whose provider needs no host may; a
    bare-metal resource's ``physical_host_id`` is among its ``attributes``.
    """

    settlement_resource_id: str
    pool_id: str
    resource_kind: str
    provider: str
    host_id: str | None = Field(default=None, exclude_if=lambda host_id: host_id is None)
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

