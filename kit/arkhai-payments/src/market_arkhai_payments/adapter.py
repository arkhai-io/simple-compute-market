"""The payments transaction adapter: one accepted commitment, composed by part kind.

One adapter implements the lifecycle ``PaymentAdapter`` protocol for every
mandate. Shared parts — mandate binding, verified reads, event projection,
reverse, refusal classification and descriptor recording — serve every part;
rate parts add start, stop, notice, their observations and the rate delivery
phases. Once and rate behaviour do not inherit from one another: a once-only
mandate simply has no rate behaviour composed in, so it refuses rate commands
and its billing start is a no-op.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
import time
from typing import Any, cast

from market_deal_lifecycle.delivery import (
    BillingStartResult, DeliveryAuthorization, DeliveryEvidence, DeliveryPhase, JournaledBillingStart,
    OnceDeliveryPolicy,
)
from market_deal_lifecycle.operations import OperationKeys
from market_deal_lifecycle_contracts.models import (
    Accepted, AuthorityView, DisputeEvent, LifecycleCommand, LifecycleOutcome, OpenExtension, PaymentEvent, Rejected,
    Unknown,
)

from .agreement import PaymentSettlementData
from .errors import PaymentsProtocolError
from .models import SignedTransactionSnapshot, StoredEvent, TransactionSnapshot
from .operations import PaymentOperation
from .rate_parts import RateParts, deal_stop
from .receipts import SnapshotVerifier, verify_snapshot
from .settlement_config import DEFAULT_SNAPSHOT_FRESHNESS_SECONDS, ArkhaiPaymentsConfig
from .transaction import (
    READ_FAILURES, ClientForAccount, LifecyclePaymentsClient, VerifiedSnapshots, classify_failure,
    record_descriptors, recorded_by,
)

ONCE_COMMANDS = frozenset({"reverse"})
RATE_COMMANDS = frozenset({"start", "stop", "notice", "reverse"})


def pinned_snapshot_verifier(
    agreement: Mapping[str, Any], data: PaymentSettlementData, config: ArkhaiPaymentsConfig,
) -> SnapshotVerifier:
    """Bind the shared snapshot verifier to the configured receipt identities.

    The configured current and retiring identities (``receipt_identities``, or
    ``service_identity`` alone without one) both apply, each within its window;
    a deal approved under an identity absent from the configuration does not
    verify, so open deals are drained before their identity leaves it.
    """

    def verify(signed: SignedTransactionSnapshot, minimum_sequence: int) -> bool:
        trust = config.receipt_trust
        return bool(trust) and verify_snapshot(
            signed, trust, mandate=data.mandate, agreement_json=agreement,
            livemode=config.livemode, minimum_sequence=minimum_sequence,
        )

    return verify


class PaymentAdapter:
    """One accepted commitment, with credentials and verification injected.

    The composition supplies its pinned snapshot verifier and durable cursor
    floor. No cached snapshot or command outcome is a payment ledger: every
    effect is accepted only once the verified authority record carries it, and
    replays are resolved by stable per-part request identities. A rate deal's
    descriptors, and a once reverse's when the caller supplies a store, are
    recorded through the caller's operation store before any I/O.
    """

    def __init__(
        self, agreement: Mapping[str, Any], data: PaymentSettlementData, *,
        account: str, client_for_owner: ClientForAccount, verify_snapshot: SnapshotVerifier,
        minimum_sequence: int = 0, clock: Callable[[], int] = lambda: int(time.time()),
        snapshot_freshness_seconds: int = DEFAULT_SNAPSHOT_FRESHNESS_SECONDS,
    ) -> None:
        data.require_bound_to(agreement)
        self.negotiation_id = str(agreement["negotiation_id"])
        self.commitment_ref = data.transaction_id
        self.data = data
        self.account = account
        self.snapshots = VerifiedSnapshots(
            data.transaction_id, len(data.mandate.parts), account=account,
            client_for_owner=client_for_owner, verify=verify_snapshot, minimum_sequence=minimum_sequence,
        )
        self.rate = (
            RateParts(agreement, data, account=account, snapshots=self.snapshots, clock=clock,
                      freshness_seconds=snapshot_freshness_seconds)
            if any(part.root.kind == "rate" for part in data.mandate.parts) else None
        )
        self.supported_commands = RATE_COMMANDS if self.rate is not None else ONCE_COMMANDS
        self._once = OnceDeliveryPolicy(self._commitment_matches)

    # Commands -------------------------------------------------------------------

    def validate(self, command: LifecycleCommand) -> Rejected | None:
        if command.negotiation_id != self.negotiation_id:
            return Rejected(reason="command negotiation does not match payment commitment")
        if command.kind == "reverse":
            return self._validate_reverse(command)
        if self.rate is None:
            return Rejected(reason="once payments support voluntary reverse only")
        return self.rate.validate(command)

    def _validate_reverse(self, command: LifecycleCommand) -> Rejected | None:
        if command.at is not None:
            return Rejected(reason="a voluntary reverse has no at")
        if set(command.payload) != {"part", "amount"}:
            return Rejected(reason="reverse requires exactly part and amount")
        part, amount = command.payload["part"], command.payload["amount"]
        if not isinstance(part, str) or len(part) > 2 or not part.isascii() or not part.isdecimal():
            return Rejected(reason="part must be a canonical decimal part reference")
        index = int(part)
        if str(index) != part or index >= len(self.data.mandate.parts):
            return Rejected(reason="unknown payment part")
        if (not isinstance(amount, str) or len(amount) > 38 or not amount.isascii() or not amount.isdecimal()
                or not 0 < int(amount) < 10**38 or str(int(amount)) != amount):
            return Rejected(reason="reverse amount must be positive minor-unit decimal text")
        authorities = self.data.mandate.parts[index].root.authorities.reverse
        if self.account not in {entry.root for entry in authorities}:
            return Rejected(reason="account has no reverse authority on this part")
        return None

    def command_event(self, command: LifecycleCommand) -> dict[str, Any]:
        if command.kind == "reverse":
            return {"kind": "reverse", "part": int(str(command.payload["part"])),
                    "amount": command.payload["amount"]}
        assert self.rate is not None
        return self.rate.event(command)

    def describe(self, command: LifecycleCommand, keys: OperationKeys) -> PaymentOperation:
        """The immutable descriptor of one per-part operation, for audit and journals."""

        if deal_stop(command):
            raise ValueError("deal stop expands into per-part stops through submit")
        refusal = self.validate(command)
        if refusal is not None:
            raise ValueError(refusal.reason)
        if (keys.negotiation_id, keys.operation_key) != (command.negotiation_id, command.operation_key):
            raise ValueError("operation keys do not match the command")
        return PaymentOperation.create(transaction=self.commitment_ref, account=self.account,
                                       part=str(command.payload["part"]), event=self.command_event(command), keys=keys)

    async def submit(self, command: LifecycleCommand, keys: OperationKeys) -> LifecycleOutcome:
        refusal = self.validate(command)
        if refusal is not None:
            return refusal
        if (keys.negotiation_id, keys.operation_key) != (command.negotiation_id, command.operation_key):
            return Rejected(reason="operation keys do not match the command")
        commands = self.rate.expand(command) if self.rate is not None else (command,)
        operations = tuple(self.describe(item, keys) for item in commands)
        # A rate deal's every monetary operation is recorded through the
        # caller's store before the first is sent; the same records and derived
        # keys recover a partially acknowledged deal stop. A once-only reverse
        # records when the caller supplies a store, and otherwise relies on the
        # authority's request_id_reused refusal of changed bytes.
        if self.rate is not None or keys.store is not None:
            refusal = await record_descriptors(operations, keys)
            if refusal is not None:
                return refusal
        if not deal_stop(command):
            return await asyncio.to_thread(self._send, command, operations[0])
        for item, operation in zip(commands, operations, strict=True):
            outcome = await asyncio.to_thread(self._send, item, operation)
            if not isinstance(outcome, Accepted):
                return outcome
        view = await self.read()
        if not isinstance(view.outcome, Accepted):
            return view.outcome
        records = [part.final_stop or part.pending_stop for part in view.parts]
        if any(record is None for record in records):
            return Unknown(reason="deal stop awaits a verified controlling stop for every rate part")
        return Accepted(records=[record for record in records if record is not None])

    def submit_now(self, command: LifecycleCommand, keys: OperationKeys) -> LifecycleOutcome:
        """Send a once-only mandate's reverse for a caller that holds no operation store.

        Such a caller resolves its own retries from the verified record, and the
        authority refuses changed bytes under one request identity. A rate
        deal's operations are recorded before I/O, so they go through ``submit``.
        """

        if self.rate is not None:
            return Rejected(reason="a rate deal's payment operations require the caller's durable operation store")
        refusal = self.validate(command)
        if refusal is not None:
            return refusal
        try:
            operation = self.describe(command, keys)
        except ValueError as exc:
            return Rejected(reason=str(exc))
        return self._send(command, operation)

    def _send(self, command: LifecycleCommand, operation: PaymentOperation) -> LifecycleOutcome:
        """Send one recorded operation and accept it only from the verified record."""

        try:
            stored = self.snapshots.submit(operation)
            # A POST response is not signed. No effect is accepted until read
            # returns the same operation in the verified authority record.
            after = self.snapshots.now(minimum_sequence=stored.sequence or 0)
            match = recorded_by(after, operation)
            if match is not None:
                return Accepted(records=[event for event in self.events(after.snapshot)
                                         if event.sequence == match.sequence and event.part == operation.part])
            if command.kind == "stop" and self.rate is not None:
                # The authority answers a stop of an already stopped part with
                # the winning stop; that satisfies this one only if no later.
                earlier = self.rate.earlier_stop(after, command, operation)
                if earlier is not None:
                    return Accepted(records=[earlier])
            return Unknown(reason="operation response is not yet in the verified authority record")
        except READ_FAILURES as exc:
            return classify_failure(exc, kind=command.kind, attempted=True, reread=self.snapshots.now)

    # Reads ----------------------------------------------------------------------

    def snapshot_now(self, *, minimum_sequence: int | None = None) -> SignedTransactionSnapshot:
        return self.snapshots.now(minimum_sequence=minimum_sequence)

    def events(self, snapshot: TransactionSnapshot) -> list[PaymentEvent]:
        """Project verified events without interpreting dispute remedies or delivery ends.

        In a once-only mandate a part's stop is the deal's payment end. Beside a
        rate part, a raw stop is only a request: the winning final stop, an
        equal-time winner included, lives in the rate parts' observations.
        """

        result = []
        once_only = self.rate is None
        reversed_so_far = {part.part: 0 for part in snapshot.parts}
        for wrapped in snapshot.events:
            stored = wrapped.root
            event = stored.event
            sequence = stored.sequence
            assert sequence is not None
            kind = stored.event.kind.value if isinstance(stored, StoredEvent) else stored.event.kind
            if kind not in {"start", "stop", "reverse", "extend", "lift"}:
                raise PaymentsProtocolError("unsupported payment authority event")
            actor = stored.account.root if isinstance(stored, StoredEvent) else "terms"
            payload = stored.event.payload if isinstance(stored, StoredEvent) else None
            case = payload.get("case_ref") if isinstance(payload, dict) else None
            if case is not None and (not isinstance(case, str) or not case):
                raise PaymentsProtocolError("invalid payment event case reference")
            for part in snapshot.parts:
                if event.part is not None and event.part != part.part:
                    continue
                part_kind = self.data.mandate.parts[part.part].root.kind
                if event.part is None:
                    if kind == "start" and part_kind != "rate":
                        continue
                    if kind == "stop" and not once_only and not any(
                            stop is not None and stop.sequence == sequence for stop in (part.stop, part.pendingStop)):
                        continue
                amount = stored.event.amount.root if isinstance(stored, StoredEvent) and stored.event.amount else None
                if kind == "reverse" and part_kind == "once":
                    # A whole-part reverse may omit its amount. Once parts
                    # cannot earn again, so the signed cumulative reversal is
                    # the remaining movement after earlier recorded reverses.
                    if amount is None:
                        amount = str(int(part.reversed.root) - reversed_so_far[part.part])
                        if amount == "0":
                            continue
                    reversed_so_far[part.part] += int(amount)
                projected = "stop_request" if kind == "stop" and not once_only else kind
                result.append(PaymentEvent(
                    negotiation_id=self.negotiation_id, commitment_ref=self.commitment_ref,
                    part=str(part.part), kind=cast(Any, projected), actor=actor, at=stored.receivedAt,
                    amount=amount, cause=("terms" if actor == "terms" else
                                          "payee" if actor == self.data.mandate.to.root else
                                          "payer" if actor == self.data.mandate.from_.root else "authority"),
                    case_ref=case,
                    extension_ref=(str(sequence) if kind == "extend" else
                                   str(stored.event.ref) if kind == "lift" and isinstance(stored, StoredEvent)
                                   else None),
                    sequence=sequence, authority_record_ref=f"{self.commitment_ref}:events:{sequence}",
                ))
        return result

    def _view(self, signed: SignedTransactionSnapshot) -> AuthorityView:
        snapshot = signed.snapshot
        events = self.events(snapshot)
        opened = {(event.part, event.extension_ref): event for event in events if event.kind == "extend"}
        extensions = []
        for part in snapshot.parts:
            for extension in part.extensions:
                source = opened.get((str(part.part), str(extension.ref)))
                if source is None or source.case_ref is None:
                    raise PaymentsProtocolError("open extension has no case-bound authority event")
                extensions.append(OpenExtension(
                    part=str(part.part), extension_ref=str(extension.ref),
                    case_ref=source.case_ref, until=extension.until,
                ))
        payouts = {str(part.part): snapshot.observedAt if (
            part.held.root == "0" and part.status.value in {"released", "reversed", "settled"}
        ) else None for part in snapshot.parts}
        if self.rate is None:
            # A refund or discount is not a delivery end. The seller's end
            # journal owns physical state; once commitments have no payment deadline.
            return AuthorityView(outcome=Accepted(), state="running", events=events,
                                 extensions=extensions, payouts=payouts)
        observations = self.rate.observations(signed)
        state, deadline = self.rate.state(observations)
        return AuthorityView(outcome=Accepted(), state=cast(Any, state), events=events, extensions=extensions,
                             payouts=payouts, parts=observations, deadline=deadline)

    async def read(self) -> AuthorityView:
        try:
            return self._view(await asyncio.to_thread(self.snapshots.now))
        except READ_FAILURES as exc:
            return AuthorityView(outcome=classify_failure(exc, kind="read", attempted=False,
                                                          reread=self.snapshots.now))

    # Delivery -------------------------------------------------------------------

    async def _commitment_matches(self, evidence: DeliveryEvidence) -> bool:
        if (evidence.negotiation_id, evidence.commitment_ref) != (self.negotiation_id, self.commitment_ref):
            return False
        return isinstance((await self.read()).outcome, Accepted)

    async def authorize(
        self, phase: DeliveryPhase, evidence: DeliveryEvidence, billing: JournaledBillingStart | None = None,
    ) -> DeliveryAuthorization:
        if self.rate is None:
            return await self._once.authorize(phase, evidence)
        keys = OperationKeys(self.negotiation_id, billing.operation_key) if billing is not None else None
        return await self.rate.authorize(
            phase, evidence, billing,
            describe=lambda command: self.describe(command, cast(OperationKeys, keys)),
            read=lambda: asyncio.to_thread(self.snapshots.now),
        )

    def billing_operations(self, keys: OperationKeys, evidence: DeliveryEvidence) -> tuple[PaymentOperation, ...]:
        """The descriptors one billing start records, in the order it sends them."""

        if self.rate is None:
            return ()
        return tuple(self.describe(command, keys) for command in self.rate.billing_commands(keys.operation_key, evidence))

    async def start_billing(self, keys: OperationKeys, evidence: DeliveryEvidence) -> BillingStartResult:
        """Start every rate part under end service's one billing-start identity.

        A once-only mandate has nothing to start: after its commitment and the
        activation evidence are verified, its billing start is a no-op.
        """

        if self.rate is None:
            return await self._once.start_billing(keys, evidence)
        if keys.negotiation_id != self.negotiation_id:
            return BillingStartResult(outcome=Rejected(reason="operation keys name another deal"))
        try:
            commands = self.rate.billing_commands(keys.operation_key, evidence)
            operations = tuple(self.describe(command, keys) for command in commands)
        except (ValueError, TypeError) as exc:
            return BillingStartResult(outcome=Rejected(reason=str(exc)))
        refusal = await record_descriptors(operations, keys)
        if refusal is not None:
            return BillingStartResult(outcome=refusal)
        records: list[PaymentEvent | DisputeEvent] = []
        for command, operation in zip(commands, operations, strict=True):
            result = await asyncio.to_thread(self._send, command, operation)
            if not isinstance(result, Accepted):
                return BillingStartResult(outcome=result)
            records.extend(result.records)
        return BillingStartResult(outcome=Accepted(records=records))


__all__ = [
    "ClientForAccount",
    "LifecyclePaymentsClient",
    "PaymentAdapter",
    "pinned_snapshot_verifier",
]
