"""Caller-session delivery admission and an immutable effect journal."""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Literal

from market_deal_lifecycle.adapters import DeliveryEndIntent
from market_deal_lifecycle.delivery import DeliveryPhase
from market_deal_lifecycle_contracts.models import (
    DeliveryView, Instant, LifecycleCommand, RecordedEnd, Reference, WireModel,
)
from market_identity import Identity, frame_fields
from pydantic import Field, model_validator

from .evidence import EvidenceSession

Revision = Annotated[int, Field(strict=True, ge=0)]
ClassificationKind = Literal[
    "entitled_stop", "terms", "exhaustion", "ruling", "buyer_surrender",
    "unentitled_withdrawal", "provisioning_failure", "start_failure",
    "activation_lapse", "non_delivery",
]
PhysicalProgress = Literal["unstarted", "active", "end_recorded", "tearing_down", "released", "repair_required"]
IntentKind = Literal["terminate", "truncate", "billing", "filing", "append", "authorization"]
LAWFUL = frozenset({"entitled_stop", "terms", "exhaustion", "ruling", "buyer_surrender"})


class Classification(WireModel):
    kind: ClassificationKind
    evidence_refs: Annotated[list[Reference], Field(min_length=1)]

    @property
    def lawful(self) -> bool:
        return self.kind in LAWFUL


class FinalRequest(RecordedEnd):
    negotiation_id: Reference
    source_ref: Reference
    observed_at: Instant
    administrator_reason: str | None = None
    controlling_source_ref: Reference | None = None

    @property
    def attribution(self) -> RecordedEnd:
        return RecordedEnd(**self.model_dump(include={
            "ended_at", "actor", "cause", "source", "evidence_refs",
        }))


class DeliveryRecord(WireModel):
    negotiation_id: Reference
    seller: Identity
    commitment_ref: Reference
    start_at: Instant
    term_end: Instant
    committed_at: Instant | None = None
    delivery_deadline_seconds: Annotated[int, Field(strict=True, gt=0)] | None = None
    available_at: Instant | None = None
    phase: DeliveryPhase = DeliveryPhase.RESERVE
    progress: PhysicalProgress = "unstarted"
    revision: Revision = 0

    @model_validator(mode="after")
    def coherent_term(self) -> DeliveryRecord:
        if self.term_end < self.start_at:
            raise ValueError("term end precedes Agreement start")
        return self

    @property
    def deadline(self) -> int:
        if self.delivery_deadline_seconds is None or self.committed_at is None:
            return self.term_end
        return min(self.term_end, max(self.start_at, self.committed_at) + self.delivery_deadline_seconds)


class Admission(WireModel):
    status: Literal["admitted", "ended", "retry"]
    revision: Revision
    ended_at: Instant | None = None


class FilingIntent(WireModel):
    command: LifecycleCommand
    not_before: Instant


class JournalIntent(WireModel):
    intent_ref: Reference
    negotiation_id: Reference
    kind: IntentKind
    operation_key: Reference
    payload: dict
    not_before: Instant
    state: Literal["pending", "done", "skipped"] = "pending"
    result: dict | None = None


def stable_ref(negotiation_id: str, kind: str, key: str) -> str:
    return hashlib.sha256(frame_fields((
        "arkhai.deal-servicing.intent.v1", negotiation_id, kind, key,
    ))).hexdigest()


@contextmanager
def atomic(conn: sqlite3.Connection) -> Iterator[None]:
    if not conn.in_transaction:
        raise RuntimeError("servicing writes require the caller's active transaction")
    name = "servicing_" + uuid.uuid4().hex
    conn.execute(f"SAVEPOINT {name}")
    try:
        yield
    except BaseException:
        conn.execute(f"ROLLBACK TO {name}")
        conn.execute(f"RELEASE {name}")
        raise
    else:
        conn.execute(f"RELEASE {name}")


class EndSession:
    """All ordering writes share the caller's delivery/Agreement transaction.

    The session issues no DDL: its tables are the storefront chain's
    (``market_deal_servicing.schema``).
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def register(self, record: DeliveryRecord) -> None:
        with atomic(self.conn):
            old = self.conn.execute(
                "SELECT record FROM servicing_delivery WHERE negotiation_id=?", (record.negotiation_id,),
            ).fetchone()
            if old:
                previous = DeliveryRecord.model_validate_json(old[0])
                fields = {"seller", "commitment_ref", "start_at", "term_end", "delivery_deadline_seconds"}
                if record.committed_at is not None and previous.committed_at != record.committed_at:
                    raise ValueError("delivery registration changes verified commitment time")
                if previous.model_dump(include=fields) != record.model_dump(include=fields):
                    raise ValueError("delivery registration changes accepted timing or identity")
                return
            self.conn.execute(
                "INSERT INTO servicing_delivery VALUES (?,?,?)",
                (record.negotiation_id, record.revision, record.model_dump_json()),
            )

    def confirm_commitment(self, negotiation_id: str, *, committed_at: int) -> DeliveryRecord:
        """Bind authority-verified timing without discarding pre-dispatch ends."""
        with atomic(self.conn):
            record = self.read(negotiation_id)
            if record.committed_at is not None:
                if record.committed_at != committed_at:
                    raise ValueError("verified commitment time cannot change")
                return record
            return self._write(record.model_copy(update={"committed_at": committed_at}))

    def read(self, negotiation_id: str) -> DeliveryRecord:
        row = self.conn.execute(
            "SELECT revision,record FROM servicing_delivery WHERE negotiation_id=?", (negotiation_id,),
        ).fetchone()
        if row is None:
            raise KeyError(negotiation_id)
        return DeliveryRecord.model_validate_json(row[1]).model_copy(update={"revision": row[0]})

    def _write(self, record: DeliveryRecord) -> DeliveryRecord:
        revision = record.revision + 1
        updated = record.model_copy(update={"revision": revision})
        if self.conn.execute(
            "UPDATE servicing_delivery SET revision=?,record=? WHERE negotiation_id=? AND revision=?",
            (revision, updated.model_dump_json(), record.negotiation_id, record.revision),
        ).rowcount != 1:
            raise RuntimeError("delivery revision changed; retry the transaction")
        return updated

    def requests(self, negotiation_id: str) -> list[FinalRequest]:
        return [FinalRequest.model_validate_json(row[0]) for row in self.conn.execute(
            """SELECT request FROM servicing_final_requests WHERE negotiation_id=?
               ORDER BY ended_at, source_ref COLLATE BINARY""", (negotiation_id,),
        )]

    def selected_end(self, negotiation_id: str) -> FinalRequest | None:
        requests = self.requests(negotiation_id)
        return requests[0] if requests else None

    def view(self, negotiation_id: str) -> DeliveryView:
        record = self.read(negotiation_id)
        selected = self.selected_end(negotiation_id)
        return DeliveryView(
            recorded_end=selected.attribution if selected else None, progress=record.progress,
            site_reports=[
                item for item in EvidenceSession(self.conn).read(negotiation_id).items
                if item.kind == "lease_ended"
            ],
        )

    def journal(
        self, negotiation_id: str, kind: IntentKind,
        operation_key: str, payload: dict, *, not_before: int,
    ) -> JournalIntent:
        if not self.conn.in_transaction:
            raise RuntimeError("intent journaling requires the caller's transaction")
        ref = stable_ref(negotiation_id, kind, operation_key)
        intent = JournalIntent(
            intent_ref=ref, negotiation_id=negotiation_id, kind=kind,
            operation_key=operation_key, payload=payload, not_before=not_before,
        )
        old = self.intent(ref)
        if old is not None:
            fields = {"payload", "not_before"}
            if old.model_dump(include=fields) != intent.model_dump(include=fields):
                raise ValueError("intent key retry changes content")
            return old
        self.conn.execute(
            "INSERT INTO servicing_intents VALUES (?,?,?,?,?)",
            (ref, negotiation_id, kind, operation_key, intent.model_dump_json()),
        )
        return intent

    def intent(self, ref: str) -> JournalIntent | None:
        row = self.conn.execute(
            "SELECT intent FROM servicing_intents WHERE intent_ref=?", (ref,),
        ).fetchone()
        return JournalIntent.model_validate_json(row[0]) if row else None

    def intents(self, negotiation_id: str, *, pending_only: bool = False) -> list[JournalIntent]:
        items = [JournalIntent.model_validate_json(row[0]) for row in self.conn.execute(
            "SELECT intent FROM servicing_intents WHERE negotiation_id=? ORDER BY rowid", (negotiation_id,),
        )]
        return [item for item in items if not pending_only or item.state == "pending"]

    def acknowledge(self, ref: str, result: dict, *, state: Literal["pending", "done", "skipped"]) -> None:
        with atomic(self.conn):
            old = self.intent(ref)
            if old is None:
                raise KeyError(ref)
            if old.state != "pending":
                if old.state != state or old.result != result:
                    raise ValueError("completed intent cannot change")
                return
            updated = old.model_copy(update={"state": state, "result": result})
            self.conn.execute(
                "UPDATE servicing_intents SET intent=? WHERE intent_ref=?", (updated.model_dump_json(), ref),
            )

    def record_end(
        self, request: FinalRequest, *, now: int, filing_intent: FilingIntent | None = None,
        pending_classification: bool = False, classification: Classification | None = None,
    ) -> DeliveryRecord:
        with atomic(self.conn):
            record = self.read(request.negotiation_id)
            if request.observed_at > now:
                raise ValueError("end observation cannot be future-dated")
            if classification is None and not pending_classification:
                raise ValueError("an end requires verified classification or a pending slot")
            if classification is not None and pending_classification:
                raise ValueError("classification is either resolved or pending")
            if classification is not None and classification.lawful and filing_intent is not None:
                raise ValueError("lawful end cannot carry a self-penalty filing")
            if (classification is not None and not classification.lawful and filing_intent is None
                    and request.controlling_source_ref is None):
                raise ValueError("seller failure must atomically journal its filing")
            if pending_classification and filing_intent is not None:
                raise ValueError("pending classification cannot yet carry a filing")
            old = self.conn.execute(
                """SELECT request,classification FROM servicing_final_requests
                   WHERE negotiation_id=? AND source_ref=?""", (request.negotiation_id, request.source_ref),
            ).fetchone()
            if old:
                if FinalRequest.model_validate_json(old[0]) != request:
                    raise ValueError("final-request identity retry changes content")
                if classification is not None and (
                    old[1] is None or Classification.model_validate_json(old[1]) != classification
                ):
                    raise ValueError("classification changes require pending-slot resolution")
                if filing_intent is not None:
                    self._filing(request, filing_intent)
                return record
            if request.controlling_source_ref is not None:
                self._validate_controlling(request, classification, request.controlling_source_ref)
                if filing_intent is not None:
                    raise ValueError("correlated report adopts its controlling filing")
            # A never-delivered correction covers the entire accepted term.
            basis = record.start_at
            self.conn.execute(
                "INSERT INTO servicing_final_requests VALUES (?,?,?,?,?,?)",
                (
                    request.negotiation_id, request.source_ref, request.ended_at, request.model_dump_json(),
                    classification.model_dump_json() if classification else None, basis,
                ),
            )
            if filing_intent is not None:
                self._filing(request, filing_intent)
            record = self._write(record.model_copy(update={
                "progress": record.progress if record.progress in {"released", "tearing_down"} else "end_recorded",
            }))
            self.schedule_physical(request.negotiation_id, now=now)
            return record

    def _validate_controlling(
        self, request: FinalRequest, classification: Classification | None, source_ref: str,
    ) -> None:
        row = self.conn.execute(
            """SELECT request,classification FROM servicing_final_requests
               WHERE negotiation_id=? AND source_ref=?""", (request.negotiation_id, source_ref),
        ).fetchone()
        if row is None or row[1] is None or source_ref == request.source_ref:
            raise ValueError("correlated end requires its verified controlling request")
        controlling = FinalRequest.model_validate_json(row[0])
        if (classification is None or Classification.model_validate_json(row[1]).kind != classification.kind
                or controlling.ended_at > request.ended_at):
            raise ValueError("correlated report must preserve its controlling classification and end")
        if not classification.lawful:
            key = stable_ref(request.negotiation_id, "filing", source_ref)
            filing = self.intent(stable_ref(request.negotiation_id, "filing", key))
            selected = self.selected_end(request.negotiation_id)
            if filing is None and (selected is None or selected.source_ref == source_ref):
                raise ValueError("controlling seller failure requires its journaled filing")

    def _filing(self, request: FinalRequest, filing: FilingIntent) -> None:
        command = filing.command
        if command.negotiation_id != request.negotiation_id or command.kind != "delivery_end":
            raise ValueError("correction must be this deal's delivery_end intent")
        claim = DeliveryEndIntent.model_validate(command.payload)
        row = self.conn.execute(
            """SELECT correction_basis FROM servicing_final_requests
               WHERE negotiation_id=? AND source_ref=?""", (request.negotiation_id, request.source_ref),
        ).fetchone()
        if command.operation_key != stable_ref(request.negotiation_id, "filing", request.source_ref):
            raise ValueError("filing key must bind the correction source")
        if claim.cause != "payee":
            raise ValueError("seller correction has cause payee")
        if not claim.delivered and claim.ended_at != row[0]:
            raise ValueError("never-delivered correction must preserve its fixed basis")
        if filing.not_before < claim.ended_at:
            raise ValueError("a filing cannot be future-dated")
        # A classified earlier end settles whether a financial claim is owed.
        # An unclassified report cannot discharge this seller failure's filing.
        selected = self.selected_end(request.negotiation_id)
        if selected is not None and selected.source_ref != request.source_ref:
            classification = self.conn.execute(
                """SELECT classification FROM servicing_final_requests
                   WHERE negotiation_id=? AND source_ref=?""", (request.negotiation_id, selected.source_ref),
            ).fetchone()[0]
            if classification is not None:
                return
        self.journal(
            request.negotiation_id, "filing", command.operation_key,
            command.model_dump(mode="json"), not_before=filing.not_before,
        )

    def resolve_correction(
        self, negotiation_id: str, source_ref: str, expected_revision: int, *,
        evidence: list[str], classification: Classification, filing_intent: FilingIntent | None = None,
        controlling_source_ref: str | None = None,
    ) -> Admission:
        with atomic(self.conn):
            record = self.read(negotiation_id)
            if record.revision != expected_revision:
                return Admission(status="retry", revision=record.revision)
            if not evidence or not set(classification.evidence_refs).issubset(evidence):
                raise ValueError("classification requires the verified resolution evidence")
            row = self.conn.execute(
                """SELECT request,classification FROM servicing_final_requests
                   WHERE negotiation_id=? AND source_ref=?""", (negotiation_id, source_ref),
            ).fetchone()
            if row is None:
                raise KeyError(source_ref)
            request = FinalRequest.model_validate_json(row[0])
            controlling = controlling_source_ref or request.controlling_source_ref
            if controlling is not None:
                self._validate_controlling(request, classification, controlling)
                if filing_intent is not None:
                    raise ValueError("correlated report adopts its controlling filing")
            if row[1] is not None:
                if Classification.model_validate_json(row[1]) != classification:
                    raise ValueError("resolved classification cannot change")
                return Admission(status="admitted", revision=record.revision)
            if classification.lawful:
                if filing_intent is not None:
                    raise ValueError("lawful classification discharges correction")
            elif filing_intent is None and controlling is None:
                raise ValueError("seller failure requires a filing in the same transaction")
            if filing_intent is not None:
                self._filing(request, filing_intent)
            self.conn.execute(
                """UPDATE servicing_final_requests SET classification=?
                   WHERE negotiation_id=? AND source_ref=?""",
                (classification.model_dump_json(), negotiation_id, source_ref),
            )
            record = self._write(record)
            return Admission(status="admitted", revision=record.revision)

    def failure_filing(self, request: FinalRequest, *, now: int, delivered: bool) -> FilingIntent:
        record = self.read(request.negotiation_id)
        old = self.conn.execute(
            "SELECT correction_basis FROM servicing_final_requests WHERE negotiation_id=? AND source_ref=?",
            (request.negotiation_id, request.source_ref),
        ).fetchone()
        basis = old[0] if old else record.start_at
        if delivered:
            basis = request.ended_at
        command = LifecycleCommand(
            negotiation_id=request.negotiation_id, kind="delivery_end",
            operation_key=stable_ref(request.negotiation_id, "filing", request.source_ref),
            payload=DeliveryEndIntent(ended_at=basis, delivered=delivered, cause="payee").model_dump(mode="json"),
        )
        return FilingIntent(command=command, not_before=max(request.observed_at, record.start_at, basis))

    def _deadline_failure(self, record: DeliveryRecord, *, now: int) -> None:
        request = FinalRequest(
            negotiation_id=record.negotiation_id, source_ref="delivery-deadline",
            ended_at=record.deadline, observed_at=record.deadline,
            actor=record.seller, cause="non_delivery", source="delivery_deadline",
            evidence_refs=["delivery-deadline"],
        )
        self.record_end(
            request, now=now, classification=Classification(kind="non_delivery", evidence_refs=request.evidence_refs),
            filing_intent=self.failure_filing(request, now=now, delivered=False),
        )

    def admit(
        self, negotiation_id: str, phase: DeliveryPhase, expected_revision: int, *, now: int,
    ) -> Admission:
        with atomic(self.conn):
            record = self.read(negotiation_id)
            if record.revision != expected_revision:
                return Admission(status="retry", revision=record.revision)
            selected = self.selected_end(negotiation_id)
            missed_deadline = (
                record.committed_at is not None and record.delivery_deadline_seconds is not None and now > record.deadline
                and (record.available_at is None or record.available_at > record.deadline)
            )
            if selected is not None and selected.ended_at <= now and (
                not missed_deadline or selected.ended_at <= record.deadline
            ):
                return Admission(status="ended", revision=record.revision, ended_at=selected.ended_at)
            if missed_deadline:
                self._deadline_failure(record, now=now)
                return Admission(status="ended", revision=self.read(negotiation_id).revision, ended_at=record.deadline)
            if now >= record.term_end:
                return Admission(status="ended", revision=record.revision, ended_at=record.term_end)
            phases = list(DeliveryPhase)
            latest_phase = max((record.phase, phase), key=phases.index)
            if latest_phase != record.phase:
                record = self._write(record.model_copy(update={"phase": latest_phase}))
            return Admission(
                status="admitted", revision=record.revision,
                ended_at=selected.ended_at if selected else None,
            )

    def available(self, negotiation_id: str, *, at: int, expected_revision: int, now: int) -> Admission:
        with atomic(self.conn):
            record = self.read(negotiation_id)
            if record.revision != expected_revision:
                return Admission(status="retry", revision=record.revision)
            if record.available_at is not None and record.available_at != at:
                raise ValueError("durable availability cannot change")
            if at > now:
                raise ValueError("availability cannot be future-dated")
            admission = self.admit(negotiation_id, DeliveryPhase.DISCLOSE, expected_revision, now=now)
            if admission.status != "admitted":
                return admission
            record = self.read(negotiation_id)
            if record.available_at is not None:
                return Admission(status="admitted", revision=record.revision)
            record = self._write(record.model_copy(update={"available_at": at, "progress": "active"}))
            return Admission(status="admitted", revision=record.revision)

    def schedule_physical(self, negotiation_id: str, *, now: int) -> JournalIntent | None:
        selected = self.selected_end(negotiation_id)
        if selected is None:
            return None
        terminate = selected.ended_at <= now
        kind: IntentKind = "terminate" if terminate else "truncate"
        key = "terminate" if terminate else f"truncate:{selected.ended_at}"
        # A termination is independent of later earlier evidence; never restart it.
        old = self.intent(stable_ref(negotiation_id, kind, key))
        if old is not None:
            return old
        return self.journal(
            negotiation_id, kind, key, {"at": selected.ended_at}, not_before=now,
        )

    def physical_progress(self, negotiation_id: str, progress: PhysicalProgress) -> None:
        with atomic(self.conn):
            record = self.read(negotiation_id)
            if record.progress == "released" and progress != "released":
                return
            if record.progress == "tearing_down" and progress in {"unstarted", "active", "end_recorded"}:
                return
            self._write(record.model_copy(update={"progress": progress}))

    def check_and_record(self, negotiation_id: str, operation_key: str, digest: str) -> bool:
        self.conn.execute(
            "INSERT OR IGNORE INTO servicing_operations VALUES (?,?,?)", (negotiation_id, operation_key, digest),
        )
        return self.conn.execute(
            "SELECT digest FROM servicing_operations WHERE negotiation_id=? AND operation_key=?",
            (negotiation_id, operation_key),
        ).fetchone()[0] == digest
