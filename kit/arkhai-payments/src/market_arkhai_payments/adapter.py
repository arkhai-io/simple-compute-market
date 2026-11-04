"""Once-only lifecycle adapter; signed authority reads resolve every write outcome."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Any, Literal, Protocol, cast

from market_deal_lifecycle.delivery import (
    BillingStartResult, DeliveryAuthorization, DeliveryEvidence, DeliveryPhase, OnceDeliveryPolicy,
)
from market_deal_lifecycle.operations import OperationKeys
from market_deal_lifecycle_contracts.models import (
    Accepted, AuthorityView, LifecycleCommand, LifecycleOutcome, OpenExtension,
    PaymentEvent, Pending, Rejected, Unknown,
)
from pydantic import ValidationError

from .agreement import PaymentSettlementData
from .errors import PaymentsAPIError, PaymentsError, PaymentsProtocolError, PaymentsTransportError
from .models import SignedTransactionSnapshot, StoredEvent, TransactionSnapshot
from .receipts import SnapshotVerifier, verify_snapshot
from .settlement_config import ArkhaiPaymentsConfig, ArkhaiPaymentsConfigurationError

class LifecyclePaymentsClient(Protocol):
    def __enter__(self) -> LifecyclePaymentsClient: ...
    def __exit__(self, *args: object) -> None: ...
    def get_transaction(self, transaction: str) -> SignedTransactionSnapshot: ...
    def submit_event(
        self, transaction: str, event: Mapping[str, Any], *, request_id: str,
    ) -> StoredEvent: ...


ClientForAccount = Callable[[str], LifecyclePaymentsClient]


def pinned_snapshot_verifier(
    agreement: Mapping[str, Any], data: PaymentSettlementData, config: ArkhaiPaymentsConfig,
) -> SnapshotVerifier:
    """Bind the shared snapshot verifier to the configured current service pin."""

    def verify(signed: SignedTransactionSnapshot, minimum_sequence: int) -> bool:
        trusted = config.service_identity
        return trusted is not None and verify_snapshot(
            signed, trusted, mandate=data.mandate, agreement_json=agreement,
            livemode=config.livemode, minimum_sequence=minimum_sequence,
        )

    return verify


class PaymentAdapter:
    """One accepted once-only commitment, with credentials and verification injected.

    The composition supplies its pinned snapshot verifier and durable cursor floor.
    No cached snapshot or command outcome is a payment ledger. Replays are resolved
    by the authority's signed events and stable per-part request identities.
    """

    supported_commands = frozenset({"reverse"})

    def __init__(
        self, agreement: Mapping[str, Any], data: PaymentSettlementData, *,
        account: str, client_for_owner: ClientForAccount, verify_snapshot: SnapshotVerifier,
        minimum_sequence: int = 0,
    ) -> None:
        data.require_bound_to(agreement)
        if any(part.root.kind != "once" for part in data.mandate.parts):
            raise ValueError("the hosted once adapter does not support rate parts")
        if minimum_sequence < 0:
            raise ValueError("minimum sequence must be nonnegative")
        self.negotiation_id = str(agreement["negotiation_id"])
        self.commitment_ref = data.transaction_id
        self.data = data
        self.account = account
        self._client_for_owner = client_for_owner
        self._verify = verify_snapshot
        self._minimum_sequence = minimum_sequence
        self._delivery = OnceDeliveryPolicy(self._commitment_matches)

    def validate(self, command: LifecycleCommand) -> Rejected | None:
        if command.negotiation_id != self.negotiation_id:
            return Rejected(reason="command negotiation does not match payment commitment")
        if command.kind != "reverse":
            return Rejected(reason="once payments support voluntary reverse only")
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

    def snapshot_now(self, *, minimum_sequence: int | None = None) -> SignedTransactionSnapshot:
        with self._client_for_owner(self.account) as client:
            signed = client.get_transaction(self.commitment_ref)
        floor = max(self._minimum_sequence, minimum_sequence or 0)
        if not self._verify(signed, floor):
            raise PaymentsProtocolError("payments snapshot does not prove this commitment")
        snapshot = signed.snapshot
        if snapshot.transaction.root != self.commitment_ref:
            raise PaymentsProtocolError("payments snapshot names another commitment")
        if snapshot.latestEventSequence is None or snapshot.latestEventSequence < floor:
            raise PaymentsProtocolError("payments snapshot has no current event sequence")
        if sorted(part.part for part in snapshot.parts) != list(range(len(self.data.mandate.parts))):
            raise PaymentsProtocolError("payments snapshot has a different part population")
        sequences = [event.root.sequence for event in snapshot.events]
        if (len(sequences) != snapshot.latestEventSequence
                or any(sequence != index for index, sequence in enumerate(sequences, 1))):
            raise PaymentsProtocolError("payments snapshot has incomplete or unordered events")
        return signed

    def events(self, snapshot: TransactionSnapshot) -> list[PaymentEvent]:
        """Project verified events without interpreting dispute remedies or delivery ends."""
        result = []
        reversed_so_far = {part.part: 0 for part in snapshot.parts}
        for wrapped in snapshot.events:
            stored = wrapped.root
            event = stored.event
            sequence = stored.sequence
            assert sequence is not None
            actor = stored.account.root if isinstance(stored, StoredEvent) else "terms"
            payload = stored.event.payload if isinstance(stored, StoredEvent) else None
            case = payload.get("case_ref") if isinstance(payload, dict) else None
            if case is not None and (not isinstance(case, str) or not case):
                raise PaymentsProtocolError("invalid payment event case reference")
            for part in snapshot.parts:
                if event.part is not None and event.part != part.part:
                    continue
                kind = stored.event.kind.value if isinstance(stored, StoredEvent) else stored.event.kind
                if kind not in {"reverse", "extend", "lift", "stop"}:
                    raise PaymentsProtocolError("unsupported once payment event")
                amount = stored.event.amount.root if isinstance(stored, StoredEvent) and stored.event.amount else None
                if kind == "reverse":
                    # A legacy whole-part reverse omits its amount. Once parts
                    # cannot earn again, so the signed cumulative reversal is
                    # the remaining movement after earlier recorded reverses.
                    if amount is None:
                        amount = str(int(part.reversed.root) - reversed_so_far[part.part])
                        if amount == "0":
                            continue
                    reversed_so_far[part.part] += int(amount)
                extension = None
                if kind == "extend":
                    extension = str(sequence)
                elif kind == "lift":
                    extension = str(stored.event.ref) if isinstance(stored, StoredEvent) else None
                result.append(PaymentEvent(
                    negotiation_id=self.negotiation_id, commitment_ref=self.commitment_ref,
                    part=str(part.part), kind=cast(Literal["reverse", "extend", "lift", "stop"], kind),
                    actor=actor, at=stored.receivedAt,
                    amount=amount, cause=("terms" if actor == "terms" else
                        "payee" if actor == self.data.mandate.to.root else
                        "payer" if actor == self.data.mandate.from_.root else "authority"),
                    case_ref=case, extension_ref=extension, sequence=sequence,
                    authority_record_ref=f"{self.commitment_ref}:events:{sequence}",
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
        # A refund or discount is not a delivery end. The seller's end journal
        # owns physical state; once commitments have no payment deadline.
        return AuthorityView(
            outcome=Accepted(), state="running", events=events, extensions=extensions,
            payouts={str(part.part): snapshot.observedAt if (
                part.held.root == "0" and part.status.value in {"released", "reversed", "settled"}
            ) else None for part in snapshot.parts},
        )

    async def read(self) -> AuthorityView:
        try:
            return self._view(await asyncio.to_thread(self.snapshot_now))
        except (PaymentsError, ArkhaiPaymentsConfigurationError, ValidationError) as exc:
            return AuthorityView(outcome=_failure(exc))

    async def submit(self, command: LifecycleCommand, keys: OperationKeys) -> LifecycleOutcome:
        refusal = self.validate(command)
        if refusal is not None:
            return refusal
        if (keys.negotiation_id, keys.operation_key) != (command.negotiation_id, command.operation_key):
            return Rejected(reason="operation keys do not match the command")
        return await asyncio.to_thread(self.submit_now, command, keys)

    def submit_now(self, command: LifecycleCommand, keys: OperationKeys) -> LifecycleOutcome:
        refusal = self.validate(command)
        if refusal is not None:
            return refusal
        if (keys.negotiation_id, keys.operation_key) != (command.negotiation_id, command.operation_key):
            return Rejected(reason="operation keys do not match the command")
        part = str(command.payload["part"])
        request_id = keys.part_event(part, "reverse")
        expected = {"kind": "reverse", "part": int(part), "amount": command.payload["amount"]}
        attempted = False
        try:
            before = self.snapshot_now()
            for wrapped in before.snapshot.events:
                prior = wrapped.root
                if isinstance(prior, StoredEvent) and prior.account.root == self.account and prior.requestId.root == request_id:
                    wire = prior.event.model_dump(mode="json", by_alias=True, exclude_none=True)
                    if wire != expected:
                        return Rejected(reason="operation key retry changes content")
                    return Accepted(records=[e for e in self.events(before.snapshot)
                                             if e.sequence == prior.sequence and e.part == part])
            attempted = True
            with self._client_for_owner(self.account) as client:
                stored = client.submit_event(self.commitment_ref, expected, request_id=request_id)
            # A POST response is not signed. No effect is accepted until read
            # returns the same operation in the verified authority record.
            after = self.snapshot_now(minimum_sequence=max(
                stored.sequence or 0, (before.snapshot.latestEventSequence or 0) + 1,
            ))
            matches = [event for event in after.snapshot.events
                       if isinstance(event.root, StoredEvent)
                       and event.root.account.root == self.account
                       and event.root.requestId.root == request_id
                       and event.root.event.model_dump(mode="json", by_alias=True, exclude_none=True) == expected]
            if not matches:
                return Unknown(reason="reverse response is not yet in the verified authority record")
            return Accepted(records=[e for e in self.events(after.snapshot)
                                     if e.sequence == matches[0].root.sequence and e.part == part])
        except (PaymentsError, ArkhaiPaymentsConfigurationError, ValidationError) as exc:
            if attempted and not isinstance(exc, PaymentsAPIError):
                return Unknown(reason=f"reverse requires verified read recovery: {exc}")
            return _failure(exc)

    async def _commitment_matches(self, evidence: DeliveryEvidence) -> bool:
        if (evidence.negotiation_id, evidence.commitment_ref) != (self.negotiation_id, self.commitment_ref):
            return False
        return isinstance((await self.read()).outcome, Accepted)

    async def authorize(self, phase: DeliveryPhase, evidence: DeliveryEvidence) -> DeliveryAuthorization:
        return await self._delivery.authorize(phase, evidence)

    async def start_billing(self, operation_key: str, evidence: DeliveryEvidence) -> BillingStartResult:
        return await self._delivery.start_billing(operation_key, evidence)


def _failure(exc: Exception) -> LifecycleOutcome:
    if isinstance(exc, PaymentsAPIError):
        if exc.code in {"transaction_not_found", "approval_pending"}:
            return Pending(reason=exc.code)
        if exc.status_code >= 500 or exc.status_code == 429:
            return Unknown(reason=str(exc))
    if isinstance(exc, PaymentsTransportError):
        return Unknown(reason=str(exc))
    return Rejected(reason=str(exc))
