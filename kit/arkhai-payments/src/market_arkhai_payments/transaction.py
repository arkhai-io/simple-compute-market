"""Parts every payment part kind shares: verified reads, descriptors and refusals.

The payments transaction adapter composes these with per-part-kind behaviour.
None of them holds authority state: each read is freshly verified against the
caller's durable sequence floor, and a rate deal's every monetary operation, or
a once reverse sent with a store, has its descriptor recorded through the
caller's own operation store before any I/O.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any, Protocol

from market_deal_lifecycle.operations import OperationKeys
from market_deal_lifecycle_contracts.models import LifecycleOutcome, Pending, Rejected, Unknown
from pydantic import ValidationError

from .errors import PaymentsAPIError, PaymentsError, PaymentsProtocolError, PaymentsTransportError
from .models import SignedTransactionSnapshot, StoredEvent
from .operations import PaymentOperation
from .receipts import SnapshotVerifier
from .settlement_config import ArkhaiPaymentsConfigurationError

# What a verified read or an authority call may raise; each is classified, never
# taken as an effect.
READ_FAILURES = (PaymentsError, ArkhaiPaymentsConfigurationError, ValidationError)


class LifecyclePaymentsClient(Protocol):
    def __enter__(self) -> LifecyclePaymentsClient: ...
    def __exit__(self, *args: object) -> None: ...
    def get_transaction(self, transaction: str) -> SignedTransactionSnapshot: ...
    def submit_event(
        self, transaction: str, event: Mapping[str, Any], *, request_id: str,
    ) -> StoredEvent: ...


ClientForAccount = Callable[[str], LifecyclePaymentsClient]


class VerifiedSnapshots:
    """Fresh, proven reads of one commitment under one account's credential."""

    def __init__(
        self, commitment_ref: str, part_count: int, *, account: str,
        client_for_owner: ClientForAccount, verify: SnapshotVerifier, minimum_sequence: int,
    ) -> None:
        if minimum_sequence < 0:
            raise ValueError("minimum sequence must be nonnegative")
        self.commitment_ref = commitment_ref
        self.part_count = part_count
        self.account = account
        self.client_for_owner = client_for_owner
        self.verify = verify
        self.minimum_sequence = minimum_sequence

    def now(self, *, minimum_sequence: int | None = None) -> SignedTransactionSnapshot:
        with self.client_for_owner(self.account) as client:
            signed = client.get_transaction(self.commitment_ref)
        floor = max(self.minimum_sequence, minimum_sequence or 0)
        if not self.verify(signed, floor):
            raise PaymentsProtocolError("payments snapshot does not prove this commitment")
        snapshot = signed.snapshot
        if snapshot.transaction.root != self.commitment_ref:
            raise PaymentsProtocolError("payments snapshot names another commitment")
        if snapshot.latestEventSequence is None or snapshot.latestEventSequence < floor:
            raise PaymentsProtocolError("payments snapshot has no current event sequence")
        if sorted(part.part for part in snapshot.parts) != list(range(self.part_count)):
            raise PaymentsProtocolError("payments snapshot has a different part population")
        sequences = [event.root.sequence for event in snapshot.events]
        if (len(sequences) != snapshot.latestEventSequence
                or any(sequence != index for index, sequence in enumerate(sequences, 1))):
            raise PaymentsProtocolError("payments snapshot has incomplete or unordered events")
        return signed

    def submit(self, operation: PaymentOperation) -> StoredEvent:
        with self.client_for_owner(self.account) as client:
            return client.submit_event(self.commitment_ref, operation.event, request_id=operation.request_id)


def recorded_by(snapshot: SignedTransactionSnapshot, operation: PaymentOperation) -> StoredEvent | None:
    """The verified authority event carrying exactly this operation, if any."""

    for wrapped in snapshot.snapshot.events:
        stored = wrapped.root
        if (isinstance(stored, StoredEvent) and stored.account.root == operation.account
                and stored.requestId.root == operation.request_id
                and stored.event.model_dump(mode="json", by_alias=True, exclude_none=True) == operation.event):
            return stored
    return None


async def record_descriptors(operations: Iterable[PaymentOperation], keys: OperationKeys) -> Rejected | None:
    """Persist every descriptor's digest through the caller's store before any I/O.

    Each digest is recorded under a key derived from the caller's operation key
    and the descriptor's part and kind, so a retry carrying changed content is
    refused here, before any authority call, and an identical retry reuses its
    request identity. The authority's ``request_id_reused`` is only the backstop.
    """

    if keys.store is None:
        return Rejected(reason="a monetary payment operation requires the caller's durable operation store")
    for operation in operations:
        recorded = await keys.store.check_and_record(
            keys.negotiation_id, keys.part_event(operation.part, f"{operation.kind}-descriptor"), operation.digest,
        )
        if not recorded:
            return Rejected(reason="operation key retry changes content")
    return None


def classify_failure(
    exc: Exception, *, kind: str, attempted: bool, reread: Callable[[], object],
) -> LifecycleOutcome:
    """Classify a failed read or command by the authority's structured code.

    Transport and server failures after an attempt stay unknown and retryable
    under the same identity. A conflict that names a repair, a matured hold or a
    stopped transaction is a definite refusal; a refusal of held funds is never
    read as partial success, so it is reconciled from a verified read.
    """

    if isinstance(exc, PaymentsAPIError):
        if exc.code in {"transaction_not_found", "approval_pending"}:
            return Pending(reason=exc.code)
        if exc.status_code >= 500 or exc.status_code == 429:
            return Unknown(reason=str(exc))
        if exc.status_code == 409:
            if exc.code in {"request_id_reused", "hold_not_reversible"}:
                return Rejected(reason=f"{exc.code}: repair required before another monetary operation")
            if exc.code == "insufficient_held_funds":
                try:
                    reread()
                except READ_FAILURES:
                    return Unknown(reason="insufficient_held_funds: verified read reconciliation is required")
                return Rejected(reason="insufficient_held_funds: reconcile recorded reversals before another delta")
            if exc.code == "hold_matured":
                return Rejected(reason="hold_matured: unrecoverable held-money shortfall; use the case path")
            if exc.code == "transaction_stopped" and kind == "start":
                return Rejected(reason="transaction_stopped: delivery must end; billing did not start")
        return Rejected(reason=str(exc))
    if attempted or isinstance(exc, PaymentsTransportError):
        return Unknown(reason=f"operation requires verified read recovery: {exc}")
    return Rejected(reason=str(exc))
