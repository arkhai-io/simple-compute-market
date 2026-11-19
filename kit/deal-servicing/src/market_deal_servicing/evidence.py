"""Exact seller evidence, independent of transport replay and financial state."""

from __future__ import annotations

import asyncio
import base64
import sqlite3
from collections.abc import Callable, Iterator
from typing import TypeVar
from contextlib import contextmanager
from pathlib import Path

from market_deal_lifecycle.evidence import CommitmentAttempt, EvidenceRecord
from market_deal_lifecycle.terms import LifecycleTerms, encode_terms
from market_deal_lifecycle_contracts.models import EvidenceItem, Instant, WireModel
from market_identity import Identity, canonical_json


T = TypeVar("T")


async def in_transaction(path: str | Path, operation: Callable[[sqlite3.Connection], T]) -> T:
    """Run a bounded database unit off the event loop; callbacks perform no I/O."""
    def run() -> T:
        with transaction(path) as conn:
            return operation(conn)
    return await asyncio.to_thread(run)


class RetentionObservation(WireModel):
    """Complete observations, not estimated payout times or a local payment ledger."""

    observed_at: Instant
    delivery_ended_at: Instant | None = None
    recovered_at: Instant | None = None
    payouts: dict[str, Instant | None]
    cases: dict[str, Instant | None]
    open_extensions: list[str]
    complete: bool = False

    def boundary(self) -> int | None:
        if (
            not self.complete or self.open_extensions or not self.payouts
            or self.delivery_ended_at is None or self.recovered_at is None
            or any(at is None for at in (*self.payouts.values(), *self.cases.values()))
        ):
            return None
        return max(
            self.delivery_ended_at, self.recovered_at,
            *(at for at in self.payouts.values() if at is not None),
            *(at for at in self.cases.values() if at is not None),
        )


class EvidenceSession:
    """Borrow a storefront SQLite session; never commit or roll back its writes.

    Capture and acceptance can share the transaction which commits the Agreement.
    The signed transport calls capture only after verification, retaining the body
    and proof headers before parsing. Administrative acceptance supplies its author
    independently of the principal who signed the buyer's message. The session
    issues no DDL: its tables are the storefront chain's
    (``market_deal_servicing.schema``).
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def _ensure(self, negotiation_id: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO servicing_evidence_deals(negotiation_id) VALUES (?)",
            (negotiation_id,),
        )

    def put(self, negotiation_id: str, item: EvidenceItem) -> None:
        self._ensure(negotiation_id)
        existing = self.conn.execute(
            "SELECT item FROM servicing_evidence_items WHERE negotiation_id=? AND evidence_id=?",
            (negotiation_id, item.evidence_id),
        ).fetchone()
        if existing:
            previous = EvidenceItem.model_validate_json(existing[0])
            if previous.model_dump(exclude={"recorded_at"}) != item.model_dump(exclude={"recorded_at"}):
                raise ValueError("evidence ID retry changes content")
            return
        self.conn.execute(
            "INSERT INTO servicing_evidence_items(negotiation_id,evidence_id,item) VALUES (?,?,?)",
            (negotiation_id, item.evidence_id, item.model_dump_json()),
        )

    def capture(
        self, negotiation_id: str, *, evidence_id: str, body: bytes,
        headers: dict[str, str], context: dict, recorded_at: int,
    ) -> None:
        self.put(negotiation_id, EvidenceItem(
            evidence_id=evidence_id, kind="verified_market_envelope",
            classification="independent", recorded_at=recorded_at,
            body=base64.b64encode(body), headers=headers, context=context,
        ))

    def accept(
        self, negotiation_id: str, *, message_id: str, accepted_by: Identity,
        expires_at: int, terms: LifecycleTerms | None = None,
    ) -> None:
        if not isinstance(expires_at, int) or isinstance(expires_at, bool) or expires_at < 0:
            raise ValueError("acceptance expiry must be nonnegative Unix seconds")
        if not self.conn.execute(
            "SELECT 1 FROM servicing_evidence_items WHERE negotiation_id=? AND evidence_id=?",
            (negotiation_id, message_id),
        ).fetchone():
            raise ValueError("acceptance requires the captured buyer message")
        row = self.conn.execute(
            "SELECT accepted_by,acceptance_expires_at,lifecycle FROM servicing_evidence_deals WHERE negotiation_id=?",
            (negotiation_id,),
        ).fetchone()
        author = accepted_by.model_dump_json()
        lifecycle = canonical_json(encode_terms(terms)).decode() if terms is not None else None
        if row[0] is not None and tuple(row) != (author, expires_at, lifecycle):
            raise ValueError("acceptance retry changes author or expiry")
        self.conn.execute(
            "UPDATE servicing_evidence_deals SET accepted_by=?,acceptance_expires_at=?,lifecycle=? WHERE negotiation_id=?",
            (author, expires_at, lifecycle, negotiation_id),
        )

    def record_commitment(self, negotiation_id: str, attempt: CommitmentAttempt) -> None:
        self._ensure(negotiation_id)
        old = self.conn.execute(
            "SELECT superseded FROM servicing_evidence_commitments WHERE negotiation_id=? AND commitment_ref=?",
            (negotiation_id, attempt.commitment_ref),
        ).fetchone()
        if old and old[0] and not attempt.superseded:
            raise ValueError("a superseded commitment cannot become live")
        try:
            self.conn.execute(
                """INSERT INTO servicing_evidence_commitments VALUES (?,?,?)
                   ON CONFLICT(negotiation_id,commitment_ref)
                   DO UPDATE SET superseded=excluded.superseded""",
                (negotiation_id, attempt.commitment_ref, int(attempt.superseded)),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("negotiation already has a live commitment") from exc

    def read(self, negotiation_id: str) -> EvidenceRecord:
        row = self.conn.execute(
            "SELECT acceptance_expires_at FROM servicing_evidence_deals WHERE negotiation_id=?",
            (negotiation_id,),
        ).fetchone()
        return EvidenceRecord(
            negotiation_id=negotiation_id,
            acceptance_expires_at=row[0] if row else None,
            commitments=[
                CommitmentAttempt(commitment_ref=ref, superseded=bool(superseded))
                for ref, superseded in self.conn.execute(
                    """SELECT commitment_ref,superseded FROM servicing_evidence_commitments
                       WHERE negotiation_id=? ORDER BY rowid""", (negotiation_id,),
                )
            ],
            items=[
                EvidenceItem.model_validate_json(item) for (item,) in self.conn.execute(
                    """SELECT item FROM servicing_evidence_items
                       WHERE negotiation_id=? ORDER BY position""", (negotiation_id,),
                )
            ],
        )

    def negotiations(self) -> tuple[str, ...]:
        return tuple(row[0] for row in self.conn.execute(
            "SELECT negotiation_id FROM servicing_evidence_deals ORDER BY negotiation_id",
        ))

    def observe(self, negotiation_id: str, observation: RetentionObservation) -> None:
        self._ensure(negotiation_id)
        row = self.conn.execute(
            "SELECT observation FROM servicing_evidence_deals WHERE negotiation_id=?", (negotiation_id,),
        ).fetchone()
        if row[0] is not None:
            previous = RetentionObservation.model_validate_json(row[0])
            if observation.observed_at < previous.observed_at:
                raise ValueError("retention observation regresses")
        self.conn.execute(
            "UPDATE servicing_evidence_deals SET observation=? WHERE negotiation_id=?",
            (observation.model_dump_json(), negotiation_id),
        )

    def prune(
        self, negotiation_id: str, *, now: int, has_adapter: bool,
    ) -> bool:
        row = self.conn.execute(
            "SELECT lifecycle FROM servicing_evidence_deals WHERE negotiation_id=?", (negotiation_id,),
        ).fetchone()
        terms = LifecycleTerms.model_validate_json(row[0]) if row and row[0] else None
        if terms is None or not has_adapter:
            return False
        record = self.read(negotiation_id)
        if not record.commitments:
            boundary = record.acceptance_expires_at
        else:
            row = self.conn.execute(
                "SELECT observation FROM servicing_evidence_deals WHERE negotiation_id=?",
                (negotiation_id,),
            ).fetchone()
            boundary = RetentionObservation.model_validate_json(row[0]).boundary() if row and row[0] else None
        if boundary is None or now < boundary + terms.adjudication.dispute_window_seconds:
            return False
        self.delete(negotiation_id)
        return True

    def delete(self, negotiation_id: str) -> None:
        for table in (
            "servicing_evidence_items", "servicing_evidence_commitments", "servicing_evidence_deals",
            "servicing_final_requests", "servicing_intents", "servicing_delivery", "servicing_watch",
            "servicing_observations",
        ):
            if not self.conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,),
            ).fetchone():
                continue
            self.conn.execute(f"DELETE FROM {table} WHERE negotiation_id=?", (negotiation_id,))


@contextmanager
def transaction(path: str | Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


class SQLiteEvidenceStore:
    """Async evidence port over a role-owned database, separate from replay tables."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _call(self, method: str, *args, **kwargs):
        with transaction(self.path) as conn:
            return getattr(EvidenceSession(conn), method)(*args, **kwargs)

    async def put(self, negotiation_id: str, item: EvidenceItem) -> None:
        await asyncio.to_thread(self._call, "put", negotiation_id, item)

    async def record_commitment(self, negotiation_id: str, attempt: CommitmentAttempt) -> None:
        await asyncio.to_thread(self._call, "record_commitment", negotiation_id, attempt)

    async def read(self, negotiation_id: str) -> EvidenceRecord:
        return await asyncio.to_thread(self._call, "read", negotiation_id)

    async def negotiations(self) -> tuple[str, ...]:
        return await asyncio.to_thread(self._call, "negotiations")

    async def observe(self, negotiation_id: str, observation: RetentionObservation) -> None:
        await asyncio.to_thread(self._call, "observe", negotiation_id, observation)

    async def prune(self, negotiation_id: str, *, now: int, has_adapter: bool) -> bool:
        return await asyncio.to_thread(self._call, "prune", negotiation_id, now=now, has_adapter=has_adapter)

    async def delete(self, negotiation_id: str) -> None:
        await asyncio.to_thread(self._call, "delete", negotiation_id)
