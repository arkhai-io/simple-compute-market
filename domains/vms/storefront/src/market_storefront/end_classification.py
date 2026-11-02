"""VM evidence interpretation over the shared delivery-end journal."""

from __future__ import annotations

from arkhai_compute.end_classification import CommandEnd, classify_site_end
from compute_provisioning_contracts import LeaseEndedEvent, SignedLeaseEndedReport
from market_deal_servicing.evidence import EvidenceSession
from market_deal_servicing.journal import Classification, EndSession, stable_ref


def classification_for(end: EndSession, negotiation_id: str, source_ref: str) -> Classification | None:
    row = end.conn.execute(
        """SELECT classification FROM servicing_final_requests
           WHERE negotiation_id=? AND source_ref=?""", (negotiation_id, source_ref),
    ).fetchone()
    return Classification.model_validate_json(row[0]) if row and row[0] else None


def site_classification(
    end: EndSession, negotiation_id: str, event: LeaseEndedEvent,
) -> tuple[Classification | None, str | None]:
    """Match a signed site statement to an actual recorded physical command.

    A site's end cause alone cannot prove a payment entitlement. A termination
    echoes our stable command key and caller; expiry can instead confirm the
    precise deadline we asked the site to enforce. Earlier independent failures
    remain separate sources, even when this report confirms a lawful command.
    """
    record = end.read(negotiation_id)
    commands = []
    for intent in end.intents(negotiation_id):
        if intent.kind not in {"terminate", "truncate"}:
            continue
        for request in end.requests(negotiation_id):
            if request.ended_at != intent.payload["at"]:
                continue
            classification = classification_for(end, negotiation_id, request.source_ref)
            if classification is None:
                continue
            commands.append(CommandEnd(
                intent.intent_ref, intent.kind, intent.payload["at"], request.source_ref,
                classification.kind if classification else None,
                classification.evidence_refs if classification else [],
            ))
    result = classify_site_end(
        event, seller=record.seller, term_end=record.term_end,
        available=record.available_at is not None, commands=commands,
        termination_ref=stable_ref(negotiation_id, "terminate", "terminate"),
    )
    return (
        Classification(kind=result.kind, evidence_refs=result.evidence_refs) if result.kind else None,
        result.controlling_source_ref,
    )


def resolve_site_corrections(end: EndSession, negotiation_id: str, *, now: int) -> None:
    """Revisit pending sources without changing their immutable request or basis."""
    items = {item.evidence_id: item for item in EvidenceSession(end.conn).read(negotiation_id).items}
    for request in end.requests(negotiation_id):
        if request.source != "lease_ended" or classification_for(end, negotiation_id, request.source_ref) is not None:
            continue
        item = items[request.source_ref]
        report = SignedLeaseEndedReport.model_validate_json(item.body)
        event = LeaseEndedEvent.model_validate_json(report.payload)
        classification, controlling = site_classification(end, negotiation_id, event)
        if classification is None:
            continue
        record = end.read(negotiation_id)
        end.resolve_correction(
            negotiation_id, request.source_ref, record.revision,
            evidence=classification.evidence_refs, classification=classification,
            filing_intent=None if classification.lawful or controlling else end.failure_filing(
                request, now=now, delivered=record.available_at is not None,
            ),
        )
