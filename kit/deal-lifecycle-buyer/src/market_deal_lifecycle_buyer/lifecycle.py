"""Buyer lifecycle dispatch over immutable Agreement bindings and injected ports."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from market_deal_lifecycle.adapters import (
    DisputeAdapterTable, DisputeBinding, PaymentAdapterTable, PaymentBinding,
    submit_dispute, submit_payment,
)
from market_deal_lifecycle.evidence import EvidenceStore
from market_deal_lifecycle.operations import OperationStore
from market_deal_lifecycle_contracts.models import (
    Accepted, AuthorityView, CommitMessage, EndDeliveryAcknowledgement, SignedEndDeliveryReceipt, EvidenceItem, HintMessage, LifecycleCommand,
    LifecycleOutcome, LifecycleRead, Rejected, SubmitResponse, Unknown,
)
from market_identity import Identity, canonical_json

from .ending import BuyerEndJournal, EndDeliveryProgress, end_delivery


class BuyerPeer(Protocol):
    async def commit(self, message: CommitMessage) -> SubmitResponse: ...
    async def hint(self, message: HintMessage) -> SubmitResponse: ...
    async def read(self, negotiation_id: str) -> LifecycleRead: ...
    async def end_delivery(self, negotiation_id: str, *, operation_key: str) -> EndDeliveryAcknowledgement: ...
    def end_receipt(self, negotiation_id: str, operation_key: str) -> SignedEndDeliveryReceipt: ...


@dataclass(frozen=True)
class BuyerDeal:
    """The composition projects this from the retained, committed Agreement."""

    negotiation_id: str
    commitment_ref: str
    payment: PaymentBinding
    dispute: DisputeBinding | None = None
    buyer: Identity | None = None
    seller: Identity | None = None

    def __post_init__(self) -> None:
        if not self.negotiation_id or not self.commitment_ref:
            raise ValueError("buyer deal requires negotiation and commitment references")
        if self.payment.negotiation_id != self.negotiation_id:
            raise ValueError("payment binding names another negotiation")
        if self.dispute is not None and (
            self.dispute.negotiation_id != self.negotiation_id
            or self.dispute.commitment_ref != self.commitment_ref
        ):
            raise ValueError("dispute binding names another deal")


HintObserver = Callable[[HintMessage, LifecycleOutcome], Awaitable[None]]


class BuyerLifecycle:
    def __init__(
        self, *, deal: Callable[[str], BuyerDeal], payments: PaymentAdapterTable,
        disputes: DisputeAdapterTable, operations: OperationStore, peer: BuyerPeer,
        observe_hint: HintObserver | None = None,
        end_journal: BuyerEndJournal | None = None, evidence: EvidenceStore | None = None,
        clock: Callable[[], int] = lambda: int(time.time()),
    ) -> None:
        self._resolve = deal
        self.payments = payments
        self.disputes = disputes
        self.operations = operations
        self.peer = peer
        self.observe_hint = observe_hint
        self.end_journal = end_journal
        self.evidence = evidence
        self.clock = clock

    def _deal(self, negotiation_id: str) -> BuyerDeal:
        deal = self._resolve(negotiation_id)
        if deal.negotiation_id != negotiation_id:
            raise ValueError("buyer resolver returned another negotiation")
        return deal

    async def end_delivery(self, negotiation_id: str) -> EndDeliveryProgress:
        return await end_delivery(self, negotiation_id)

    async def commit(self, message: CommitMessage) -> LifecycleOutcome:
        deal = self._deal(message.negotiation_id)
        if message.commitment_ref != deal.commitment_ref:
            return Rejected(reason="commitment differs from the accepted deal")
        return (await self.peer.commit(message)).outcome

    async def submit(self, command: LifecycleCommand) -> LifecycleOutcome:
        deal = self._deal(command.negotiation_id)
        if command.kind not in {"dispute", "delivery_end", "append"}:
            return await submit_payment(command, deal.payment, self.payments, self.operations)
        if deal.dispute is None:
            return Rejected(reason=f"{deal.payment.selector.mechanism} has no Agreement dispute authority")
        outcome = await submit_dispute(command, deal.dispute, self.disputes, self.operations)
        # Even an unknown filing may be recorded. A hint asks for a read, never
        # asserts that protection or a delivery ruling exists.
        if command.kind in {"dispute", "delivery_end"} and not isinstance(outcome, Rejected):
            await self._hint(command, outcome)
        return outcome

    async def append(
        self, negotiation_id: str, *, operation_key: str, case_ref: str, items: list[EvidenceItem],
    ) -> LifecycleOutcome:
        deal = self._deal(negotiation_id)
        adapter = self.disputes.resolve(deal.dispute) if deal.dispute is not None else None
        if adapter is None:
            return Rejected(reason="no dispute adapter for the Agreement authority")
        payload = adapter.build_append(case_ref, items)
        if isinstance(payload, Rejected):
            return payload
        return await self.submit(LifecycleCommand(
            negotiation_id=negotiation_id, kind="append", operation_key=operation_key, payload=payload,
        ))

    async def _hint(self, command: LifecycleCommand, outcome: LifecycleOutcome) -> None:
        # The peer key is stable across retries, separate from authority keys.
        operation_key = hashlib.sha256(canonical_json({
            "peer": "hint", "command": command.model_dump(mode="json"),
        })).hexdigest()
        message = HintMessage(
            negotiation_id=command.negotiation_id, operation_key=operation_key,
            payload={"operation_key": command.operation_key, "kind": command.kind},
        )
        try:
            hint = (await self.peer.hint(message)).outcome
        except Exception:
            # A courtesy transport cannot turn the authority's accepted filing
            # into an unknown filing. Its acknowledgement is observed separately.
            hint = Unknown(reason="storefront hint was not acknowledged")
        if self.observe_hint is not None:
            await self.observe_hint(message, hint)

    async def read(self, negotiation_id: str) -> LifecycleRead:
        deal = self._deal(negotiation_id)
        delivery = await self.peer.read(negotiation_id)
        if delivery.negotiation_id != negotiation_id or delivery.commitment_ref not in {None, deal.commitment_ref}:
            raise ValueError("storefront delivery read names another deal")
        payment = self.payments.resolve(deal.payment)
        if payment is None:
            authority = AuthorityView(outcome=Rejected(
                reason=f"{deal.payment.selector.mechanism} has no lifecycle adapter",
            ))
        else:
            financial = await payment.read()
            dispute = self.disputes.resolve(deal.dispute) if deal.dispute is not None else None
            cases = await dispute.read() if dispute is not None else AuthorityView(outcome=Rejected(
                reason="no dispute adapter for the Agreement authority",
            ))
            # Open protection comes only from payments, not a case's filing
            # answer. Dispute effects are observed here, never applied locally.
            outcome = next((view.outcome for view in (financial, cases)
                            if not isinstance(view.outcome, Accepted)), financial.outcome)
            authority = AuthorityView(
                outcome=outcome, state=financial.state, events=financial.events,
                extensions=financial.extensions, deadline=financial.deadline,
                disputes=cases.disputes, cases=cases.cases,
            )
        return LifecycleRead(
            negotiation_id=negotiation_id, commitment_ref=deal.commitment_ref,
            authority=authority, delivery=delivery.delivery,
        )
