"""VM persistence and report codec over the compute-family end classifier."""

from __future__ import annotations

from arkhai_compute.end_classification import (
    resolve_site_corrections as pending_site_corrections,
    site_classification as classify_journal,
)
from compute_provisioning_contracts import LeaseEndedEvent, SignedLeaseEndedReport
from market_deal_servicing.evidence import EvidenceSession
from market_deal_servicing.journal import Classification, EndSession, stable_ref


def classification_for(end: EndSession, negotiation_id: str, source_ref: str) -> Classification | None:
    row = end.conn.execute(
        """SELECT classification FROM servicing_final_requests
           WHERE negotiation_id=? AND source_ref=?""", (negotiation_id, source_ref),
    ).fetchone()
    return Classification.model_validate_json(row[0]) if row and row[0] else None


def _site_classification(end, negotiation_id, event):
    record = end.read(negotiation_id)
    requests = end.requests(negotiation_id)
    return classify_journal(
        event, seller=record.seller, term_end=record.term_end,
        available=record.available_at is not None, intents=end.intents(negotiation_id),
        requests=requests,
        classifications={request.source_ref: classification_for(end, negotiation_id, request.source_ref)
                         for request in requests},
        termination_ref=stable_ref(negotiation_id, "terminate", "terminate"),
    )


def site_classification(
    end: EndSession, negotiation_id: str, event: LeaseEndedEvent,
) -> tuple[Classification | None, str | None]:
    result = _site_classification(end, negotiation_id, event)
    return (
        Classification(kind=result.kind, evidence_refs=result.evidence_refs) if result.kind else None,
        result.controlling_source_ref,
    )


def resolve_site_corrections(end: EndSession, negotiation_id: str, *, now: int) -> None:
    """Apply shared pending-source decisions in the caller's atomic journal unit."""
    items = {item.evidence_id: item for item in EvidenceSession(end.conn).read(negotiation_id).items}
    requests = end.requests(negotiation_id)

    def report_for(source_ref):
        report = SignedLeaseEndedReport.model_validate_json(items[source_ref].body)
        return LeaseEndedEvent.model_validate_json(report.payload)

    for request, result in pending_site_corrections(
        requests,
        classifications={request.source_ref: classification_for(end, negotiation_id, request.source_ref)
                         for request in requests},
        report_for=report_for, classify=lambda event: _site_classification(end, negotiation_id, event),
    ):
        classification = Classification(kind=result.kind, evidence_refs=result.evidence_refs)
        record = end.read(negotiation_id)
        end.resolve_correction(
            negotiation_id, request.source_ref, record.revision,
            evidence=result.evidence_refs, classification=classification,
            controlling_source_ref=result.controlling_source_ref,
            filing_intent=None if classification.lawful or result.controlling_source_ref else end.failure_filing(
                request, now=now, delivered=record.available_at is not None,
            ),
        )
