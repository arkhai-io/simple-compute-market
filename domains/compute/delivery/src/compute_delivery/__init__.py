"""The compute family's delivery path, one order behind two domain ports.

See openspec/specs/compute-delivery/spec.md.
"""

from .outcome import AccessRefused, DeliveryOutcome, HookDisposition, OutcomeKind, RepairReason
from .path import ComputeDeliveryPath
from .ports import (
    AcceptedDeal,
    AcceptedHold,
    ComputeDeliveryDomain,
    ContinuationState,
    DeliveryProgress,
    DeliveryStep,
    HoldPlacement,
    RecordedProgress,
    ReserveClaim,
    SiteFulfillment,
)
from .window import AgreementWindow, TimingInvalid, agreement_window

__all__ = [
    "AccessRefused",
    "AcceptedDeal",
    "AcceptedHold",
    "AgreementWindow",
    "ComputeDeliveryDomain",
    "ComputeDeliveryPath",
    "ContinuationState",
    "DeliveryOutcome",
    "DeliveryProgress",
    "DeliveryStep",
    "HoldPlacement",
    "HookDisposition",
    "OutcomeKind",
    "RecordedProgress",
    "RepairReason",
    "ReserveClaim",
    "SiteFulfillment",
    "TimingInvalid",
    "agreement_window",
]
