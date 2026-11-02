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


class FileEvidenceStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / "evidence.sqlite3"
        self.path.touch(mode=0o600, exist_ok=True)
        with self._connection() as db:
            db.execute("CREATE TABLE IF NOT EXISTS evidence (negotiation_id TEXT PRIMARY KEY, record TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS requests (request_id TEXT PRIMARY KEY, negotiation_id TEXT NOT NULL)")

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
        if not negotiation_id and envelope.operation == "negotiate_continue":
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
            if not attempt.superseded:
                attempts = {ref: old.model_copy(update={"superseded": True}) for ref, old in attempts.items()}
            attempts[attempt.commitment_ref] = attempt
            self._save(db, record.model_copy(update={"commitments": list(attempts.values())}))

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
            db.execute("DELETE FROM evidence WHERE negotiation_id = ?", (expected.negotiation_id,))
            db.execute("DELETE FROM requests WHERE negotiation_id = ?", (expected.negotiation_id,))
            return True

    async def delete(self, negotiation_id: str) -> None:
        with self._connection() as db:
            db.execute("DELETE FROM evidence WHERE negotiation_id = ?", (negotiation_id,))
            db.execute("DELETE FROM requests WHERE negotiation_id = ?", (negotiation_id,))
