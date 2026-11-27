"""Seller lifecycle operations over committed bindings and durable end intents."""

from __future__ import annotations

import asyncio
import base64
import builtins
import hashlib
import logging
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any, Literal, NamedTuple

from market_deal_lifecycle.adapters import (
    DisputeAdapter, DisputeAdapterTable, DisputeBinding,
    PaymentAdapter, PaymentAdapterTable, PaymentBinding,
    submit_dispute, submit_payment,
)
from market_deal_lifecycle.terms import DisputeAuthority
from market_deal_lifecycle_contracts.models import (
    Accepted, AuthorityView, DealPage, DealSummary, DeliveryView, EndingCode, EvidenceItem, LifecycleCommand,
    LifecycleOutcome, FilingProgress, LifecycleRead, LifecycleState, ListDealsRequest, Pending, Rejected,
    SubmitResponse, Unknown,
)
from market_identity import Identity, canonical_json

from .end import SQLiteOperationStore
from .evidence import EvidenceSession, in_transaction, transaction
from .journal import Classification, EndSession, FinalRequest, JournalIntent, PhysicalProgress, atomic, stable_ref
from .projection import SellerDeal, read_seller_deal
from .watch import DealWatch, WatchSession

logger = logging.getLogger(__name__)

InterruptionKind = Literal["preemption", "failure"]


class InterruptRefused(ValueError):
    """An administrator interruption refused before any notice, end or filing."""


class InterruptResult(NamedTuple):
    """The command an interruption sent, its outcome, and the deal's delivery."""

    kind: Literal["notice", "delivery_end"]
    outcome: LifecycleOutcome
    delivery: DeliveryView

    @property
    def settlement_action(self) -> Literal["notice_stop", "delivery_end_filing"]:
        return "notice_stop" if self.kind == "notice" else "delivery_end_filing"


def interrupt_command(
    deal: SellerDeal, *, operation_key: str, reason: str | None,
    interruption_kind: InterruptionKind | None,
) -> LifecycleCommand:
    """The lifecycle command an administrator interruption of ``deal`` sends.

    Preemption is the seller's notice, admitted only under the accepted payee
    entitlement; failure ends delivery and files ``delivery_end``. A rate deal
    must name its kind, since its cause decides who pays for the remaining
    period; a once-only deal defaults to failure, so a released caller, which
    sends no kind, gets the operator end it asks for. Both kinds need the
    administrator's reason. Every refusal is raised before anything is recorded
    or sent.
    """
    if interruption_kind is None:
        if not deal.once_only:
            raise InterruptRefused("rate interruption requires interruption_kind: preemption or failure")
        interruption_kind = "failure"
    if interruption_kind not in ("preemption", "failure"):
        raise InterruptRefused("unknown interruption kind")
    if interruption_kind == "preemption" and "payee" not in deal.entitlements:
        raise InterruptRefused("accepted option has no payee entitlement; preemption refused")
    if not reason or not reason.strip():
        raise InterruptRefused("administrator interruption requires a reason")
    return LifecycleCommand(
        negotiation_id=deal.negotiation_id, operation_key=operation_key,
        kind="notice" if interruption_kind == "preemption" else "delivery_end",
    )


def interrupt_operation_key(
    negotiation_id: str, *, actor: Identity, reason: str | None, interruption_kind: InterruptionKind | None,
) -> str:
    """The operation key of an interruption whose caller supplied none.

    It is derived from everything the request asserts, so a resent request is a
    retry of the same operation and a changed one is a new operation.
    """
    return hashlib.sha256(canonical_json({
        "negotiation_id": negotiation_id, "administrator": actor.model_dump(mode="json"),
        "reason": reason, "interruption_kind": interruption_kind,
    })).hexdigest()


class SellerSession:
    """Seller registrations over the caller's connection; it issues no DDL, so
    a read-only callback may share a database with an active ingress writer."""

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
        deal = read_seller_deal(self.conn, negotiation_id)
        if deal is None:
            raise KeyError(negotiation_id)
        return deal

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
        clock: Callable[[], int], missing_adapters: Mapping[str, str] | None = None,
    ):
        self.path = Path(path)
        self.payments = payments
        self.disputes = disputes
        self.credential_available = credential_available
        self.watch_factory = watch_factory
        self.clock = clock
        # By mechanism, the configuration that would compose the adapter of a
        # mechanism the storefront installs but whose configuration composed
        # none; a deal of that mechanism names it in its repair reason.
        self.missing_adapters = dict(missing_adapters or {})
        self.operations = SQLiteOperationStore(path)

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

    def _authority(
        self, deal: SellerDeal, watch: DealWatch, current: list[AuthorityView] | None = None,
    ) -> AuthorityView:
        return self._observed(deal, watch, current)[0]

    def _observed(
        self, deal: SellerDeal, watch: DealWatch, current: list[AuthorityView] | None = None,
    ) -> tuple[AuthorityView, bool]:
        """The deal's authority view, and whether it names a dispute authority
        of which no view is saved.

        A view is saved only from an accepted read, so with none the dispute
        authority's cases are unknown, not empty; what an accepted read assures
        is its adapter's to state. The view and that answer are read in one
        transaction, so a view saved meanwhile cannot leave them disagreeing.
        """
        with transaction(self.path) as conn:
            session = WatchSession(conn)
            payment = session.view(deal.negotiation_id, watch.payment_record)
            current_payment = session.observation(deal.negotiation_id, watch.payment_record)
            current_dispute = session.observation(deal.negotiation_id, watch.dispute_record) if watch.dispute_record else None
            dispute = session.view(deal.negotiation_id, watch.dispute_record) if watch.dispute_record else None
            repairs = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='servicing_respondent_repairs'",
            ).fetchone()
            repair = conn.execute(
                "SELECT reason FROM servicing_respondent_repairs WHERE commitment_ref=? LIMIT 1",
                (deal.commitment_ref,),
            ).fetchone() if repairs else None
        if current is not None:
            observations = iter(current)
            current_payment = next(observations, None) if watch.payment is not None else None
            current_dispute = next(observations, None) if watch.dispute is not None else None
        rejected = next((item.outcome for item in self._filings(deal.negotiation_id)
                         if isinstance(item.outcome, Rejected)), None)
        # A deal of a mechanism the storefront installs but whose configuration
        # composed no adapter cannot be serviced at all, so that is its repair
        # reason before any other.
        unserviceable = watch.payment is None and deal.payment.mechanism in self.missing_adapters
        missing = deal.dispute is not None and not self.credential_available(deal.dispute)
        if unserviceable:
            outcome: LifecycleOutcome = Rejected(reason=self._unserviceable_reason(deal))
        elif missing:
            outcome = Rejected(reason="repair required: Agreement authority credential is missing")
        elif repair:
            outcome = Rejected(reason="repair required: respondent case: " + repair[0])
        elif rejected is not None:
            outcome = Rejected(reason="repair required: " + rejected.reason.removeprefix("repair required: "))
        elif watch.payment is None:
            outcome = Rejected(reason=f"{deal.payment.mechanism} has no lifecycle adapter")
        else:
            required = [current_payment] + ([current_dispute] if deal.dispute else [])
            outcome = next(
                (view.outcome for view in required if view is not None and not isinstance(view.outcome, Accepted)),
                Pending(reason="required authority has not been observed") if None in required else Accepted(),
            )
        return AuthorityView(
            outcome=outcome,
            state=(
                "repair_required" if unserviceable or missing or repair or rejected is not None
                else payment.state if payment else None
            ),
            payouts=payment.payouts if payment else None,
            events=payment.events if payment else [], parts=payment.parts if payment else [],
            disputes=dispute.disputes if dispute else [],
            cases=dispute.cases if dispute else [], extensions=payment.extensions if payment else [],
            deadline=payment.deadline if payment else None,
        ), watch.dispute_record is not None and dispute is None

    def _unserviceable_reason(self, deal: SellerDeal) -> str:
        mechanism = deal.payment.mechanism
        return (
            f"repair required: {mechanism} has no lifecycle adapter; "
            f"configure {self.missing_adapters[mechanism]}"
        )

    def unserviceable(self) -> builtins.list[tuple[str, str]]:
        """Each open deal of a mechanism named in ``missing_adapters`` that has
        no adapter composed, with its repair reason.

        A deal is open until the seller list's rule would call it ended: a
        recorded end, its resource proven released, nothing outstanding at
        either authority in its saved views and every filing of its own
        answered (``_outstanding``). With no adapter
        nothing observes its payment again, so a released deal whose part last
        showed no stop stays reported until the adapter is restored; one whose
        dispute authority has no saved view stays reported until one is saved.
        Every registered deal is read, committed or not, since an uncommitted
        one still holds capacity a storefront must end.
        """
        found: builtins.list[tuple[str, str]] = []
        continuation: str | None = None
        while True:
            with transaction(self.path) as conn:
                deals, continuation = SellerSession(conn).page(
                    ListDealsRequest(limit=100, continuation=continuation), committed_only=False,
                )
            for deal in deals:
                if deal.payment.mechanism not in self.missing_adapters:
                    continue
                if self.payments.resolve(PaymentBinding(deal.negotiation_id, deal.payment)) is not None:
                    continue
                if not self._ended(deal):
                    found.append((deal.negotiation_id, self._unserviceable_reason(deal)))
            if continuation is None:
                return found

    def _ended(self, deal: SellerDeal) -> bool:
        """Whether the seller list's rule calls the deal ended, from its saved views.

        A deal whose views cannot be read is not shown ended, so it stays
        reported rather than failing the report.
        """
        with transaction(self.path) as conn:
            end = EndSession(conn)
            selected = end.selected_end(deal.negotiation_id)
            progress = end.read(deal.negotiation_id).progress
        if selected is None:
            return False
        try:
            authority, unobserved = self._observed(deal, self._watch(deal))
        except Exception:
            logger.exception("unserviceable deal %s: its authority views cannot be read", deal.negotiation_id)
            return False
        open_cases = [case.case_ref for case in authority.cases if case.state != "closed"]
        return not self._outstanding(
            deal, authority, progress, open_cases, dispute_unobserved=unobserved,
            filings=self._filings(deal.negotiation_id),
        )

    async def watch(self, negotiation_id: str):
        deal = await asyncio.to_thread(self._deal, negotiation_id)
        watch = await asyncio.to_thread(self._watch, deal)
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
            authority=authority, delivery=delivery, filings=self._filings(negotiation_id),
        )

    async def read(self, negotiation_id: str) -> LifecycleRead:
        deal = await asyncio.to_thread(self._deal, negotiation_id)
        watch = await asyncio.to_thread(self._watch, deal)
        views, _ = await watch.poll()
        authority = await asyncio.to_thread(self._authority, deal, watch, views)
        delivery = await in_transaction(self.path, lambda conn: EndSession(conn).view(negotiation_id))
        filings = await asyncio.to_thread(self._filings, negotiation_id)
        return LifecycleRead(
            negotiation_id=negotiation_id, commitment_ref=deal.commitment_ref,
            authority=authority, delivery=delivery, filings=filings,
        )

    async def list(self, request: ListDealsRequest = ListDealsRequest()) -> DealPage:
        """Bounded local views; the registered watch step refreshes authority state."""
        return await asyncio.to_thread(self._list, request)

    def _list(self, request: ListDealsRequest) -> DealPage:
        with transaction(self.path) as conn:
            deals, continuation = SellerSession(conn).page(request)
        summaries = []
        for deal in deals:
            authority, unobserved = self._observed(deal, self._watch(deal))
            with transaction(self.path) as conn:
                end = EndSession(conn)
                delivery = end.read(deal.negotiation_id)
                selected = end.selected_end(deal.negotiation_id)
            open_cases = [case.case_ref for case in authority.cases if case.state != "closed"]
            filings = self._filings(deal.negotiation_id)
            state: LifecycleState = authority.state or "unstarted"
            ending: list[EndingCode] = []
            if deal.once_only:
                state = "running"
            if selected:
                ending = self._outstanding(
                    deal, authority, delivery.progress, open_cases, dispute_unobserved=unobserved, filings=filings,
                )
                state = "ending" if ending else "ended"
            if authority.state == "repair_required" or delivery.progress == "repair_required":
                state, ending = "repair_required", []
            summaries.append(DealSummary(
                negotiation_id=deal.negotiation_id, commitment_ref=deal.commitment_ref,
                domain=deal.domain, mechanism=deal.payment.mechanism, entitlements=deal.entitlements,
                state=state, ending=ending,
                deadline=selected.ended_at if selected else authority.deadline or delivery.term_end,
                parts=authority.parts, has_open_extension=bool(authority.extensions),
                open_cases=open_cases, filings=filings,
            ))
        return DealPage(deals=summaries, continuation=continuation)

    def _outstanding(
        self, deal: SellerDeal, authority: AuthorityView, progress: PhysicalProgress,
        open_cases: builtins.list[str], *, dispute_unobserved: bool,
        filings: builtins.list[FilingProgress],
    ) -> builtins.list[EndingCode]:
        """What still keeps a deal with a recorded end from being ended.

        A recorded end is physical and local; the deal is ended only once its
        resource is proven released, the payment authority shows every part
        stopped or past its end, so nothing more can bill, and the dispute
        authority's saved view shows no open case. An open case read later
        makes it ending again.

        A deal that is not once-only bills through rate parts, and the payment
        authority's view of it lists every one, started or not; a view listing
        none, or no view yet saved, verifies no stop, so its payment is still
        running. A once-only deal has no rate part to stop.

        A deal naming a dispute authority of which no view is saved
        (``dispute_unobserved``) has no case known closed, so it is not ended
        until a view of that authority is saved.

        Every journaled filing is the deal's own ``delivery_end``. One the
        authority has neither accepted nor rejected — unsent, waiting for the
        Agreement's start, pending or of unknown outcome — may yet open a case
        that no saved view shows, so the deal is not ended until it is
        answered. A rejected filing shows repair required instead.
        """
        now = self.clock()
        ending: builtins.list[EndingCode] = []
        if progress != "released":
            ending.append("release_pending")
        if (not deal.once_only and not authority.parts) or any(
            part.final_stop is None and (part.end_at is None or part.end_at > now)
            for part in authority.parts
        ):
            ending.append("payment_running")
        if open_cases:
            ending.append("case_open")
        if dispute_unobserved:
            ending.append("case_unobserved")
        if any(not isinstance(filing.outcome, (Accepted, Rejected)) for filing in filings):
            ending.append("filing_unanswered")
        return ending

    async def submit(
        self, command: LifecycleCommand, *, actor: Identity, reason: str | None = None,
    ) -> LifecycleOutcome:
        deal = await asyncio.to_thread(self._deal, command.negotiation_id)
        if command.kind == "notice" and "payee" not in deal.entitlements:
            return Rejected(reason="accepted option has no payee entitlement; actual seller non-delivery uses delivery_end")
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

    async def interrupt(
        self, negotiation_id: str, *, actor: Identity, reason: str,
        physical: Callable[[str], Awaitable[Any]],
        operation_key: str | None = None, interruption_kind: InterruptionKind | None = None,
        dry_run: bool = False,
    ) -> InterruptResult:
        """Carry out an administrator interruption as ``interrupt_command`` classifies it.

        ``physical`` drives the deal's physical end, normally end service's
        ``drive_physical``. A dry run classifies and records nothing. A
        classification refusal raises ``InterruptRefused`` before any effect; a
        same-key retry changing the administrator or reason raises the evidence
        store's ``ValueError``, and an unknown deal ``KeyError``.
        """
        deal = await asyncio.to_thread(self._deal, negotiation_id)
        key = operation_key or interrupt_operation_key(
            negotiation_id, actor=actor, reason=reason, interruption_kind=interruption_kind,
        )
        command = interrupt_command(deal, operation_key=key, reason=reason, interruption_kind=interruption_kind)
        if dry_run:
            return await self._interrupted(command, Pending(reason="dry run; no interruption submitted"))
        # The administrator's attribution is kept for a notice as for a failure.
        # Its evidence ID is the operation's, so a same-key retry changing the
        # author or reason is refused here.
        evidence = EvidenceItem(
            evidence_id="administrator-interrupt:" + key,
            kind="administrator_interrupt", classification="seller_assertion",
            recorded_at=self.clock(), body=base64.b64encode(canonical_json({
                "command": command.model_dump(mode="json"),
                "administrator": actor.model_dump(mode="json"), "reason": reason,
            })),
        )
        await in_transaction(self.path, lambda conn: EvidenceSession(conn).put(negotiation_id, evidence))
        if command.kind == "notice":
            # Only the authority's verified stop, read by the watch, ends delivery.
            return await self._interrupted(command, await self.submit(command, actor=actor, reason=reason))

        # The end is journaled before filing and physical work start, since
        # either may yield before it writes and must not miss the new end.
        refusal = await self.record_operator_end(command, actor=actor, reason=reason)
        if refusal is not None:
            return await self._interrupted(command, refusal)
        outcome: LifecycleOutcome | BaseException
        progress: object
        outcome, progress = await asyncio.gather(
            self.submit(command, actor=actor, reason=reason), physical(negotiation_id),
            return_exceptions=True,
        )
        if isinstance(progress, BaseException):
            logger.error("Administrator end of %s awaits physical recovery: %s", negotiation_id, progress)
        if isinstance(outcome, BaseException):
            logger.error("Administrator filing for %s awaits authority recovery: %s", negotiation_id, outcome)
            outcome = Unknown(reason="delivery-end filing awaits authority recovery")
        return await self._interrupted(command, outcome)

    async def _interrupted(self, command: LifecycleCommand, outcome: LifecycleOutcome) -> InterruptResult:
        read = await asyncio.to_thread(self.delivery_read, command.negotiation_id)
        kind: Literal["notice", "delivery_end"] = "notice" if command.kind == "notice" else "delivery_end"
        return InterruptResult(kind=kind, outcome=outcome, delivery=read.delivery)

    async def _operator_end(
        self, command: LifecycleCommand, *, actor: Identity, reason: str,
    ) -> LifecycleOutcome:
        if command.at is not None or command.payload:
            return Rejected(reason="operator end uses durable receipt time, without at or payload")
        prepared = await self.record_operator_end(command, actor=actor, reason=reason)
        if prepared is not None:
            return prepared
        results = await self.dispatch_filings(command.negotiation_id)
        key = stable_ref(command.negotiation_id, "filing", "operator:" + command.operation_key)
        ref = stable_ref(command.negotiation_id, "filing", key)
        return next((item.outcome for item in results if item.intent_ref == ref), Accepted())

    async def record_operator_end(
        self, command: LifecycleCommand, *, actor: Identity, reason: str,
    ) -> LifecycleOutcome | None:
        """Durably record a local end before independently driving physical work or filing."""
        if command.kind != "delivery_end" or command.at is not None or command.payload:
            return Rejected(reason="operator end uses durable receipt time, without at or payload")
        # Bind the administrator and reason too, so retries cannot rewrite attribution.
        digest = hashlib.sha256(canonical_json({
            "command": command.model_dump(mode="json"), "actor": actor.model_dump(mode="json"), "reason": reason,
        })).hexdigest()
        return await asyncio.to_thread(self._prepare_operator_end, command, actor, reason, digest)

    def _prepare_operator_end(self, command, actor, reason, digest):
        now = self.clock()
        with transaction(self.path) as conn, atomic(conn):
            end = EndSession(conn)
            if not end.check_and_record(command.negotiation_id, command.operation_key, digest):
                return Rejected(reason="operation key retry changes content")
            prior = next((item for item in end.requests(command.negotiation_id)
                          if item.source_ref == "operator:" + command.operation_key), None)
            if prior is None:
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
        return None

    async def prune(self, negotiation_id: str) -> bool:
        """Refresh all required records before applying the retained evidence window."""
        deal = await asyncio.to_thread(self._deal, negotiation_id)
        watch = await asyncio.to_thread(self._watch, deal)
        views, _ = await watch.poll()
        if not views or not all(isinstance(view.outcome, Accepted) for view in views):
            return False
        if watch.payment is None or (deal.dispute is not None and watch.dispute is None):
            return False
        return await in_transaction(self.path, lambda conn: EvidenceSession(conn).prune(
            negotiation_id, now=self.clock(), has_adapter=True,
        ))

    def _filings(self, negotiation_id: str) -> builtins.list[FilingProgress]:
        with transaction(self.path) as conn:
            return [FilingProgress(
                intent_ref=intent.intent_ref,
                outcome=SubmitResponse.model_validate({"outcome": intent.result}).outcome if intent.result else
                    Pending(reason="delivery-end filing has not been attempted"),
            ) for intent in EndSession(conn).intents(negotiation_id) if intent.kind == "filing"]

    async def dispatch_filings(self, negotiation_id: str) -> builtins.list[FilingProgress]:
        deal = await asyncio.to_thread(self._deal, negotiation_id)
        binding = deal.dispute_binding
        filings = await in_transaction(self.path, lambda conn: [
            intent for intent in EndSession(conn).intents(negotiation_id) if intent.kind == "filing"
        ])
        results = []
        for intent in filings:
            if intent.state != "pending" and intent.result is not None:
                outcome = SubmitResponse.model_validate({"outcome": intent.result}).outcome
            elif binding is None:
                outcome = Rejected(reason=f"{deal.payment.mechanism} has no Agreement dispute authority")
            elif not self.credential_available(binding.authority):
                outcome = Rejected(reason="repair required: Agreement authority credential is missing")
            elif intent.not_before > self.clock():
                outcome = Pending(reason="delivery-end filing waits for Agreement start")
            else:
                outcome = await self._dispatch_filing(intent, binding)
            results.append(FilingProgress(intent_ref=intent.intent_ref, outcome=outcome))
        return results

    async def _dispatch_filing(self, intent: JournalIntent, binding: DisputeBinding) -> LifecycleOutcome:
        command = LifecycleCommand.model_validate(intent.payload)
        # The neutral dispatcher builds the interface request and uses this same key
        # after unknown responses; only the authority may apply monetary effects.
        outcome = await submit_dispute(command, binding, self.disputes, self.operations)
        await in_transaction(self.path, lambda conn: EndSession(conn).acknowledge(
            intent.intent_ref, outcome.model_dump(mode="json"),
            state="done" if isinstance(outcome, (Accepted, Rejected)) else "pending",
        ))
        return outcome
