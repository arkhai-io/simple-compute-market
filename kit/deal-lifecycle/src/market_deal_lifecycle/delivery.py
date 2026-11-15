"""Secret-free identities used to authorize delivery and begin billing."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Annotated, Any, Literal

from market_deal_lifecycle_contracts.models import (
    Accepted, Instant, LifecycleOutcome, Reference, Rejected, WireModel,
)
from pydantic import Field, SerializerFunctionWrapHandler, model_serializer

from .operations import OperationKeys
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


#: Why end service refused a phase, where a caller must act on the cause rather
#: than on the free-text reason. ``rate_servicing_unavailable``: end service
#: services no rate deal, so it refuses to commit one.
RefusalCode = Literal["rate_servicing_unavailable"]


class DeliveryAuthorization(WireModel):
    """A delivery phase's answer; ``code`` is set only on a refusal that names one.

    An answer without a code dumps without the key: end service compares a
    re-acknowledged answer with the one its journal holds, and an authorization
    journaled without the key must still compare equal.
    """

    status: Literal["allow", "refuse", "pending"]
    reason: Reference
    operation_id: Reference
    evidence_refs: list[Reference]
    code: RefusalCode | None = None

    @model_serializer(mode="wrap")
    def _omit_absent_code(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data = dict(handler(self))
        if self.code is None:
            data.pop("code", None)
        return data


class BillingStartResult(WireModel):
    outcome: LifecycleOutcome
    no_op: bool = False


class JournaledBillingStart(WireModel):
    """End service's one billing-start intent, as its journal holds it.

    The operation key names the intent whose per-part starts the payment
    authority must carry; the result, once the journal has one, can refuse
    disclosure definitively. It is the caller's record, never authority state.
    """

    operation_key: Reference
    result: BillingStartResult | None = None


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

    async def start_billing(self, keys: OperationKeys, evidence: DeliveryEvidence) -> BillingStartResult:
        if evidence.activated_delivery is None:
            return BillingStartResult(outcome=Rejected(reason="activation evidence is required"))
        if not await self._validate_commitment(evidence):
            return BillingStartResult(outcome=Rejected(reason="invalid commitment evidence"))
        return BillingStartResult(outcome=Accepted(), no_op=True)
