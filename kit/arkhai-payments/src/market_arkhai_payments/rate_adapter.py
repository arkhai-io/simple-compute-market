"""Stateless rate commands and pure authorization over verified authority state."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import datetime
import time
from typing import Any, cast, Literal

from market_deal_lifecycle.delivery import (
    BillingStartResult, DeliveryAuthorization, DeliveryEvidence, DeliveryPhase,
)
from market_deal_lifecycle.operations import OperationKeys
from market_deal_lifecycle_contracts.models import (
    Accepted, AuthorityView, LifecycleCommand, LifecycleOutcome, PaymentEvent, PaymentPartObservation, Rejected, Unknown,
)
from pydantic import ValidationError

from .adapter import PaymentAdapter, ClientForAccount
from .agreement import PaymentSettlementData
from .errors import PaymentsAPIError, PaymentsError, PaymentsProtocolError
from .mandates import duration_seconds
from .models import StoredEvent, TransactionSnapshot, RatePart, SignedTransactionSnapshot
from .operations import PaymentOperation, operations_digest
from .receipts import SnapshotVerifier
from .settlement_config import ArkhaiPaymentsConfigurationError


class RatePaymentAdapter(PaymentAdapter):
    """The caller verifies activation and persists operation descriptors before I/O.

    No authority state, replay guard or start intent is held locally. A snapshot
    is always freshly verified against the caller's durable sequence floor.
    """

    supported_commands = frozenset({"start", "stop", "reverse"})

    def __init__(self, agreement: Mapping[str, Any], data: PaymentSettlementData, *,
                 account: str, client_for_owner: ClientForAccount, verify_snapshot: SnapshotVerifier,
                 minimum_sequence: int = 0, clock: Callable[[], int] = lambda: int(time.time())) -> None:
        super().__init__(agreement, data, account=account, client_for_owner=client_for_owner,
                         verify_snapshot=verify_snapshot, minimum_sequence=minimum_sequence, _allow_rate=True)
        self._clock = clock
        self._agreement = dict(agreement)
        self.rate_parts = tuple(str(i) for i, part in enumerate(data.mandate.parts) if part.root.kind == "rate")
        if not self.rate_parts:
            raise ValueError("rate adapter requires a rate part")

    def _evidence_error(self, evidence: DeliveryEvidence, *, activated: bool) -> str | None:
        if not isinstance(evidence, DeliveryEvidence) or evidence.version != 1:
            return "malformed delivery evidence"
        if (evidence.negotiation_id, evidence.commitment_ref) != (self.negotiation_id, self.commitment_ref):
            return "delivery evidence names another deal"
        if activated:
            if (evidence.activated_delivery is None or evidence.ready is None
                    or not evidence.reservation_ref or not evidence.fulfillment_ref):
                return "verified activation, reservation, fulfillment and ready evidence are required"
            instant = evidence.activated_delivery.activated_at
            start = datetime.fromisoformat(str(self._agreement["start_utc"]).replace("Z", "+00:00")).timestamp()
            if instant < start or instant > self._clock():
                return "activation instant is outside the accepted service interval"
            ends = [self.data.mandate.parts[int(p)].root.end for p in self.rate_parts]
            if any(end is None or instant >= end.at for end in ends):
                return "activation is at or beyond the immutable term end"
        return None

    def validate(self, command: LifecycleCommand) -> Rejected | None:
        if command.kind == "reverse":
            return super().validate(command)
        if command.negotiation_id != self.negotiation_id:
            return Rejected(reason="command negotiation does not match payment commitment")
        part = command.payload.get("part")
        if part not in self.rate_parts:
            return Rejected(reason="command requires an explicit rate part")
        terms = cast(RatePart, self.data.mandate.parts[int(str(part))].root)
        if command.kind == "start":
            if command.at is not None or set(command.payload) != {"part", "activation"}:
                return Rejected(reason="start requires part and the journaled activation envelope; no at")
            if self.account not in {entry.root for entry in terms.authorities.start}:
                return Rejected(reason="account has no start authority")
            try:
                evidence = DeliveryEvidence.model_validate(command.payload["activation"])
                error = self._evidence_error(evidence, activated=True)
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

    def command_event(self, command: LifecycleCommand) -> dict[str, Any]:
        if command.kind == "reverse":
            return super().command_event(command)
        event: dict[str, Any] = {"kind": command.kind, "part": int(str(command.payload["part"]))}
        if command.kind == "start":
            event["payload"] = {"activation": command.payload["activation"]}
        if command.at is not None:
            event["at"] = command.at
        if "partialPeriod" in command.payload:
            event["partialPeriod"] = command.payload["partialPeriod"]
        return event

    def describe(self, command: LifecycleCommand, keys: OperationKeys) -> PaymentOperation:
        refusal = self.validate(command)
        if refusal is not None:
            raise ValueError(refusal.reason)
        if (keys.negotiation_id, keys.operation_key) != (command.negotiation_id, command.operation_key):
            raise ValueError("operation keys do not match the command")
        return PaymentOperation.create(transaction=self.commitment_ref, account=self.account,
                                       part=str(command.payload["part"]), event=self.command_event(command), keys=keys)

    async def submit(self, command: LifecycleCommand, keys: OperationKeys, *,
                     journaled_digest: str | None = None) -> LifecycleOutcome:
        return await asyncio.to_thread(self.submit_now, command, keys, journaled_digest=journaled_digest)

    def submit_now(self, command: LifecycleCommand, keys: OperationKeys, *,
                   journaled_digest: str | None = None) -> LifecycleOutcome:
        try:
            operation = self.describe(command, keys)
        except ValueError as exc:
            return Rejected(reason=str(exc))
        if journaled_digest != operation.digest:
            return Rejected(reason="caller must supply the identical journaled operation digest before I/O")
        if command.kind == "stop":
            try:
                signed = self.snapshot_now()
                for prior in signed.snapshot.events:
                    if (isinstance(prior.root, StoredEvent) and prior.root.account.root == self.account
                            and prior.root.requestId.root == operation.request_id
                            and prior.root.event.model_dump(mode="json", by_alias=True, exclude_none=True) != operation.event):
                        return Rejected(reason="operation key retry changes content")
                part = next(item for item in signed.snapshot.parts if str(item.part) == operation.part)
                entry = next(item for item in self.data.mandate.parts[int(operation.part)].root.authorities.stop
                             if item.account.root == self.account)
                target = max(command.at or 0, self._clock() + duration_seconds(entry.notice.root))
                if part.stop is not None and part.stop.effectiveAt <= target:
                    observed = next(item for item in self._view(signed).parts if item.part == operation.part)
                    return Accepted(records=[observed.final_stop] if observed.final_stop else [])
            except (PaymentsError, ArkhaiPaymentsConfigurationError, ValidationError) as exc:
                return Unknown(reason=f"stop requires verified read recovery: {exc}")
        result = super().submit_now(command, keys)
        if isinstance(result, Rejected):
            if "insufficient_held_funds" in result.reason:
                try:
                    self.snapshot_now()
                except (PaymentsError, ArkhaiPaymentsConfigurationError, ValidationError):
                    return Unknown(reason="insufficient held funds requires verified read reconciliation")
                return Rejected(reason="insufficient held funds: reconcile recorded reversals before another delta")
            if "hold_matured" in result.reason:
                return Rejected(reason="hold_matured: unrecoverable held-money shortfall; use the case path")
            if "transaction_stopped" in result.reason and command.kind == "start":
                return Rejected(reason="transaction_stopped: delivery must end; billing did not start")
        return result

    def billing_operations(self, operation_key: str, evidence: DeliveryEvidence) -> tuple[PaymentOperation, ...]:
        error = self._evidence_error(evidence, activated=True)
        if error:
            raise ValueError(error)
        keys = OperationKeys(self.negotiation_id, operation_key)
        return tuple(self.describe(LifecycleCommand(
            negotiation_id=self.negotiation_id, kind="start", operation_key=operation_key,
            payload={"part": part, "activation": evidence.model_dump(mode="json")},
        ), keys) for part in self.rate_parts)

    async def start_billing(self, operation_key: str, evidence: DeliveryEvidence, *,
                            journaled_digest: str | None = None) -> BillingStartResult:
        try:
            operations = self.billing_operations(operation_key, evidence)
        except (ValueError, TypeError) as exc:
            return BillingStartResult(outcome=Rejected(reason=str(exc)))
        if journaled_digest != operations_digest(operations):
            return BillingStartResult(outcome=Rejected(reason="billing requires the journaled descriptor digest"))
        records = []
        for operation in operations:
            result = await self.submit(LifecycleCommand(
                negotiation_id=self.negotiation_id, kind="start", operation_key=operation_key,
                payload={"part": operation.part, "activation": evidence.model_dump(mode="json")},
            ), OperationKeys(self.negotiation_id, operation_key), journaled_digest=operation.digest)
            if not isinstance(result, Accepted):
                return BillingStartResult(outcome=result)
            records.extend(result.records)
        return BillingStartResult(outcome=Accepted(records=records))

    def events(self, snapshot: TransactionSnapshot) -> list[PaymentEvent]:
        result = []
        for wrapped in snapshot.events:
            stored = wrapped.root
            event = stored.event
            kind = stored.event.kind.value if isinstance(stored, StoredEvent) else stored.event.kind
            for part in snapshot.parts:
                if event.part is not None and event.part != part.part:
                    continue
                actor = stored.account.root if isinstance(stored, StoredEvent) else "terms"
                sequence = stored.sequence
                assert sequence is not None
                # Stop requests are not final ends. The winning final record,
                # including an equal-time winner, lives in the per-part view.
                projected = "stop_request" if kind == "stop" else kind
                if kind not in {"start", "stop", "reverse", "extend", "lift"}:
                    raise PaymentsProtocolError("unsupported rate authority event")
                payload = stored.event.payload if isinstance(stored, StoredEvent) else None
                case = payload.get("case_ref") if isinstance(payload, dict) else None
                if case is not None and (not isinstance(case, str) or not case):
                    raise PaymentsProtocolError("invalid payment event case reference")
                result.append(PaymentEvent(
                    negotiation_id=self.negotiation_id, commitment_ref=self.commitment_ref,
                    part=str(part.part), kind=cast(Any, projected), actor=actor, at=stored.receivedAt,
                    amount=stored.event.amount.root if isinstance(stored, StoredEvent) and stored.event.amount else None,
                    cause=("terms" if actor == "terms" else "payer" if actor == self.data.mandate.from_.root
                           else "payee" if actor == self.data.mandate.to.root else "authority"),
                    case_ref=case, extension_ref=(str(sequence) if kind == "extend" else
                                                str(stored.event.ref) if kind == "lift" and isinstance(stored, StoredEvent) else None),
                    sequence=sequence, authority_record_ref=f"{self.commitment_ref}:events:{sequence}",
                ))
        return result

    def _view(self, signed: SignedTransactionSnapshot) -> AuthorityView:
        view = super()._view(signed)
        snapshot = signed.snapshot
        observations = []
        for part in snapshot.parts:
            if str(part.part) not in self.rate_parts:
                continue
            def stop_event(stop: Any, *, final: bool) -> PaymentEvent | None:
                if stop is None:
                    return None
                sequence = stop.sequence
                source = next((e.root for e in snapshot.events if e.root.sequence == sequence), None)
                if source is None or (source.event.kind.value if isinstance(source, StoredEvent) else source.event.kind) != "stop":
                    raise PaymentsProtocolError("winning stop has no authority stop event")
                actor = source.account.root if isinstance(source, StoredEvent) else "terms"
                treatment = {"charged": "started_period", "returned": "last_boundary", "prorated": "stop"}.get(stop.partialPeriod.value)
                if treatment is None:
                    raise PaymentsProtocolError("unknown winning partial-period rule")
                return PaymentEvent(
                    negotiation_id=self.negotiation_id, commitment_ref=self.commitment_ref,
                    part=str(part.part), kind="stop" if final else "stop_request", actor=actor,
                    at=stop.effectiveAt if final else stop.at, cause=stop.cause.value,
                    settles_through=cast(Any, treatment), sequence=sequence,
                    authority_record_ref=f"{self.commitment_ref}:events:{sequence}:part:{part.part}",
                )
            reserved = None if part.reserved is None else int(part.reserved.root) >= int(self.data.mandate.parts[part.part].root.amount.root)
            observations.append(PaymentPartObservation(
                part=str(part.part), started_at=part.started,
                end_at=part.end.at if part.end else None,
                funded_through=part.rate.reservedThrough if part.rate else None,
                initial_reservation=reserved, pending_stop=stop_event(part.pendingStop, final=False),
                final_stop=stop_event(part.stop, final=True),
                release_at=int(datetime.fromisoformat(part.releaseAt.replace("Z", "+00:00")).timestamp()) if part.releaseAt else None,
                evidence_ref=f"{self.commitment_ref}:snapshot:{snapshot.latestEventSequence}:{snapshot.observedAt}",
            ))
        bounds = [bound for part in observations for bound in (
            part.end_at, part.funded_through, part.pending_stop.at if part.pending_stop else None,
            part.final_stop.at if part.final_stop else None,
        ) if bound is not None]
        state = ("ended" if any(part.final_stop for part in observations) else
                 "ending" if any(part.pending_stop for part in observations) else
                 "running" if all(part.started_at is not None for part in observations) else "unstarted")
        return view.model_copy(update={"parts": observations, "state": state, "deadline": min(bounds) if bounds else None})

    async def authorize(self, phase: DeliveryPhase, evidence: DeliveryEvidence, *,
                        billing_operation_key: str | None = None) -> DeliveryAuthorization:
        operation_id = f"{self.negotiation_id}:{phase.value if isinstance(phase, DeliveryPhase) else phase}"
        refs = [self.commitment_ref]
        def answer(status: Literal["allow", "refuse", "pending"], reason: str) -> DeliveryAuthorization:
            return DeliveryAuthorization(status=status, reason=reason, operation_id=operation_id, evidence_refs=refs)
        if phase not in {DeliveryPhase.COMMIT, DeliveryPhase.DISPATCH, DeliveryPhase.START, DeliveryPhase.DISCLOSE}:
            return answer("refuse", "unsupported rate delivery phase")
        error = self._evidence_error(evidence, activated=phase == DeliveryPhase.DISCLOSE)
        if error:
            return answer("refuse", error)
        try:
            signed = await asyncio.to_thread(self.snapshot_now)
        except (PaymentsError, ArkhaiPaymentsConfigurationError, ValidationError):
            return answer("pending", "verified current authority state is unavailable")
        snapshot = signed.snapshot
        refs.append(f"{self.commitment_ref}:snapshot:{snapshot.latestEventSequence}:{snapshot.observedAt}")
        now = self._clock()
        if snapshot.observedAt < now:
            return answer("pending", "authority observation is stale; refresh at the decision instant")
        if snapshot.receipt.receipt.approvedAt >= self.data.mandate.expires:
            return answer("refuse", "approval was not timely")
        parts = [part for part in snapshot.parts if str(part.part) in self.rate_parts]
        if any(part.stop is not None or (part.end is not None and part.end.at <= now)
               or (part.pendingStop is not None and part.pendingStop.at <= now) for part in parts):
            return answer("refuse", "verified stop or maximum term is effective")
        if phase == DeliveryPhase.COMMIT:
            return answer("allow", "verified timely approved rate commitment")
        if any(part.started is not None for part in parts):
            if snapshot.fundedThrough is None:
                return answer("pending", "started rate has no verified funding boundary")
            if snapshot.fundedThrough <= now:
                return answer("refuse", "verified rate funding is exhausted")
        elif any(part.reserved is None or int(part.reserved.root) < int(self.data.mandate.parts[part.part].root.amount.root)
                 for part in parts):
            return answer("pending", "initial rate reservation is unproven")
        if phase == DeliveryPhase.DISCLOSE:
            if billing_operation_key is None or any(part.started is None for part in parts):
                return answer("pending", "journal-bound billing start is unresolved")
            try:
                operations = self.billing_operations(billing_operation_key, evidence)
            except ValueError as exc:
                return answer("refuse", str(exc))
            for operation in operations:
                if not any(isinstance(event.root, StoredEvent) and event.root.account.root == operation.account
                           and event.root.requestId.root == operation.request_id
                           and event.root.event.model_dump(mode="json", by_alias=True, exclude_none=True) == operation.event
                           for event in snapshot.events):
                    return answer("pending", "start is not bound to the journaled billing intent")
        return answer("allow", "verified rate funding and no effective end")
