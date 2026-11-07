"""Secret-free identities used to authorize delivery and begin billing."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Annotated, Literal

from market_deal_lifecycle_contracts.models import (
    Accepted, Instant, LifecycleOutcome, Reference, Rejected, WireModel,
)
from pydantic import Field

from .terms import Version

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class DeliveryPhase(str, Enum):
    RESERVE = "reserve"
    COMMIT = "commit"
    DISPATCH = "dispatch"
    ACTIVATE = "activate"
    START = "start"
    DISCLOSE = "disclose"


class ActivatedDeliveryRef(WireModel):
    version: Version = 1
    record_ref: Reference
    activated_at: Instant


class ReadyEvidenceRef(WireModel):
    version: Version = 1
    schema_id: Reference
    resource_ref: Reference
    digest: Digest


class DeliveryEvidence(WireModel):
    version: Version = 1
    negotiation_id: Reference
    commitment_ref: Reference
    reservation_ref: Reference | None = None
    fulfillment_ref: Reference | None = None
    activated_delivery: ActivatedDeliveryRef | None = None
    ready: ReadyEvidenceRef | None = None


class DeliveryAuthorization(WireModel):
    status: Literal["allow", "refuse", "pending"]
    reason: Reference
    operation_id: Reference
    evidence_refs: list[Reference]


class BillingStartResult(WireModel):
    outcome: LifecycleOutcome
    no_op: bool = False


class OnceDeliveryPolicy:
    """Once-only delivery makes no new financial action after verifying commitment.

    The validator is mechanism-owned and checks the versioned evidence against
    the selected stage's committed form; presence of a reference is not proof.
    """

    def __init__(self, validate_commitment: Callable[[DeliveryEvidence], Awaitable[bool]]) -> None:
        self._validate_commitment = validate_commitment

    async def authorize(self, phase: DeliveryPhase, evidence: DeliveryEvidence) -> DeliveryAuthorization:
        valid = await self._validate_commitment(evidence)
        return DeliveryAuthorization(
            status="allow" if valid else "refuse",
            reason="validated once commitment" if valid else "invalid commitment evidence",
            operation_id=f"{evidence.negotiation_id}:{phase.value}",
            evidence_refs=[evidence.commitment_ref],
        )

    async def start_billing(self, operation_key: str, evidence: DeliveryEvidence) -> BillingStartResult:
        if evidence.activated_delivery is None:
            return BillingStartResult(outcome=Rejected(reason="activation evidence is required"))
        if not await self._validate_commitment(evidence):
            return BillingStartResult(outcome=Rejected(reason="invalid commitment evidence"))
        return BillingStartResult(outcome=Accepted(), no_op=True)
