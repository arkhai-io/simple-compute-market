"""Transactional file-backed evidence, independent of authentication replay storage."""

from __future__ import annotations

import base64
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3

from market_deal_lifecycle.evidence import CommitmentAttempt, EvidenceRecord
from market_deal_lifecycle_contracts.models import EvidenceItem
from market_identity import AuthenticatedResponse, CapturedEnvelope

from .ending import BuyerEndJournal


class FileEvidenceStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / "evidence.sqlite3"
        self.path.touch(mode=0o600, exist_ok=True)
        self.end_journal = BuyerEndJournal(self.path)
        with self._connection() as db:
            db.execute("CREATE TABLE IF NOT EXISTS evidence (negotiation_id TEXT PRIMARY KEY, record TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS operations (negotiation_id TEXT, operation_key TEXT, digest TEXT NOT NULL, PRIMARY KEY (negotiation_id, operation_key))")
            db.execute("CREATE TABLE IF NOT EXISTS requests (request_id TEXT PRIMARY KEY, negotiation_id TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS commitments (negotiation_id TEXT, commitment_ref TEXT, acceptance_id TEXT NOT NULL, PRIMARY KEY (negotiation_id, commitment_ref))")

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _read(db, negotiation_id: str) -> EvidenceRecord:
        row = db.execute("SELECT record FROM evidence WHERE negotiation_id = ?", (negotiation_id,)).fetchone()
        if row is None:
            return EvidenceRecord(negotiation_id=negotiation_id, commitments=[], items=[])
        return EvidenceRecord.model_validate_json(row[0])

    @staticmethod
    def _save(db, record: EvidenceRecord) -> None:
        db.execute("INSERT OR REPLACE INTO evidence VALUES (?, ?)",
                   (record.negotiation_id, record.model_dump_json()))

    @staticmethod
    def _append(record: EvidenceRecord, item: EvidenceItem) -> EvidenceRecord:
        for existing in record.items:
            if existing.evidence_id == item.evidence_id:
                if existing != item:
                    raise ValueError("evidence ID reused with changed content")
                return record
        return record.model_copy(update={"items": [*record.items, item]})

    def capture(self, captured: CapturedEnvelope) -> None:
        envelope = captured.envelope
        payload = json.loads(captured.body) if captured.body else {}
        negotiation_id = payload.get("negotiation_id") if isinstance(payload, dict) else None
        # Peer acknowledgements and empty-body reads identify the deal in the
        # signed route context, not necessarily in their response payload.
        if not negotiation_id and envelope.operation in {
            "negotiate_continue", "lifecycle_peer", "lifecycle_buyer_read",
        }:
            negotiation_id = envelope.resource
        with self._connection() as db:
            if not negotiation_id:
                row = db.execute("SELECT negotiation_id FROM requests WHERE request_id = ?", (envelope.request_id,)).fetchone()
                negotiation_id = row[0] if row else None
            if not negotiation_id:
                return
            if not isinstance(negotiation_id, str):
                raise ValueError("captured negotiation ID must be a string")
            db.execute("INSERT OR REPLACE INTO requests VALUES (?, ?)", (envelope.request_id, negotiation_id))
            context = envelope.model_dump(mode="json")
            context["expected_principals"] = captured.expected_principals.model_dump(mode="json")
            context["producer"] = envelope.principal.model_dump(mode="json")
            context["digest"] = hashlib.sha256(captured.body).hexdigest()
            identity = json.dumps([context, dict(captured.headers)], sort_keys=True).encode() + captured.body
            item = EvidenceItem(
                evidence_id=hashlib.sha256(identity).hexdigest(),
                kind="signed_response" if isinstance(envelope, AuthenticatedResponse) else "signed_request",
                classification="seller_assertion" if envelope.role == "seller" else "buyer_observation",
                recorded_at=envelope.timestamp,
                body=base64.b64encode(captured.body), headers=dict(captured.headers), context=context,
            )
            record = self._append(self._read(db, negotiation_id), item)
            self._save(db, record)

    async def check_and_record(self, negotiation_id: str, operation_key: str, digest: str) -> bool:
        """Persist the command before authority I/O, including across restarts."""
        with self._connection() as db:
            row = db.execute("SELECT digest FROM operations WHERE negotiation_id = ? AND operation_key = ?",
                             (negotiation_id, operation_key)).fetchone()
            if row is not None:
                return row[0] == digest
            db.execute("INSERT INTO operations VALUES (?, ?, ?)", (negotiation_id, operation_key, digest))
            return True

    async def put(self, negotiation_id: str, item: EvidenceItem) -> None:
        with self._connection() as db:
            self._save(db, self._append(self._read(db, negotiation_id), item))

    async def record_commitment(self, negotiation_id: str, attempt: CommitmentAttempt) -> None:
        self.remember_commitment(negotiation_id, attempt.commitment_ref, superseded=attempt.superseded)

    def remember_commitment(self, negotiation_id: str, commitment_ref: str, *, superseded: bool = False) -> None:
        attempt = CommitmentAttempt(commitment_ref=commitment_ref, superseded=superseded)
        with self._connection() as db:
            record = self._read(db, negotiation_id)
            attempts = {old.commitment_ref: old for old in record.commitments}
            previous = attempts.get(commitment_ref)
            if previous is not None and previous.superseded:
                attempt = previous
            if not attempt.superseded:
                attempts = {ref: old.model_copy(update={"superseded": True}) for ref, old in attempts.items()}
            attempts[attempt.commitment_ref] = attempt
            self._save(db, record.model_copy(update={"commitments": list(attempts.values())}))
            acceptances = self._acceptances(record)
            if acceptances:
                db.execute("INSERT OR IGNORE INTO commitments VALUES (?, ?, ?)",
                           (negotiation_id, commitment_ref, acceptances[-1].evidence_id))

    @staticmethod
    def _acceptances(record: EvidenceRecord) -> list[EvidenceItem]:
        acceptances = []
        for item in record.items:
            if item.kind != "signed_response" or item.context.get("role") != "seller":
                continue
            try:
                payload = json.loads(item.body)
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(payload, dict) and payload.get("action") == "accept" and isinstance(payload.get("agreement_bytes"), str):
                acceptances.append(item)
        return acceptances

    async def case_material(self, negotiation_id: str, commitment_ref: str | None = None) -> tuple[EvidenceRecord, str, EvidenceItem]:
        with self._connection() as db:
            record = self._read(db, negotiation_id)
            attempts = [a for a in record.commitments if
                        (a.commitment_ref == commitment_ref if commitment_ref is not None else not a.superseded)]
            if len(attempts) != 1:
                raise ValueError("case export requires one retained commitment")
            selected = attempts[0].commitment_ref
            row = db.execute("SELECT acceptance_id FROM commitments WHERE negotiation_id = ? AND commitment_ref = ?",
                             (negotiation_id, selected)).fetchone()
            if row is None:
                raise ValueError("commitment has no retained acceptance binding")
            acceptance = next((item for item in record.items if item.evidence_id == row[0]), None)
            if acceptance is None:
                raise ValueError("commitment acceptance is missing")
            return record, selected, acceptance

    async def set_acceptance_expiry(self, negotiation_id: str, expires_at: int) -> None:
        with self._connection() as db:
            record = self._read(db, negotiation_id)
            self._save(db, record.model_copy(update={"acceptance_expires_at": expires_at}))

    async def read(self, negotiation_id: str) -> EvidenceRecord:
        with self._connection() as db:
            return self._read(db, negotiation_id)

    async def negotiations(self) -> tuple[str, ...]:
        with self._connection() as db:
            return tuple(row[0] for row in db.execute("SELECT negotiation_id FROM evidence ORDER BY negotiation_id"))

    async def delete_if_unchanged(self, expected: EvidenceRecord) -> bool:
        with self._connection() as db:
            if self._read(db, expected.negotiation_id) != expected:
                return False
            db.execute("DELETE FROM buyer_delivery_ends WHERE negotiation_id = ?", (expected.negotiation_id,))
            db.execute("DELETE FROM evidence WHERE negotiation_id = ?", (expected.negotiation_id,))
            db.execute("DELETE FROM requests WHERE negotiation_id = ?", (expected.negotiation_id,))
            db.execute("DELETE FROM commitments WHERE negotiation_id = ?", (expected.negotiation_id,))
            return True

    async def delete(self, negotiation_id: str) -> None:
        with self._connection() as db:
            db.execute("DELETE FROM buyer_delivery_ends WHERE negotiation_id = ?", (negotiation_id,))
            db.execute("DELETE FROM evidence WHERE negotiation_id = ?", (negotiation_id,))
            db.execute("DELETE FROM requests WHERE negotiation_id = ?", (negotiation_id,))
            db.execute("DELETE FROM commitments WHERE negotiation_id = ?", (negotiation_id,))
