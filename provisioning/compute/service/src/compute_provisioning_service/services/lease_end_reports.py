"""Signed lease-end reports: kept as the site's evidence, delivered to the
storefront peer by a consumer of ``site.lease_ended``.

``site.lease_ended``'s record-time hook signs the lease end's statement with
the service's identity in the transaction that records the end, and keeps it in
``lease_end_reports``, retained under its own setting and never pruned before
its event: the authenticated lease read serves it from there, whatever has
become of the event.

The lease-end report consumer holds one destination per configured storefront
peer, named for the peer's URL (``event_names.peer_destination``). A peer
answering 404, 405, 501 or an explicit ``unsupported`` parks its destination
until an administrator resumes it, and resuming delivers the reports it missed whose events are still retained; any
other failure is retried with backoff; a report the table does not hold is
abandoned to the finally sink, since no retry can send it. A newly configured peer is a new
destination, starting at the latest committed event, so no report recorded
before it reaches it; the destination of a peer the configuration does not name
is retired, its undelivered reports — those not yet read included — going to the
finally sink, the log. Each
report is sent under its event's identity, so a lost acknowledgement is retried
as the same request.
"""

from __future__ import annotations

import hashlib

import injected_time
from compute_provisioning_contracts import (
    LEASE_ENDED_CALLBACK,
    LeaseEndedEvent,
    SignedLeaseEndedReport,
    sign_lease_end,
)
from eventing import (
    AbandonDelivery,
    Consumer,
    Envelope,
    ParkDestination,
    PrunedTable,
    RecordHook,
    RetryPolicy,
)
from market_identity import Signer, canonical_json
from market_site.events import SITE_LEASE_ENDED
from sqlalchemy.orm import Session, sessionmaker
from storefront_client import StorefrontClientError

from compute_provisioning_service.db.models import LeaseEndReport
from compute_provisioning_service.event_names import LEASE_END_REPORT_CONSUMER, peer_destination
from compute_provisioning_service.services.deal_event_sink import StorefrontPeer

#: The table the signed reports are kept in, the column they age by, and the
#: column naming the event each is kept for.
LEASE_END_REPORTS_TABLE = PrunedTable(
    "lease_end_reports", "created_at", event_column="envelope_id"
)

#: The HTTP statuses of a storefront that does not take lease-end reports.
UNSUPPORTED_STATUSES = frozenset({404, 405, 501})


def lease_end_report_hook(signer: Signer) -> RecordHook:
    """``site.lease_ended``'s record-time hook: sign the lease end's statement
    and keep it, in the recording transaction, so the end and its signed report
    commit or roll back together."""

    def apply(session: Session, envelope: Envelope) -> None:
        event = LeaseEndedEvent.model_validate(envelope.details)
        report = sign_lease_end(event, signer)
        session.add(
            LeaseEndReport(
                event_id=event.event_id,
                capacity_reservation_id=event.capacity_reservation_id,
                report=canonical_json(report).decode(),
                envelope_id=envelope.id,
            )
        )

    return RecordHook(apply, tables=(LEASE_END_REPORTS_TABLE,))


class LeaseEndReports:
    """The signed reports a lease's ends recorded, as the lease read serves them."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def read(self, capacity_reservation_id: str) -> list[SignedLeaseEndedReport]:
        with self._session_factory() as db:
            return [
                SignedLeaseEndedReport.model_validate_json(row.report)
                for row in db.query(LeaseEndReport)
                .filter_by(capacity_reservation_id=capacity_reservation_id)
                .order_by(LeaseEndReport.created_at, LeaseEndReport.event_id)
            ]


class LeaseEndReportDestination:
    """Delivers a ``site.lease_ended`` event's stored signed report to the
    storefront peer, exactly as it was signed."""

    def __init__(self, session_factory: sessionmaker[Session], peer: StorefrontPeer) -> None:
        self._session_factory = session_factory
        self._peer = peer

    def deliver(self, envelope: Envelope) -> None:
        event_id = str(envelope.details["event_id"])
        with self._session_factory() as db:
            row = db.get(LeaseEndReport, event_id)
            if row is None:
                raise AbandonDelivery(f"the signed report of lease end {event_id} is not retained")
            report = SignedLeaseEndedReport.model_validate_json(row.report)
            capacity_reservation_id = str(row.capacity_reservation_id)
        path = LEASE_ENDED_CALLBACK["path"].format(capacity_reservation_id=capacity_reservation_id)
        try:
            answer = self._peer.client().authenticated_request(
                "POST",
                path,
                role="service",
                operation=LEASE_ENDED_CALLBACK["operation"],
                resource=capacity_reservation_id,
                body=report.model_dump(mode="json"),
                request_id="lease-end-" + hashlib.sha256(event_id.encode()).hexdigest(),
            )
        except StorefrontClientError as exc:
            if exc.status_code in UNSUPPORTED_STATUSES:
                raise ParkDestination(f"unsupported: HTTP {exc.status_code}") from exc
            raise
        if answer.get("status") == "unsupported":
            raise ParkDestination("unsupported")


def lease_end_report_consumer(
    session_factory: sessionmaker[Session], peer: StorefrontPeer, *, runner: str
) -> Consumer:
    """The lease-end report consumer over the configured storefront peer, which
    retries without limit. With no peer configured it has no destination: a
    stored one is retired."""
    name = peer_destination(peer.url) if peer.url else None
    destinations = {name: LeaseEndReportDestination(session_factory, peer)} if name else {}

    def select(envelope: Envelope, candidates: frozenset[str]) -> frozenset[str]:
        return candidates if envelope.kind == SITE_LEASE_ENDED.name else frozenset()

    return Consumer(
        LEASE_END_REPORT_CONSUMER,
        session_factory=session_factory,
        destinations=destinations,
        clock=injected_time.now_datetime,
        retry=RetryPolicy(max_age=None),
        select=select,
        runner=runner,
    )


__all__ = [
    "LEASE_END_REPORTS_TABLE",
    "LEASE_END_REPORT_CONSUMER",
    "UNSUPPORTED_STATUSES",
    "LeaseEndReportDestination",
    "LeaseEndReports",
    "lease_end_report_consumer",
    "lease_end_report_hook",
    "peer_destination",
]
