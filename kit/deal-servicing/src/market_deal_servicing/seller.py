"""Seller lifecycle operations over committed bindings and durable end intents."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

from market_deal_lifecycle.adapters import (
    DisputeAdapter, DisputeAdapterTable, DisputeBinding,
    PaymentAdapter, PaymentAdapterTable, PaymentBinding, PaymentSelector,
    submit_dispute, submit_payment,
)
from market_deal_lifecycle.terms import DisputeAuthority
from market_deal_lifecycle_contracts.models import (
    Accepted, AuthorityView, DealPage, DealSummary, LifecycleCommand, LifecycleOutcome,
    LifecycleRead, LifecycleState, ListDealsRequest, Pending, Reference, Rejected, WireModel,
)
from market_identity import Identity, canonical_json
from pydantic import Field, JsonValue

from .end import SQLiteOperationStore
from .evidence import transaction
from .journal import Classification, EndSession, FinalRequest, atomic, create_schema
from .watch import DealWatch, WatchSession


class SellerDeal(WireModel):
    """Immutable projection supplied from the verified committed Agreement."""

    negotiation_id: Reference
    commitment_ref: Reference
    domain: Reference
    buyer: Identity
    payment: PaymentSelector
    dispute: DisputeAuthority | None = None
    entitlements: dict[str, JsonValue] = Field(default_factory=dict)
    once_only: bool = False

    @property
    def dispute_binding(self) -> DisputeBinding | None:
        return DisputeBinding(self.negotiation_id, self.commitment_ref, self.dispute) if self.dispute else None


class SellerSession:
    def __init__(self, conn):
        self.conn = conn

    def register(self, deal: SellerDeal) -> None:
        """Register in the transaction that records the verified commitment."""
        with atomic(self.conn):
            delivery = EndSession(self.conn).read(deal.negotiation_id)
            if delivery.commitment_ref != deal.commitment_ref:
                raise ValueError("seller registration differs from delivery commitment")
            old = self.conn.execute(
                "SELECT deal FROM servicing_seller_deals WHERE negotiation_id=?", (deal.negotiation_id,),
            ).fetchone()
            if old:
                if SellerDeal.model_validate_json(old[0]) != deal:
                    raise ValueError("seller registration changes committed metadata")
                return
            self.conn.execute(
                "INSERT INTO servicing_seller_deals VALUES (?,?)",
                (deal.negotiation_id, deal.model_dump_json()),
            )

    def read(self, negotiation_id: str) -> SellerDeal:
        row = self.conn.execute(
            "SELECT deal FROM servicing_seller_deals WHERE negotiation_id=?", (negotiation_id,),
        ).fetchone()
        if row is None:
            raise KeyError(negotiation_id)
        return SellerDeal.model_validate_json(row[0])

    def page(self, request: ListDealsRequest, *, committed_only: bool = True) -> tuple[list[SellerDeal], str | None]:
        # The opaque token is the last immutable ID, not an offset into a mutable set.
        after = request.continuation or ""
        rows = self.conn.execute(
            """SELECT s.deal FROM servicing_seller_deals s
               JOIN servicing_delivery d USING (negotiation_id)
               WHERE s.negotiation_id > ? COLLATE BINARY
                 AND (? = 0 OR json_extract(d.record, '$.committed_at') IS NOT NULL)
               ORDER BY s.negotiation_id COLLATE BINARY LIMIT ?""",
            (after, int(committed_only), request.limit + 1),
        ).fetchall()
        deals = [SellerDeal.model_validate_json(row[0]) for row in rows[:request.limit]]
        return deals, deals[-1].negotiation_id if len(rows) > request.limit else None


WatchFactory = Callable[[SellerDeal, PaymentAdapter | None, DisputeAdapter | None], DealWatch]


class SellerServicing:
    def __init__(
        self, path: str | Path, *, payments: PaymentAdapterTable, disputes: DisputeAdapterTable,
        credential_available: Callable[[DisputeAuthority], bool], watch_factory: WatchFactory,
        clock: Callable[[], int],
    ):
        self.path = Path(path)
        self.payments = payments
        self.disputes = disputes
        self.credential_available = credential_available
        self.watch_factory = watch_factory
        self.clock = clock
        self.operations = SQLiteOperationStore(path)
        with transaction(self.path) as conn:
            create_schema(conn)

    def _deal(self, negotiation_id: str) -> SellerDeal:
        with transaction(self.path) as conn:
            return SellerSession(conn).read(negotiation_id)

    def _watch(self, deal: SellerDeal) -> DealWatch:
        payment = self.payments.resolve(PaymentBinding(deal.negotiation_id, deal.payment))
        binding = deal.dispute_binding
        dispute = self.disputes.resolve(binding) if (
            binding is not None and self.credential_available(binding.authority)
        ) else None
        watch = self.watch_factory(deal, payment, dispute)
        if (
            watch.negotiation_id != deal.negotiation_id or watch.commitment_ref != deal.commitment_ref
            or watch.binding != binding or watch.payment is not payment or watch.dispute is not dispute
            or watch.path.resolve() != self.path.resolve()
        ):
            raise ValueError("watch factory changed the committed bindings or persistence")
        return watch

    def _authority(self, deal: SellerDeal, watch: DealWatch) -> AuthorityView:
        with transaction(self.path) as conn:
            session = WatchSession(conn)
            payment = session.view(deal.negotiation_id, watch.payment_record)
            dispute = session.view(deal.negotiation_id, watch.dispute_record) if watch.dispute_record else None
        missing = deal.dispute is not None and not self.credential_available(deal.dispute)
        if missing:
            outcome: LifecycleOutcome = Rejected(reason="repair required: Agreement authority credential is missing")
        elif watch.payment is None:
            outcome = Rejected(reason=f"{deal.payment.mechanism} has no lifecycle adapter")
        else:
            views = [view for view in (payment, dispute) if view is not None]
            outcome = next((view.outcome for view in views if not isinstance(view.outcome, Accepted)), Accepted())
            if payment is None:
                outcome = Pending(reason="payment authority has not been observed")
        return AuthorityView(
            outcome=outcome, state="repair_required" if missing else payment.state if payment else None,
            events=payment.events if payment else [], disputes=dispute.disputes if dispute else [],
            cases=dispute.cases if dispute else [], extensions=payment.extensions if payment else [],
            deadline=payment.deadline if payment else None,
        )

    async def watch(self, negotiation_id: str):
        deal = self._deal(negotiation_id)
        watch = self._watch(deal)
        await self.dispatch_filings(negotiation_id)
        async for item in watch.watch():
            yield item

    def delivery_read(self, negotiation_id: str) -> LifecycleRead:
        """Return kept delivery evidence even when either authority is unreachable."""
        deal = self._deal(negotiation_id)
        authority = self._authority(deal, self._watch(deal))
        with transaction(self.path) as conn:
            delivery = EndSession(conn).view(negotiation_id)
        return LifecycleRead(
            negotiation_id=negotiation_id, commitment_ref=deal.commitment_ref,
            authority=authority, delivery=delivery,
        )

    async def read(self, negotiation_id: str) -> LifecycleRead:
        deal = self._deal(negotiation_id)
        watch = self._watch(deal)
        await watch.poll()
        authority = self._authority(deal, watch)
        with transaction(self.path) as conn:
            delivery = EndSession(conn).view(negotiation_id)
        return LifecycleRead(
            negotiation_id=negotiation_id, commitment_ref=deal.commitment_ref,
            authority=authority, delivery=delivery,
        )

    async def list(self, request: ListDealsRequest = ListDealsRequest()) -> DealPage:
        """Bounded local views; the registered watch step refreshes authority state."""
        with transaction(self.path) as conn:
            deals, continuation = SellerSession(conn).page(request)
        summaries = []
        for deal in deals:
            authority = self._authority(deal, self._watch(deal))
            with transaction(self.path) as conn:
                end = EndSession(conn)
                delivery = end.read(deal.negotiation_id)
                selected = end.selected_end(deal.negotiation_id)
            state: LifecycleState = authority.state or "unstarted"
            if deal.once_only:
                state = "running"
            if selected:
                state = "ended" if delivery.progress == "released" else "ending"
            if authority.state == "repair_required" or delivery.progress == "repair_required":
                state = "repair_required"
            summaries.append(DealSummary(
                negotiation_id=deal.negotiation_id, commitment_ref=deal.commitment_ref,
                domain=deal.domain, mechanism=deal.payment.mechanism, entitlements=deal.entitlements,
                state=state, deadline=selected.ended_at if selected else authority.deadline or delivery.term_end,
                has_open_extension=bool(authority.extensions),
                open_cases=[case.case_ref for case in authority.cases if case.state != "closed"],
            ))
        return DealPage(deals=summaries, continuation=continuation)

    async def submit(
        self, command: LifecycleCommand, *, actor: Identity, reason: str | None = None,
    ) -> LifecycleOutcome:
        deal = self._deal(command.negotiation_id)
        if command.kind == "delivery_end":
            if not reason or not reason.strip():
                return Rejected(reason="an operator delivery end requires its administrator reason")
            return await self._operator_end(command, actor=actor, reason=reason)
        if command.kind in {"dispute", "append"}:
            binding = deal.dispute_binding
            if binding is None:
                return Rejected(reason=f"{deal.payment.mechanism} has no Agreement dispute authority")
            if not self.credential_available(binding.authority):
                return Rejected(reason="repair required: Agreement authority credential is missing")
            return await submit_dispute(command, binding, self.disputes, self.operations)
        return await submit_payment(
            command, PaymentBinding(deal.negotiation_id, deal.payment), self.payments, self.operations,
        )

    async def _operator_end(
        self, command: LifecycleCommand, *, actor: Identity, reason: str,
    ) -> LifecycleOutcome:
        # Bind the administrator and reason too, so retries cannot rewrite attribution.
        digest = hashlib.sha256(canonical_json({
            "command": command.model_dump(mode="json"), "actor": actor.model_dump(mode="json"), "reason": reason,
        })).hexdigest()
        now = self.clock()
        with transaction(self.path) as conn, atomic(conn):
            end = EndSession(conn)
            if not end.check_and_record(command.negotiation_id, command.operation_key, digest):
                return Rejected(reason="operation key retry changes content")
            prior = next((item for item in end.requests(command.negotiation_id)
                          if item.source_ref == "operator:" + command.operation_key), None)
            if prior is None:
                if command.at is not None or command.payload:
                    return Rejected(reason="operator end uses durable receipt time, without at or payload")
                request = FinalRequest(
                    negotiation_id=command.negotiation_id, source_ref="operator:" + command.operation_key,
                    ended_at=now, observed_at=now, actor=actor, cause="operator_end", source="administrator",
                    administrator_reason=reason, evidence_refs=["operator:" + command.operation_key],
                )
                end.record_end(
                    request, now=now,
                    classification=Classification(kind="unentitled_withdrawal", evidence_refs=request.evidence_refs),
                    filing_intent=end.failure_filing(
                        request, now=now, delivered=end.read(command.negotiation_id).available_at is not None,
                    ),
                )
        return await self.dispatch_filings(command.negotiation_id)

    async def dispatch_filings(self, negotiation_id: str) -> LifecycleOutcome:
        deal = self._deal(negotiation_id)
        binding = deal.dispute_binding
        if binding is None:
            return Rejected(reason=f"{deal.payment.mechanism} has no Agreement dispute authority")
        if not self.credential_available(binding.authority):
            return Rejected(reason="repair required: Agreement authority credential is missing")
        with transaction(self.path) as conn:
            filings = [intent for intent in EndSession(conn).intents(negotiation_id) if intent.kind == "filing"]
        outcome: LifecycleOutcome = Accepted()
        for intent in filings:
            if intent.state == "done":
                if intent.result is not None:
                    outcome = Accepted.model_validate(intent.result)
                continue
            if intent.not_before > self.clock():
                outcome = Pending(reason="delivery-end filing waits for Agreement start")
                continue
            command = LifecycleCommand.model_validate(intent.payload)
            # The neutral dispatcher builds the interface request and uses this same key
            # after unknown responses; only the authority may apply monetary effects.
            outcome = await submit_dispute(command, binding, self.disputes, self.operations)
            with transaction(self.path) as conn:
                EndSession(conn).acknowledge(
                    intent.intent_ref, outcome.model_dump(mode="json"),
                    state="done" if isinstance(outcome, Accepted) else "pending",
                )
        return outcome
