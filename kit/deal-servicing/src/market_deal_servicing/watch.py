"""Durable independent authority cursors and journal-before-advance observation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Literal

from market_deal_lifecycle.adapters import DisputeAdapter, DisputeBinding, PaymentAdapter
from market_deal_lifecycle.operations import OperationKeys
from market_deal_lifecycle.respondent import RespondentAdapter
from market_deal_lifecycle_contracts.models import (
    Accepted, AuthorityView, DisputeEvent, EvidenceItem, LifecycleCommand, PaymentEvent, Rejected,
)
from market_identity import Identity, IdentityScheme, canonical_json

from .evidence import EvidenceSession, RetentionObservation, in_transaction, transaction
from .journal import Classification, EndSession, FinalRequest, atomic, stable_ref


class WatchSession:
    """Watch cursors over the caller's connection; it issues no DDL, its tables
    being the storefront chain's (``market_deal_servicing.schema``)."""

    def __init__(self, conn):
        self.conn = conn

    def cursor(self, negotiation_id: str, record_ref: str) -> int:
        row = self.conn.execute(
            "SELECT sequence FROM servicing_watch WHERE negotiation_id=? AND record_ref=?",
            (negotiation_id, record_ref),
        ).fetchone()
        return row[0] if row else -1

    def view(self, negotiation_id: str, record_ref: str) -> AuthorityView | None:
        row = self.conn.execute(
            "SELECT view FROM servicing_watch WHERE negotiation_id=? AND record_ref=?",
            (negotiation_id, record_ref),
        ).fetchone()
        return AuthorityView.model_validate_json(row[0]) if row else None

    def observation(self, negotiation_id: str, record_ref: str) -> AuthorityView | None:
        row = self.conn.execute(
            "SELECT view FROM servicing_observations WHERE negotiation_id=? AND record_ref=?",
            (negotiation_id, record_ref),
        ).fetchone()
        return AuthorityView.model_validate_json(row[0]) if row else None

    def observe(self, negotiation_id: str, record_ref: str, view: AuthorityView) -> None:
        self.conn.execute(
            """INSERT INTO servicing_observations VALUES (?,?,?)
               ON CONFLICT(negotiation_id,record_ref) DO UPDATE SET view=excluded.view""",
            (negotiation_id, record_ref, view.model_dump_json()),
        )

    def save(self, negotiation_id: str, record_ref: str, sequence: int, view: AuthorityView) -> None:
        if sequence < self.cursor(negotiation_id, record_ref):
            raise ValueError("authority cursor regresses")
        self.conn.execute(
            """INSERT INTO servicing_watch VALUES (?,?,?,?)
               ON CONFLICT(negotiation_id,record_ref) DO UPDATE
               SET sequence=excluded.sequence,view=excluded.view""",
            (negotiation_id, record_ref, sequence, view.model_dump_json()),
        )


class DealWatch:
    """Adapters verify their pinned authority before supplying neutral records.

    Each poll is bounded by the adapters' paginated reads. The storefront loop
    controller supplies cadence and pause/step control; this kit starts no timer.
    Payment and dispute sequences are never compared with each other.
    """

    def __init__(
        self, path: str | Path, *, negotiation_id: str, commitment_ref: str,
        payment: PaymentAdapter | None, dispute: DisputeAdapter | None,
        dispute_binding: DisputeBinding | None, seller_account: str,
        actor: Callable[[str], Identity], clock: Callable[[], int],
        classify_payment_end: Callable[[PaymentEvent], Classification | None] = lambda _: None,
        observe_retention: Callable[[list[AuthorityView]], RetentionObservation | None] = lambda _: None,
    ):
        self.path = Path(path)
        self.negotiation_id = negotiation_id
        self.commitment_ref = commitment_ref
        self.payment = payment
        self.dispute = dispute
        self.binding = dispute_binding
        self.seller_account = seller_account
        self.actor = actor
        self.classify_payment_end = classify_payment_end
        self.observe_retention = observe_retention
        self.clock = clock
        self.payment_record = "payment:" + commitment_ref
        self.dispute_record = (
            stable_ref(negotiation_id, "dispute-record", canonical_json(dispute_binding.authority).decode())
            if dispute_binding else None
        )
        if dispute_binding is not None and (
            dispute_binding.negotiation_id != negotiation_id
            or dispute_binding.commitment_ref != commitment_ref
        ):
            raise ValueError("watch binding names another deal")

    def _observe(
        self, record_ref: str, view: AuthorityView, *, dispute: bool,
    ) -> list[PaymentEvent | DisputeEvent]:
        if not isinstance(view.outcome, Accepted):
            return []
        events: list[PaymentEvent | DisputeEvent] = []
        if dispute:
            events.extend(view.disputes)
        else:
            events.extend(view.events)
        events.sort(key=lambda item: item.sequence)
        if len({item.sequence for item in events}) != len(events):
            raise ValueError("authority read repeats a sequence")
        with transaction(self.path) as conn, atomic(conn):
            watch = WatchSession(conn)
            end = EndSession(conn)
            cursor = watch.cursor(self.negotiation_id, record_ref)
            if max((event.sequence for event in events), default=-1) < cursor:
                raise ValueError("authority read regresses below its durable cursor")
            fresh: list[PaymentEvent | DisputeEvent] = []
            for event in events:
                if event.negotiation_id != self.negotiation_id or event.commitment_ref != self.commitment_ref:
                    raise ValueError("authority event names another deal")
                if event.sequence <= cursor:
                    continue
                if isinstance(event, DisputeEvent):
                    for item in event.items:
                        EvidenceSession(conn).put(self.negotiation_id, item)
                    for effect in event.outcome:
                        if effect.kind != "delivery_end":
                            continue
                        source_ref = "dispute-effect:" + effect.effect_id
                        prior = next((request for request in end.requests(self.negotiation_id)
                                      if request.source_ref == source_ref), None)
                        if prior is not None:
                            if prior.ended_at != effect.at:
                                raise ValueError("authority effect identity changes its end")
                            continue
                        if self.binding is None:
                            raise ValueError("dispute effect requires its accepted authority binding")
                        scheme, separator, key = self.binding.authority.record_key.partition(":")
                        authority_actor = Identity(
                            scheme=IdentityScheme(scheme) if separator else IdentityScheme.ED25519,
                            identifier=key if separator else scheme,
                        )
                        request = FinalRequest(
                            negotiation_id=self.negotiation_id, source_ref=source_ref,
                            ended_at=effect.at, observed_at=self.clock(),
                            actor=authority_actor,
                            cause="ruling", source=event.record_ref,
                            evidence_refs=[item.evidence_id for item in event.items] or [event.record_ref],
                        )
                        end.record_end(
                            request, now=self.clock(), classification=Classification(
                                kind="ruling", evidence_refs=request.evidence_refs,
                            ),
                        )
                    # Discovery owns the signed answer. Do not advance past an
                    # unanswered filing: later effects replay once its exact answer
                    # is journaled, or the authority confirms the case closed.
                    if (event.kind == "filed" and event.actor != self.seller_account
                            and isinstance(self.dispute, RespondentAdapter)):
                        key = stable_ref(self.negotiation_id, "append", event.case_ref)
                        answered = end.intent(stable_ref(self.negotiation_id, "append", key)) is not None
                        closed = any(case.case_ref == event.case_ref and case.state == "closed" for case in view.cases)
                        if not answered and not closed:
                            break
                    elif event.kind == "filed" and event.actor != self.seller_account:
                        if self.dispute is None:
                            raise ValueError("counterparty case has no dispute adapter")
                        key = stable_ref(self.negotiation_id, "append", event.case_ref)
                        # Respondent discovery may already have journaled signed
                        # concurrence. Never replace its exact answer on watch replay.
                        if end.intent(stable_ref(self.negotiation_id, "append", key)) is not None:
                            cursor = event.sequence
                            fresh.append(event)
                            continue
                        items = EvidenceSession(conn).read(self.negotiation_id).items
                        payload = self.dispute.build_append(event.case_ref, items)
                        if isinstance(payload, Rejected):
                            raise ValueError(payload.reason)
                        command = LifecycleCommand(
                            negotiation_id=self.negotiation_id, kind="append",
                            operation_key=stable_ref(self.negotiation_id, "append", event.case_ref),
                            payload=payload,
                        )
                        intent = end.journal(
                            self.negotiation_id, "append", command.operation_key,
                            command.model_dump(mode="json"), not_before=event.at,
                        )
                        closed = any(case.case_ref == event.case_ref and case.state == "closed" for case in view.cases)
                        if closed and intent.state == "pending" and intent.result is None:
                            end.acknowledge(
                                intent.intent_ref, {"reason": "authority confirmed closed case"}, state="skipped",
                            )
                elif event.kind == "stop":
                    request = FinalRequest(
                        negotiation_id=self.negotiation_id, source_ref="payment-stop:" + event.authority_record_ref,
                        ended_at=event.at, observed_at=self.clock(),
                        actor=self.actor(event.actor), cause=event.cause, source=event.authority_record_ref,
                        evidence_refs=[event.authority_record_ref],
                    )
                    classification = self.classify_payment_end(event)
                    end.record_end(
                        request, now=self.clock(), classification=classification,
                        pending_classification=classification is None,
                        filing_intent=(
                            end.failure_filing(
                                request, now=self.clock(),
                                delivered=end.read(self.negotiation_id).available_at is not None,
                            ) if classification is not None and not classification.lawful else None
                        ),
                    )
                cursor = event.sequence
                fresh.append(event)
            watch.save(self.negotiation_id, record_ref, cursor, view)
            return fresh

    def _refresh(self, record_ref: str, view: AuthorityView, *, dispute: bool):
        try:
            fresh = self._observe(record_ref, view, dispute=dispute)
        except ValueError as exc:
            view = AuthorityView(outcome=Rejected(reason=str(exc)))
            fresh = []
        with transaction(self.path) as conn:
            WatchSession(conn).observe(self.negotiation_id, record_ref, view)
        return view, fresh

    async def poll(self) -> tuple[list[AuthorityView], list[PaymentEvent | DisputeEvent]]:
        views = []
        fresh: list[PaymentEvent | DisputeEvent] = []
        if self.payment is not None:
            payment = await self.payment.read()
            payment, events = await asyncio.to_thread(self._refresh, self.payment_record, payment, dispute=False)
            views.append(payment)
            fresh.extend(events)
        if self.dispute is not None and self.dispute_record is not None:
            dispute = await self.dispute.read()
            dispute, events = await asyncio.to_thread(self._refresh, self.dispute_record, dispute, dispute=True)
            views.append(dispute)
            fresh.extend(events)
        await self.replay_appends()
        if views and all(isinstance(view.outcome, Accepted) for view in views):
            observation = await asyncio.to_thread(self.observe_retention, views)
            if observation is not None:
                await in_transaction(self.path, lambda conn: EvidenceSession(conn).observe(self.negotiation_id, observation))
        return views, fresh

    async def watch(self) -> AsyncIterator[AuthorityView | PaymentEvent | DisputeEvent]:
        """One controller cycle: current verified views, then newly journaled events."""
        views, fresh = await self.poll()
        for view in views:
            yield view
        for event in fresh:
            yield event

    async def replay_appends(self) -> None:
        if self.dispute is None:
            return
        pending = await in_transaction(self.path, lambda conn: [
            intent for intent in EndSession(conn).intents(self.negotiation_id, pending_only=True)
            if intent.kind == "append"
        ])
        for intent in pending:
            if intent.not_before > self.clock():
                continue
            command = LifecycleCommand.model_validate(intent.payload)
            # Mark the uncertain I/O boundary before sending. Even if the case is
            # now closed, a replay must first recover any earlier acknowledgement.
            await in_transaction(self.path, lambda conn: EndSession(conn).acknowledge(
                intent.intent_ref, {"attempted": True}, state="pending",
            ))
            outcome = await self.dispute.submit(
                command, None, OperationKeys(self.negotiation_id, command.operation_key),
            )
            state: Literal["pending", "done", "skipped"] = "done" if isinstance(outcome, Accepted) else "pending"
            if isinstance(outcome, Rejected):
                view = await self.dispute.read()
                if isinstance(view.outcome, Accepted) and any(
                    case.case_ref == command.payload.get("case_ref") and case.state == "closed"
                    for case in view.cases
                ):
                    state = "skipped"
            await in_transaction(self.path, lambda conn: EndSession(conn).acknowledge(
                intent.intent_ref, outcome.model_dump(mode="json"), state=state,
            ))

    async def peer_hint(self, item: EvidenceItem) -> list[AuthorityView]:
        """Authentication and buyer binding are checked at the route boundary."""
        await in_transaction(self.path, lambda conn: EvidenceSession(conn).put(self.negotiation_id, item))
        views, _ = await self.poll()
        return views
