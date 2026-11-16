"""What rate parts add to a payments transaction: start, stop, notice and authorization.

The payments transaction adapter composes this behaviour when its mandate has a
rate part. It holds no authority state, replay guard or start intent: every
decision reads a freshly verified snapshot, and the adapter records each
operation descriptor through the caller's operation store before any I/O.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Literal, cast

from market_deal_lifecycle.delivery import (
    DeliveryAuthorization, DeliveryEvidence, DeliveryPhase, JournaledBillingStart,
)
from market_deal_lifecycle_contracts.models import (
    Instant, LifecycleCommand, PaymentEvent, PaymentPartObservation, Rejected,
)

from .agreement import PaymentSettlementData
from .errors import PaymentsProtocolError
from .mandates import duration_seconds
from .models import RatePart, SignedTransactionSnapshot, StoredEvent
from .operations import PaymentOperation
from .transaction import READ_FAILURES, VerifiedSnapshots, recorded_by

_TREATMENTS = {"charged": "started_period", "returned": "last_boundary", "prorated": "stop"}

Describe = Callable[[LifecycleCommand], PaymentOperation]


def deal_stop(command: LifecycleCommand) -> bool:
    """A notice, or a stop naming no part, stops every rate part of the deal."""

    return command.kind == "notice" or (command.kind == "stop" and not command.payload)


class RateParts:
    """Rate behaviour for one accepted mandate under one account's credential."""

    def __init__(
        self, agreement: Mapping[str, Any], data: PaymentSettlementData, *, account: str,
        snapshots: VerifiedSnapshots, clock: Callable[[], int], freshness_seconds: int,
    ) -> None:
        if type(freshness_seconds) is not int or freshness_seconds <= 0:
            raise ValueError("snapshot freshness must be positive whole seconds")
        self.negotiation_id = str(agreement["negotiation_id"])
        self.commitment_ref = data.transaction_id
        self.data = data
        self.account = account
        self.snapshots = snapshots
        self.clock = clock
        self.freshness = freshness_seconds
        self.start_utc = datetime.fromisoformat(str(agreement["start_utc"]).replace("Z", "+00:00")).timestamp()
        self.parts = tuple(str(i) for i, part in enumerate(data.mandate.parts) if part.root.kind == "rate")
        if not self.parts:
            raise ValueError("rate behaviour requires a rate part")

    def evidence_error(self, evidence: DeliveryEvidence, *, activated: bool) -> str | None:
        if not isinstance(evidence, DeliveryEvidence) or evidence.version != 1:
            return "malformed delivery evidence"
        if (evidence.negotiation_id, evidence.commitment_ref) != (self.negotiation_id, self.commitment_ref):
            return "delivery evidence names another deal"
        if activated:
            if (evidence.activated_delivery is None or evidence.ready is None
                    or not evidence.reservation_ref or not evidence.fulfillment_ref):
                return "verified activation, reservation, fulfillment and ready evidence are required"
            instant = evidence.activated_delivery.activated_at
            if instant < self.start_utc or instant > self.clock():
                return "activation instant is outside the accepted service interval"
            ends = [self._terms(part).end for part in self.parts]
            if any(end is None or instant >= end.at for end in ends):
                return "activation is at or beyond the immutable term end"
        return None

    def _terms(self, part: str) -> RatePart:
        return cast(RatePart, self.data.mandate.parts[int(part)].root)

    def expand(self, command: LifecycleCommand) -> tuple[LifecycleCommand, ...]:
        """The per-part commands one deal-level stop sends, each with explicit parts."""

        if not deal_stop(command):
            return (command,)
        return tuple(command.model_copy(update={"kind": "stop", "payload": {"part": part}}) for part in self.parts)

    def validate(self, command: LifecycleCommand) -> Rejected | None:
        if deal_stop(command):
            if command.kind == "notice" and self.account != self.data.mandate.to.root:
                return Rejected(reason="seller notice requires the accepted payee account")
            if command.payload:
                return Rejected(reason="notice derives all affected rate parts from the accepted mandate")
            for stop in self.expand(command):
                refusal = self.validate(stop)
                if refusal is not None:
                    return refusal
            return None
        part = command.payload.get("part")
        if part not in self.parts:
            return Rejected(reason="command requires an explicit rate part")
        terms = self._terms(str(part))
        if command.kind == "start":
            if command.at is not None or set(command.payload) != {"part", "activation"}:
                return Rejected(reason="start requires part and the journaled activation envelope; no at")
            if self.account not in {entry.root for entry in terms.authorities.start}:
                return Rejected(reason="account has no start authority")
            try:
                evidence = DeliveryEvidence.model_validate(command.payload["activation"])
                error = self.evidence_error(evidence, activated=True)
            except (ValueError, TypeError):
                error = "malformed activation evidence"
            return Rejected(reason=error) if error else None
        if command.kind == "stop":
            if set(command.payload) - {"part", "partialPeriod"}:
                return Rejected(reason="stop accepts only part and chosen treatment")
            entry = next((item for item in terms.authorities.stop if item.account.root == self.account), None)
            if entry is None:
                return Rejected(reason="account has no entitled stop authority")
            treatment = command.payload.get("partialPeriod")
            if entry.partialPeriod.root == "chosen":
                if treatment not in {"charged", "returned", "prorated"}:
                    return Rejected(reason="chosen stop requires an explicit partialPeriod")
            elif treatment is not None:
                return Rejected(reason="fixed entitled treatment cannot be overridden")
            return None
        return Rejected(reason="unsupported rate payment command")

    @staticmethod
    def event(command: LifecycleCommand) -> dict[str, Any]:
        event: dict[str, Any] = {"kind": command.kind, "part": int(str(command.payload["part"]))}
        if command.kind == "start":
            event["payload"] = {"activation": command.payload["activation"]}
        if command.at is not None:
            event["at"] = command.at
        if "partialPeriod" in command.payload:
            event["partialPeriod"] = command.payload["partialPeriod"]
        return event

    def earlier_stop(
        self, signed: SignedTransactionSnapshot, command: LifecycleCommand, operation: PaymentOperation,
    ) -> PaymentEvent | None:
        """The verified final stop that already satisfies this stop, if one does.

        A repeated stop is satisfied only by a stop effective no later than this
        one would be: the earliest stop wins at the authority and cannot be
        postponed by asking again.
        """

        part = next(item for item in signed.snapshot.parts if str(item.part) == operation.part)
        entry = next(item for item in self._terms(operation.part).authorities.stop
                     if item.account.root == self.account)
        target = max(command.at or 0, self.clock() + duration_seconds(entry.notice.root))
        if part.stop is None or part.stop.effectiveAt > target:
            return None
        observed = next(item for item in self.observations(signed) if item.part == operation.part)
        return observed.final_stop

    def billing_commands(self, operation_key: str, evidence: DeliveryEvidence) -> tuple[LifecycleCommand, ...]:
        """The per-part starts of end service's one billing-start intent."""

        error = self.evidence_error(evidence, activated=True)
        if error:
            raise ValueError(error)
        return tuple(LifecycleCommand(
            negotiation_id=self.negotiation_id, kind="start", operation_key=operation_key,
            payload={"part": part, "activation": evidence.model_dump(mode="json")},
        ) for part in self.parts)

    def observations(self, signed: SignedTransactionSnapshot) -> list[PaymentPartObservation]:
        snapshot = signed.snapshot

        def stop_event(part: int, stop: Any, *, final: bool) -> PaymentEvent | None:
            if stop is None:
                return None
            sequence = stop.sequence
            source = next((e.root for e in snapshot.events if e.root.sequence == sequence), None)
            if source is None or (source.event.kind.value if isinstance(source, StoredEvent)
                                  else source.event.kind) != "stop":
                raise PaymentsProtocolError("winning stop has no authority stop event")
            treatment = _TREATMENTS.get(stop.partialPeriod.value)
            if treatment is None:
                raise PaymentsProtocolError("unknown winning partial-period rule")
            return PaymentEvent(
                negotiation_id=self.negotiation_id, commitment_ref=self.commitment_ref,
                part=str(part), kind="stop" if final else "stop_request",
                actor=source.account.root if isinstance(source, StoredEvent) else "terms",
                at=stop.effectiveAt if final else stop.at, cause=stop.cause.value,
                settles_through=cast(Any, treatment), sequence=sequence,
                authority_record_ref=f"{self.commitment_ref}:events:{sequence}:part:{part}",
            )

        observations = []
        for part in snapshot.parts:
            if str(part.part) not in self.parts:
                continue
            amount = int(self._terms(str(part.part)).amount.root)
            observations.append(PaymentPartObservation(
                part=str(part.part), started_at=part.started,
                end_at=part.end.at if part.end else None,
                funded_through=part.rate.reservedThrough if part.rate else None,
                initial_reservation=None if part.reserved is None else int(part.reserved.root) >= amount,
                pending_stop=stop_event(part.part, part.pendingStop, final=False),
                final_stop=stop_event(part.part, part.stop, final=True),
                release_at=(int(datetime.fromisoformat(part.releaseAt.replace("Z", "+00:00")).timestamp())
                            if part.releaseAt else None),
                evidence_ref=f"{self.commitment_ref}:snapshot:{snapshot.latestEventSequence}:{snapshot.observedAt}",
            ))
        return observations

    @staticmethod
    def state(observations: list[PaymentPartObservation]) -> tuple[str, Instant | None]:
        bounds = [bound for part in observations for bound in (
            part.end_at, part.funded_through, part.pending_stop.at if part.pending_stop else None,
            part.final_stop.at if part.final_stop else None,
        ) if bound is not None]
        state = ("ended" if any(part.final_stop for part in observations) else
                 "ending" if any(part.pending_stop for part in observations) else
                 "running" if all(part.started_at is not None for part in observations) else "unstarted")
        return state, min(bounds) if bounds else None

    async def authorize(
        self, phase: DeliveryPhase, evidence: DeliveryEvidence, billing: JournaledBillingStart | None,
        *, describe: Describe, read: Callable[[], Any],
    ) -> DeliveryAuthorization:
        operation_id = f"{self.negotiation_id}:{phase.value if isinstance(phase, DeliveryPhase) else phase}"
        refs = [self.commitment_ref]

        def answer(status: Literal["allow", "refuse", "pending"], reason: str) -> DeliveryAuthorization:
            return DeliveryAuthorization(status=status, reason=reason, operation_id=operation_id, evidence_refs=refs)

        if phase not in {DeliveryPhase.COMMIT, DeliveryPhase.DISPATCH, DeliveryPhase.START, DeliveryPhase.DISCLOSE}:
            return answer("refuse", "unsupported rate delivery phase")
        error = self.evidence_error(evidence, activated=phase == DeliveryPhase.DISCLOSE)
        if error:
            return answer("refuse", error)
        try:
            signed = await read()
        except READ_FAILURES:
            return answer("pending", "verified current authority state is unavailable")
        snapshot = signed.snapshot
        refs.append(f"{self.commitment_ref}:snapshot:{snapshot.latestEventSequence}:{snapshot.observedAt}")
        now = self.clock()
        # observedAt is the authority's claim on its own clock, never ordered
        # against the storefront's. The window only bounds how stale a view may
        # decide a phase; every bound below is still checked at the storefront's now.
        if now - snapshot.observedAt > self.freshness:
            return answer("pending", "authority observation is older than the freshness window; refresh")
        if snapshot.receipt.receipt.approvedAt >= self.data.mandate.expires:
            return answer("refuse", "approval was not timely")
        parts = [part for part in snapshot.parts if str(part.part) in self.parts]
        if any(part.stop is not None or (part.end is not None and part.end.at <= now)
               or (part.pendingStop is not None and part.pendingStop.at <= now) for part in parts):
            return answer("refuse", "verified stop or maximum term is effective")
        if phase == DeliveryPhase.COMMIT:
            return answer("allow", "verified timely approved rate commitment")
        if phase == DeliveryPhase.DISCLOSE and billing is not None and billing.result is not None:
            if isinstance(billing.result.outcome, Rejected):
                return answer("refuse", "journaled billing start refused: " + billing.result.outcome.reason)
        if any(part.started is not None for part in parts):
            if snapshot.fundedThrough is None:
                return answer("pending", "started rate has no verified funding boundary")
            if snapshot.fundedThrough <= now:
                return answer("refuse", "verified rate funding is exhausted")
        elif any(part.reserved is None or int(part.reserved.root) < int(self._terms(str(part.part)).amount.root)
                 for part in parts):
            return answer("pending", "initial rate reservation is unproven")
        if phase == DeliveryPhase.DISCLOSE:
            if billing is None or any(part.started is None for part in parts):
                return answer("pending", "journal-bound billing start is unresolved")
            try:
                operations = [describe(command) for command in self.billing_commands(billing.operation_key, evidence)]
            except ValueError as exc:
                return answer("refuse", str(exc))
            if any(recorded_by(signed, operation) is None for operation in operations):
                return answer("pending", "start is not bound to the journaled billing intent")
        return answer("allow", "verified rate funding and no effective end")
