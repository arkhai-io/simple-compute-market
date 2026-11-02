"""Event-keyed signed report delivery, independent of proven capacity release."""

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Literal

from compute_provisioning_contracts import LeaseEndedEvent, SignedLeaseEndedReport, sign_lease_end
from market_identity import Signer, canonical_json
from sqlalchemy.orm import Session

from compute_provisioning_service.db.models import LeaseEndReportOutbox

ReportDelivery = Literal["delivered", "unsupported", "retry"]


class LeaseEndReports:
    def __init__(self, session_factory, *, signer: Signer, peer: str):
        self.session_factory = session_factory
        self.signer = signer
        self.peer = peer

    def record(self, db: Session, payload: dict) -> None:
        """Borrow the ending transaction; signing and reservation precede commit."""
        event = LeaseEndedEvent.model_validate(payload)
        if db.get(LeaseEndReportOutbox, event.event_id) is not None:
            return
        parked = db.query(LeaseEndReportOutbox).filter_by(peer=self.peer, parked=True).first() is not None
        report = sign_lease_end(event, self.signer)
        db.add(LeaseEndReportOutbox(
            event_id=event.event_id, capacity_reservation_id=event.capacity_reservation_id,
            peer=self.peer, report=canonical_json(report).decode(), parked=parked,
        ))

    def read(self, capacity_reservation_id: str) -> list[SignedLeaseEndedReport]:
        with self.session_factory() as db:
            return [SignedLeaseEndedReport.model_validate_json(row.report) for row in db.query(
                LeaseEndReportOutbox,
            ).filter_by(capacity_reservation_id=capacity_reservation_id).order_by(
                LeaseEndReportOutbox.created_at, LeaseEndReportOutbox.event_id,
            )]

    async def drain(self, deliver: Callable[[SignedLeaseEndedReport], Awaitable[ReportDelivery]]) -> None:
        with self.session_factory() as db:
            pending = [(row.event_id, row.report, row.peer) for row in db.query(LeaseEndReportOutbox).filter(
                LeaseEndReportOutbox.delivered_at.is_(None), LeaseEndReportOutbox.parked.is_(False),
            ).order_by(LeaseEndReportOutbox.created_at, LeaseEndReportOutbox.event_id).limit(100)]
        for event_id, body, peer in pending:
            # Never send an old event to a different configured owner after a
            # reconfiguration. Pull still exposes the original signed statement.
            if peer != self.peer:
                continue
            with self.session_factory() as db:
                row = db.get(LeaseEndReportOutbox, event_id)
                if row.parked or row.delivered_at is not None:
                    continue
            try:
                result = await deliver(SignedLeaseEndedReport.model_validate_json(body))
            except Exception:
                result = "retry"
            with self.session_factory() as db:
                row = db.get(LeaseEndReportOutbox, event_id)
                row.attempt_count += 1
                row.last_attempted_at = datetime.now(timezone.utc)
                row.last_error = None if result == "delivered" else result
                if result == "delivered":
                    row.delivered_at = row.last_attempted_at
                elif result == "unsupported":
                    db.query(LeaseEndReportOutbox).filter_by(peer=peer).update({"parked": True})
                db.commit()

    def resume_peer(self) -> None:
        """Explicitly re-enable push after the coordinated receiver upgrade."""
        with self.session_factory() as db:
            db.query(LeaseEndReportOutbox).filter_by(peer=self.peer).update({"parked": False})
            db.commit()
