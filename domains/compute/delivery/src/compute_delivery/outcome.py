"""Where one ``drive`` left a deal.

Six outcomes suffice: a first drive is the start of the normal path, and a
missing deal and unreadable progress ask the same of a caller, which the
repair reason distinguishes. A ``repair_required`` or ``ended`` outcome names
the deal's recorded reservation and fulfillment and the authority evidence it
rests on, so a repair or an end report is explained without re-reading the
deal. See openspec/specs/compute-delivery/spec.md, "Delivery is driven one
deal at a time and reports where it stands".
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal


class OutcomeKind(str, Enum):
    WAITING = "waiting"
    PENDING = "pending"
    REPAIR_REQUIRED = "repair_required"
    AVAILABLE = "available"
    CONVERGED = "converged"
    ENDED = "ended"


class RepairReason(str, Enum):
    """The closed set of reasons a deal needs repair before it can go on."""

    NO_ACCEPTED_DEAL = "no_accepted_deal"
    TIMING_INVALID = "timing_invalid"
    PROGRESS_UNREADABLE = "progress_unreadable"
    DOMAIN_RESULT_INVALID = "domain_result_invalid"
    ACTIVATION_UNEXPLAINED = "activation_unexplained"
    SITE_UNANSWERED = "site_unanswered"


HookDisposition = Literal["fulfilled", "deferred", "failed"]


class AccessRefused(Exception):
    """A buyer's access read the path refused; nothing fetched is returned.

    ``reason`` is ``not_available``, ``not_started`` or ``ended``.
    """

    def __init__(self, reason: Literal["not_available", "not_started", "ended"], detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class DeliveryOutcome:
    kind: OutcomeKind
    capacity_reservation_id: str | None = None
    fulfillment_id: str | None = None
    #: The start a ``waiting`` deal wakes at.
    wake_at: int | None = None
    reason: RepairReason | None = None
    #: The authority evidence a ``repair_required`` or ``ended`` outcome rests
    #: on: the end record's source, the retained site answer, or the record
    #: the path could not read.
    evidence_ref: str | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        if (self.kind is OutcomeKind.WAITING) != (self.wake_at is not None):
            raise ValueError("a waiting outcome, and only one, names its wake time")
        if (self.kind is OutcomeKind.REPAIR_REQUIRED) != (self.reason is not None):
            raise ValueError("a repair outcome, and only one, names its reason")
        if self.kind in (OutcomeKind.REPAIR_REQUIRED, OutcomeKind.ENDED) and not self.evidence_ref:
            raise ValueError(f"a {self.kind.value} outcome names the evidence it rests on")

    @property
    def hook_disposition(self) -> HookDisposition:
        """What a fulfillment hook reports for this outcome.

        ``ended`` is returned only once the end hand-off is durable, so a hook
        may report it failed.
        """
        if self.kind in (OutcomeKind.AVAILABLE, OutcomeKind.CONVERGED):
            return "fulfilled"
        if self.kind is OutcomeKind.ENDED:
            return "failed"
        return "deferred"
