"""The site's event kinds, and the recorder its ledger records them through.

The ledger records ``site.lease_ended`` with every immutable ``lease_ended``
record and ``site.capacity_released`` with every release that frees a
reservation's capacity, each in the transaction of the transition it reports.
A caller's prepared event — a draft of a kind the site does not know — is
recorded in the release-failure transition the same way.

Every event names the lease it concerns as its subject and among its related
references, so one read by reference finds every event of a lease, whoever
recorded it.
"""

from __future__ import annotations

from typing import Any, Protocol

from eventing import EventDraft, Kind, Reference, Severity
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

LEASE_REFERENCE_TYPE = "lease"


class EventRecorder(Protocol):
    """Records a draft in the caller's session, never committing."""

    def record(self, session: Session, draft: EventDraft) -> object: ...


class LeaseEndedDetails(BaseModel):
    """The immutable ``lease_ended`` record's payload, as the site signs it."""

    model_config = ConfigDict(extra="forbid")

    version: int
    kind: str
    event_id: str
    capacity_reservation_id: str
    site_id: str
    effective_at: Any
    source_state: str
    cause: str | None
    reason: str | None
    caller: Any
    claimed_deadline: Any
    deadline_phase: str | None


class CapacityReleasedDetails(BaseModel):
    """A release that freed a reservation's capacity."""

    model_config = ConfigDict(extra="forbid")

    capacity_reservation_id: str
    site_id: str
    state: str
    released_at: str
    failure_reason: str | None = None


def _lease_ended_summary(draft: EventDraft, details: LeaseEndedDetails) -> str:
    return (
        f"Lease {details.capacity_reservation_id} ended ({details.cause}) "
        f"from {details.source_state} at site {details.site_id}."
    )


def _capacity_released_summary(draft: EventDraft, details: CapacityReleasedDetails) -> str:
    how = " by force" if draft.attributes.get("forced") else ""
    after = " after a release failure" if draft.attributes.get("after_release_failure") else ""
    return (
        f"Lease {details.capacity_reservation_id}'s capacity was released{how}{after} "
        f"at site {details.site_id}."
    )


#: One per immutable ``lease_ended`` record, keyed on the reservation and the
#: transition that ended it, so a repeated transition records neither again.
#: A composition attaches the record-time hook it needs with
#: ``dataclasses.replace``.
SITE_LEASE_ENDED: Kind[LeaseEndedDetails] = Kind(
    name="site.lease_ended",
    version=1,
    severity=Severity.INFO,
    details=LeaseEndedDetails,
    summary=_lease_ended_summary,
    attributes={"cause": str, "source_state": str, "transition_key": str},
    dedup_key=("subject", "attributes.transition_key"),
)

#: One per reservation whose capacity a release freed. ``lease_lifecycle`` says
#: the lease lifecycle made the release through the site authority port — the
#: releases the owning storefront is called back for — rather than a caller of
#: the site's own release route.
SITE_CAPACITY_RELEASED: Kind[CapacityReleasedDetails] = Kind(
    name="site.capacity_released",
    version=1,
    severity=Severity.INFO,
    details=CapacityReleasedDetails,
    summary=_capacity_released_summary,
    attributes={"forced": bool, "after_release_failure": bool, "lease_lifecycle": bool},
    dedup_key=("subject",),
)

SITE_KINDS: tuple[Kind[Any], ...] = (SITE_LEASE_ENDED, SITE_CAPACITY_RELEASED)


def lease_reference(capacity_reservation_id: str) -> Reference:
    """The reference naming a lease, by its reservation's identifier."""
    return Reference(type=LEASE_REFERENCE_TYPE, id=capacity_reservation_id)


def lease_ended_draft(payload: dict[str, Any], *, transition_key: str) -> EventDraft:
    """``site.lease_ended`` carrying a ``lease_ended`` record's payload."""
    lease = lease_reference(str(payload["capacity_reservation_id"]))
    return SITE_LEASE_ENDED.draft(
        subject=lease,
        details=payload,
        attributes={
            "cause": payload.get("cause"),
            "source_state": payload.get("source_state"),
            "transition_key": transition_key,
        },
        related=(lease,),
        correlation_id=lease.id,
    )


def capacity_released_draft(
    details: CapacityReleasedDetails,
    *,
    forced: bool,
    after_release_failure: bool,
    lease_lifecycle: bool,
) -> EventDraft:
    """``site.capacity_released`` for a release that freed a reservation's capacity."""
    lease = lease_reference(details.capacity_reservation_id)
    return SITE_CAPACITY_RELEASED.draft(
        subject=lease,
        details=details,
        attributes={
            "forced": forced,
            "after_release_failure": after_release_failure,
            "lease_lifecycle": lease_lifecycle,
        },
        related=(lease,),
        correlation_id=lease.id,
    )


__all__ = [
    "LEASE_REFERENCE_TYPE",
    "SITE_CAPACITY_RELEASED",
    "SITE_KINDS",
    "SITE_LEASE_ENDED",
    "CapacityReleasedDetails",
    "EventRecorder",
    "LeaseEndedDetails",
    "capacity_released_draft",
    "lease_ended_draft",
    "lease_reference",
]
