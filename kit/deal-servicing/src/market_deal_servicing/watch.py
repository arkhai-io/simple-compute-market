"""Durable independent authority cursors and journal-before-advance observation."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import sqlite3
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Literal, cast

from market_deal_lifecycle.adapters import (DisputeAdapter, DisputeBinding, PaymentAdapter, OnceAccountingReader, OnceAccountingRead, OnceAccountingProjection)
from market_deal_lifecycle.operations import OperationKeys
from market_deal_lifecycle.respondent import RespondentAdapter
from market_deal_lifecycle_contracts.models import (
    Accepted, AuthorityView, DisputeEvent, EvidenceItem, LifecycleCommand, PaymentEvent, Rejected, Unknown,
)
from market_identity import Identity, IdentityScheme, canonical_json

from .evidence import EvidenceSession, RetentionObservation, in_transaction, transaction
from .journal import Classification, EndSession, FilingIntent, FinalRequest, atomic, stable_ref


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

    def record_payment_observation(self, negotiation_id: str, commitment_ref: str, observed_at: int) -> None:
        """Record a successful payment observation's instant, keeping the latest."""
        self.conn.execute(
            """INSERT INTO servicing_payment_observations VALUES (?,?,?)
               ON CONFLICT(negotiation_id,commitment_ref) DO UPDATE
               SET observed_at=MAX(observed_at,excluded.observed_at)""",
            (negotiation_id, commitment_ref, observed_at),
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

    def _record_payment_stop(self, end: EndSession, event: PaymentEvent) -> None:
        if (event.negotiation_id, event.commitment_ref) != (self.negotiation_id, self.commitment_ref):
            raise ValueError("authority stop names another deal")
        request = FinalRequest(
            negotiation_id=self.negotiation_id, source_ref="payment-stop:" + event.authority_record_ref,
            ended_at=event.at, observed_at=self.clock(), actor=self.actor(event.actor),
            cause=event.cause, source=event.authority_record_ref, evidence_refs=[event.authority_record_ref],
        )
        prior = next((item for item in end.requests(self.negotiation_id)
                      if item.source_ref == request.source_ref), None)
        if prior is not None:
            if request.model_copy(update={"observed_at": prior.observed_at}) != prior:
                raise ValueError("controlling payment stop changes its recorded end")
            # A stop recorded with its classification pending, because no
            # classifier was composed or it could not classify the stop, keeps
            # its recorded end; only the pending slot is resolved, once, when
            # the classifier classifies it.
            if end.classification(self.negotiation_id, prior.source_ref) is None:
                classification = self.classify_payment_end(event)
                if classification is not None:
                    end.resolve_correction(
                        self.negotiation_id, prior.source_ref, end.read(self.negotiation_id).revision,
                        evidence=prior.evidence_refs, classification=classification,
                        filing_intent=self._failure_filing(end, prior, classification),
                    )
            return
        classification = self.classify_payment_end(event)
        end.record_end(
            request, now=self.clock(), classification=classification,
            pending_classification=classification is None,
            filing_intent=self._failure_filing(end, request, classification),
        )

    def _failure_filing(
        self, end: EndSession, request: FinalRequest, classification: Classification | None,
    ) -> FilingIntent | None:
        """A seller failure's filing, journaled with its classification; a lawful end files nothing."""
        if classification is None or classification.lawful:
            return None
        return end.failure_filing(
            request, now=self.clock(), delivered=end.read(self.negotiation_id).available_at is not None,
        )

    def _observe(
        self, record_ref: str, view: AuthorityView, *, dispute: bool, observed_at: int | None, payment_projection=None,
    ) -> list[PaymentEvent | DisputeEvent]:
        """Journal what one accepted view shows; ``observed_at`` is a payment read's instant."""
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
            prior_cursor = cursor
            if max((event.sequence for event in events), default=-1) < cursor:
                raise ValueError("authority read regresses below its durable cursor")
            # A scheduled request can mature without a new event sequence. Read
            # its controlling per-part record independently of the event cursor.
            for part in view.parts:
                if part.final_stop is not None:
                    self._record_payment_stop(end, part.final_stop)
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
                    self._record_payment_stop(end, event)
                cursor = event.sequence
                fresh.append(event)
            if observed_at is not None:
                # In the transaction that recorded every final stop the view
                # carried, so admission never reads the instant without them.
                watch.record_payment_observation(self.negotiation_id, self.commitment_ref, observed_at)
            watch.save(self.negotiation_id, record_ref, cursor, view)
            if payment_projection is not None and not dispute:
                try:
                    with atomic(conn):
                        self._retain_verified_payment(conn, payment_projection, view, prior_cursor, cursor)
                except (ValueError, TypeError, AttributeError, sqlite3.Error):
                    pass  # No capture means unqualified; normal servicing continues.
            return fresh

    def _payment_capture_semantics(self, projection: OnceAccountingProjection, cursor: int) -> dict:
        """Financial invariants; a refreshed observation or signature is not a change."""
        return {
            "schema": "normal-payment-read-capture/v1",
            "negotiation_sha256": hashlib.sha256(self.negotiation_id.encode()).hexdigest(),
            "commitment_sha256": hashlib.sha256(self.commitment_ref.encode()).hexdigest(),
            "seller_account_sha256": hashlib.sha256(self.seller_account.encode()).hexdigest(),
            "latest_event_sequence": projection.latest_event_sequence, "saved_cursor": cursor,
            "livemode": projection.livemode, "part_count": projection.part_count,
            "all_parts_terminal": projection.all_parts_terminal,
            "financial_facts_sha256": projection.financial_facts_sha256,
        }

    def _payment_capture_matches(self, item: EvidenceItem, projection: OnceAccountingProjection, cursor: int) -> bool:
        if item.kind != "normal_verified_payment_read" or item.classification != "seller_assertion":
            raise ValueError("existing capture has unsupported provenance")
        prior = json.loads(item.body)
        expected = self._payment_capture_semantics(projection, cursor)
        return all(type(prior.get(key)) is type(value) and prior.get(key) == value
                   for key, value in expected.items())

    def _retain_verified_payment(self, conn, projection, view, prior_cursor, cursor):
        """Atomic evidence from THIS normal verified read, not a new service call.

        Capture-only failure rolls back its nested evidence savepoint, not the
        ordinary cursor/servicing transaction. Missing/conflicting capture is
        unqualified; no capture proves full poll success or stop readiness.
        """
        if (type(projection) is not OnceAccountingProjection
                or projection.negotiation_id != self.negotiation_id
                or projection.commitment_ref != self.commitment_ref
                or projection.seller_account != self.seller_account
                or not isinstance(view.outcome, Accepted)):
            raise ValueError("once projection differs from normal case")
        floor = max(0, prior_cursor, projection.minimum_sequence)
        if (type(prior_cursor) is not int or type(cursor) is not int
                or type(projection.minimum_sequence) is not int or projection.minimum_sequence < 0
                or type(projection.latest_event_sequence) is not int
                or not floor <= projection.latest_event_sequence <= 128
                or type(projection.provider_observed_at) is not int or projection.provider_observed_at < 0
                or type(projection.part_count) is not int or not 1 <= projection.part_count <= 32
                or projection.livemode is not False or type(projection.all_parts_terminal) is not bool
                or any(type(value) is not str or re.fullmatch(r"[a-f0-9]{64}", value) is None
                       for value in (projection.verified_signature_sha256, projection.financial_facts_sha256))
                or cursor != max((event.sequence for event in view.events), default=prior_cursor)
                or WatchSession(conn).cursor(self.negotiation_id, self.payment_record) != cursor):
            raise ValueError("once projection sequence or scope differs")
        terminal = projection.all_parts_terminal
        proof_hash = projection.verified_signature_sha256
        body = canonical_json({
            **self._payment_capture_semantics(projection, cursor),
            "minimum_sequence": floor, "prior_cursor": prior_cursor,
            "provider_observed_at": projection.provider_observed_at,
            "verified_signature_sha256": proof_hash,
        })
        if len(body) > 4096:
            raise ValueError("payment read capture exceeds fixed projection")
        commitment_hash = hashlib.sha256(self.commitment_ref.encode()).hexdigest()
        evidence_id = "normal-payment-read:" + commitment_hash + ":" + str(projection.latest_event_sequence)
        conflict_id = "normal-payment-read-conflict:" + commitment_hash
        # Exact capture-only ceiling already inherited from <=128 events.
        # It has NO effect on normal user, payment, watch or lifecycle limits.
        count = 0
        for prefix in ("normal-payment-read:", "normal-payment-read-conflict:"):
            count += conn.execute(
                "SELECT count(*) FROM (SELECT 1 FROM servicing_evidence_items "
                "WHERE negotiation_id=? AND evidence_id>=? AND evidence_id<? LIMIT 131)",
                (self.negotiation_id, prefix, prefix[:-1] + ";"),
            ).fetchone()[0]
        if type(count) is not int or count > 130:
            raise ValueError("capture history exceeds narrow scope")
        row = conn.execute(
            "SELECT length(item),substr(item,1,8193) FROM servicing_evidence_items "
            "WHERE negotiation_id=? AND evidence_id=?", (self.negotiation_id, evidence_id),
        ).fetchone()
        if row:
            if type(row[0]) is not int or not 0 < row[0] <= 8192:
                raise ValueError("existing capture exceeds scope")
            previous = EvidenceItem.model_validate_json(row[1])
            if self._payment_capture_matches(previous, projection, cursor):
                return  # Same finance: keep first verified observation, no write.
            if conn.execute("SELECT 1 FROM servicing_evidence_items WHERE negotiation_id=? AND evidence_id=?",
                            (self.negotiation_id, conflict_id)).fetchone():
                return  # The original unqualified marker is already durable.
            conflict = canonical_json({"schema": "normal-payment-read-conflict/v1",
                "commitment_sha256": commitment_hash,
                "classification": "SAME_SEQUENCE_FINANCIAL_FACTS_UNQUALIFIED"})
            EvidenceSession(conn).put(self.negotiation_id, EvidenceItem(
                evidence_id=conflict_id, kind="normal_verified_payment_read_conflict",
                classification="seller_assertion", recorded_at=self.clock(),
                body=base64.b64encode(conflict), context={"schema": "normal-payment-read-conflict/v1"},
            ))
            return  # Stable single marker; no row overwrite, pruning or rearm.
        if not terminal:
            return  # A pending normal poll produces no terminal closeout receipt.
        if count >= 129:
            raise ValueError("capture count excludes additional terminal row")
        EvidenceSession(conn).put(self.negotiation_id, EvidenceItem(
            evidence_id=evidence_id,
            kind="normal_verified_payment_read", classification="seller_assertion",
            recorded_at=self.clock(), body=base64.b64encode(body),
            context={"schema": "normal-payment-read-capture/v1"},
        ))


    def _refresh(self, record_ref: str, view: AuthorityView, *, dispute: bool, observed_at: int | None = None, payment_projection=None):
        try:
            fresh = self._observe(record_ref, view, dispute=dispute, observed_at=observed_at, payment_projection=payment_projection)
        except ValueError as exc:
            view = AuthorityView(outcome=Rejected(reason=str(exc)))
            fresh = []
        with transaction(self.path) as conn:
            WatchSession(conn).observe(self.negotiation_id, record_ref, view)
        return view, fresh

    async def poll(self) -> tuple[list[AuthorityView], list[PaymentEvent | DisputeEvent]]:
        views, fresh, _, _ = await self._poll_with_accounting()
        return views, fresh

    async def _poll_with_accounting(self):
        """Read each authority and journal what it shows.

        A verified payment read also records its instant, taken before the read
        is sent: the authority answers no earlier, so a stop it had recorded by
        then is in the view. A failed, unverified or refused read records none.
        """
        views = []
        fresh: list[PaymentEvent | DisputeEvent] = []
        payment_projection = None
        observation = None
        accounting = None
        if self.payment is not None:
            observed_at = self.clock()
            can_capture = isinstance(self.payment, OnceAccountingReader)
            minimum_sequence = 0
            if can_capture:
                try:
                    def prior_floor():
                        with transaction(self.path) as conn:
                            value = WatchSession(conn).cursor(self.negotiation_id, self.payment_record)
                            if type(value) is not int:
                                raise ValueError("normal prior cursor unavailable")
                            return max(0, value)
                    minimum_sequence = await asyncio.to_thread(prior_floor)
                except Exception:
                    can_capture = False  # Before I/O; retain ordinary single read.
            if can_capture:
                captured = await cast(OnceAccountingReader, self.payment).read_with_once_accounting(
                    minimum_sequence=minimum_sequence, read_started_at=observed_at)
                if type(captured) is not OnceAccountingRead or not isinstance(captured.view, AuthorityView):
                    payment = AuthorityView(outcome=Unknown(reason="optional once read result is unqualified"))
                else:
                    payment, payment_projection = captured.view, captured.projection
            else:
                payment = await self.payment.read()
            payment, events = await asyncio.to_thread(
                self._refresh, self.payment_record, payment, dispute=False, observed_at=observed_at,
                payment_projection=payment_projection,
            )
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
        if payment_projection is not None and views and isinstance(views[0].outcome, Accepted):
            try:
                def same_read_floor():
                    with transaction(self.path) as conn:
                        session = WatchSession(conn)
                        if (session.view(self.negotiation_id, self.payment_record) != views[0]
                                or session.observation(self.negotiation_id, self.payment_record) != views[0]
                                or EndSession(conn).payment_observed_at(self.negotiation_id, self.commitment_ref) != observed_at):
                            raise ValueError("normal payment observation changed")
                        conflict_id = "normal-payment-read-conflict:" + hashlib.sha256(self.commitment_ref.encode()).hexdigest()
                        if conn.execute("SELECT 1 FROM servicing_evidence_items WHERE negotiation_id=? AND evidence_id=?",
                                        (self.negotiation_id, conflict_id)).fetchone():
                            raise ValueError("same-sequence payment facts remain unqualified")
                        floor = session.cursor(self.negotiation_id, self.payment_record)
                        if type(floor) is not int:
                            raise ValueError("normal cursor unavailable")
                        evidence_id = ("normal-payment-read:"
                                       + hashlib.sha256(self.commitment_ref.encode()).hexdigest()
                                       + ":" + str(payment_projection.latest_event_sequence))
                        row = conn.execute(
                            "SELECT length(item),substr(item,1,8193) FROM servicing_evidence_items "
                            "WHERE negotiation_id=? AND evidence_id=?", (self.negotiation_id, evidence_id),
                        ).fetchone()
                        if (row is None or type(row[0]) is not int or not 0 < row[0] <= 8192
                                or not self._payment_capture_matches(
                                    EvidenceItem.model_validate_json(row[1]), payment_projection, floor)):
                            raise ValueError("normal payment capture is missing or differs")
                        return max(0, floor)
                floor = await asyncio.to_thread(same_read_floor)
                if (type(payment_projection) is not OnceAccountingProjection
                        or payment_projection.negotiation_id != self.negotiation_id
                        or payment_projection.commitment_ref != self.commitment_ref
                        or payment_projection.seller_account != self.seller_account
                        or payment_projection.latest_event_sequence < floor
                        or payment_projection.livemode is not False
                        or payment_projection.accounting.get("returnAdmitted") is not False
                        or not 0 <= self.clock() - observed_at <= 60):
                    raise ValueError("normal once accounting projection changed")
                accounting = payment_projection.accounting
            except Exception:
                accounting = None
        return views, fresh, accounting, observation

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
