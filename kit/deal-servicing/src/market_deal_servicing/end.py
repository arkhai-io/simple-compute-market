"""Replay physical and billing effects without owning financial interpretation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable, Protocol

from market_deal_lifecycle.adapters import PaymentAdapter
from market_deal_lifecycle.delivery import (
    BillingStartResult, DeliveryAuthorization, DeliveryEvidence, DeliveryPhase,
)
from market_deal_lifecycle_contracts.models import (
    Accepted, Reference, Rejected, WireModel,
)
from .evidence import transaction
from .journal import (
    EndSession, JournalIntent, PhysicalProgress, create_schema, stable_ref,
)


class PhysicalResult(WireModel):
    progress: PhysicalProgress
    done: bool


class DomainEndPort(Protocol):
    async def apply_end(
        self, negotiation_id: str, *, terminate: bool, at: int, operation_key: str,
    ) -> PhysicalResult:
        """Adopt dispatched work; deduplicate the key before terminate/truncate.

        No dispatched resource is a completed no-op, not queued teardown. A
        termination acknowledgement may still report tearing_down. Only the
        domain's release guard can report recovered capacity. Truncation must
        never extend a lease or resurrect an already-ended resource, including
        when an older request completes after a newer termination.
        """
        ...


class BillingIntentResult(WireModel):
    intent_ref: Reference
    result: BillingStartResult


class EndService:
    def __init__(self, path: str | Path, physical: DomainEndPort, *, clock: Callable[[], int]):
        self.path = Path(path)
        self.physical = physical
        self.clock = clock
        with transaction(self.path) as conn:
            create_schema(conn)

    def _prepare_physical(self, negotiation_id: str) -> list[JournalIntent]:
        with transaction(self.path) as conn:
            session = EndSession(conn)
            session.schedule_physical(negotiation_id, now=self.clock())
            pending = session.intents(negotiation_id, pending_only=True)
            selected = session.selected_end(negotiation_id)
            ready = []
            for intent in pending:
                if intent.kind not in {"terminate", "truncate"}:
                    continue
                if intent.kind == "truncate" and (
                    selected is None or intent.payload["at"] != selected.ended_at
                    or selected.ended_at <= self.clock()
                ):
                    session.acknowledge(intent.intent_ref, {"reason": "superseded end"}, state="skipped")
                    continue
                ready.append(intent)
            return ready

    async def drive_physical(self, negotiation_id: str) -> list[PhysicalResult]:
        intents = await asyncio.to_thread(self._prepare_physical, negotiation_id)
        results = []
        for intent in intents:
            # Domain keys are stable even if a response is lost after the effect.
            result = await self.physical.apply_end(
                negotiation_id, terminate=intent.kind == "terminate",
                at=intent.payload["at"], operation_key=intent.intent_ref,
            )
            with transaction(self.path) as conn:
                session = EndSession(conn)
                session.physical_progress(negotiation_id, result.progress)
                session.acknowledge(
                    intent.intent_ref, result.model_dump(mode="json"),
                    state="done" if result.done else "pending",
                )
            results.append(result)
        return results

    async def authorize_delivery(
        self, phase: DeliveryPhase, evidence: DeliveryEvidence, *,
        adapter: PaymentAdapter | None, session: EndSession, expected_revision: int,
    ) -> DeliveryAuthorization:
        """The caller keeps this session through its protected delivery write.

        Financial evidence can only narrow local admission. A stale revision or
        an end committed while the adapter reads never authorizes the caller.
        """
        if adapter is None:
            return DeliveryAuthorization(
                status="refuse", reason="selected mechanism has no delivery adapter",
                operation_id=f"{evidence.negotiation_id}:{phase.value}",
                evidence_refs=[evidence.commitment_ref],
            )
        record = session.read(evidence.negotiation_id)
        if record.commitment_ref != evidence.commitment_ref:
            return DeliveryAuthorization(
                status="refuse", reason="delivery evidence names another commitment",
                operation_id=f"{evidence.negotiation_id}:{phase.value}",
                evidence_refs=[evidence.commitment_ref],
            )
        if record.committed_at is None:
            return DeliveryAuthorization(
                status="pending", reason="commitment has not been verified",
                operation_id=f"{evidence.negotiation_id}:{phase.value}",
                evidence_refs=[evidence.commitment_ref],
            )
        financial = await adapter.authorize(phase, evidence)
        admission = session.admit(
            evidence.negotiation_id, phase, expected_revision, now=self.clock(),
        )
        if admission.status != "admitted":
            financial = financial.model_copy(update={
                "status": "pending" if admission.status == "retry" else "refuse",
                "reason": "stale admission revision" if admission.status == "retry" else "delivery ended",
            })
        if phase == DeliveryPhase.DISCLOSE and financial.status == "allow":
            billing = [item for item in session.intents(evidence.negotiation_id) if item.kind == "billing"]
            if (
                not billing or billing[0].state != "done" or billing[0].result is None
                or billing[0].result["outcome"]["status"] != "accepted"
            ):
                financial = financial.model_copy(update={
                    "status": "pending", "reason": "billing start requires same-key resolution",
                })
        intent = session.journal(
            evidence.negotiation_id, "authorization",
            f"{financial.operation_id}:{admission.revision}",
            {"phase": phase.value, "evidence": evidence.model_dump(mode="json")},
            not_before=record.committed_at,
        )
        session.acknowledge(
            intent.intent_ref, financial.model_dump(mode="json"),
            state="pending" if financial.status == "pending" else "done",
        )
        return financial.model_copy(update={"operation_id": intent.intent_ref})

    async def begin_billing(
        self, operation_key: str, activated_delivery_ref: DeliveryEvidence, *,
        adapter: PaymentAdapter | None,
    ) -> BillingIntentResult:
        """Persist the only billing-start key and evidence before authority I/O."""
        evidence = activated_delivery_ref
        if evidence.activated_delivery is None or evidence.activated_delivery.activated_at > self.clock():
            return self._billing_refusal(evidence, operation_key, "durable activation evidence is required")
        if adapter is None:
            return self._billing_refusal(evidence, operation_key, "selected mechanism has no billing adapter")
        with transaction(self.path) as conn:
            session = EndSession(conn)
            record = session.read(evidence.negotiation_id)
            if record.commitment_ref != evidence.commitment_ref:
                return self._billing_refusal(evidence, operation_key, "billing evidence names another commitment")
            if record.committed_at is None:
                return self._billing_refusal(evidence, operation_key, "commitment has not been verified")
            existing = [item for item in session.intents(evidence.negotiation_id) if item.kind == "billing"]
            if existing:
                intent = existing[0]
                if intent.operation_key != operation_key or intent.payload != evidence.model_dump(mode="json"):
                    return self._billing_refusal(evidence, operation_key, "billing-start retry changes key or evidence")
                if intent.state == "done" and intent.result is not None:
                    return BillingIntentResult(
                        intent_ref=intent.intent_ref, result=BillingStartResult.model_validate(intent.result),
                    )
            else:
                admission = session.admit(
                    evidence.negotiation_id, DeliveryPhase.START, record.revision, now=self.clock(),
                )
                if admission.status != "admitted":
                    return self._billing_refusal(evidence, operation_key, "delivery ended before billing start")
                intent = session.journal(
                    evidence.negotiation_id, "billing", operation_key,
                    evidence.model_dump(mode="json"), not_before=self.clock(),
                )
        # A retry of an unknown result uses the adapter's same-key resolution;
        # no generic servicing code guesses from a mechanism snapshot.
        result = await adapter.start_billing(operation_key, evidence)
        with transaction(self.path) as conn:
            EndSession(conn).acknowledge(
                intent.intent_ref, result.model_dump(mode="json"),
                state="done" if isinstance(result.outcome, (Accepted, Rejected)) else "pending",
            )
        return BillingIntentResult(intent_ref=intent.intent_ref, result=result)

    @staticmethod
    def _billing_refusal(evidence: DeliveryEvidence, key: str, reason: str) -> BillingIntentResult:
        return BillingIntentResult(
            intent_ref=stable_ref(evidence.negotiation_id, "billing", key),
            result=BillingStartResult(outcome=Rejected(reason=reason)),
        )


class SQLiteOperationStore:
    """The foundation's replay guard, independent of evidence retention."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    async def check_and_record(self, negotiation_id: str, operation_key: str, digest: str) -> bool:
        def remember() -> bool:
            with transaction(self.path) as conn:
                return EndSession(conn).check_and_record(negotiation_id, operation_key, digest)
        return await asyncio.to_thread(remember)
