"""VM evidence interpretation over the shared delivery-end journal."""

from __future__ import annotations

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
    ref = "site-event:" + event.event_id
    requests = end.requests(negotiation_id)
    intents = end.intents(negotiation_id)
    for intent in intents:
        commanded = (
            intent.kind == "terminate" and event.reason == intent.intent_ref
            and (event.caller == record.seller or (
                event.caller is None and event.cause == "release"
                and event.source_state in {"reserved", "leased"} and record.available_at is None
            )) and intent.payload["at"] <= event.effective_at
        ) or (
            intent.kind == "truncate" and event.deadline_phase == "lease"
            and event.claimed_deadline == event.effective_at == intent.payload["at"]
        )
        if not commanded:
            continue
        for request in requests:
            if request.ended_at != intent.payload["at"]:
                continue
            controlling = classification_for(end, negotiation_id, request.source_ref)
            if controlling is not None:
                return Classification(
                    kind=controlling.kind,
                    evidence_refs=[ref, request.source_ref, *controlling.evidence_refs],
                ), request.source_ref if controlling.lawful else None

    # Only an exact accepted term deadline is a lawful clock end. An arbitrary
    # earlier site deadline is not allowed to shorten the commercial Agreement.
    if (
        event.deadline_phase == "lease"
        and event.claimed_deadline == event.effective_at == record.term_end
    ):
        return Classification(kind="terms", evidence_refs=[ref]), None
    if (
        event.deadline_phase == "reservation"
        and event.claimed_deadline == event.effective_at
        and record.available_at is None
    ):
        return Classification(kind="provisioning_failure", evidence_refs=[ref]), None
    if event.reason == stable_ref(negotiation_id, "terminate", "terminate"):
        return None, None
    if event.cause in {"termination", "force_release"}:
        return Classification(kind="unentitled_withdrawal", evidence_refs=[ref]), None
    # Release and teardown failures may be consequences of an authority end not
    # observed yet. Keep the correction open until its controlling evidence lands.
    return None, None


def resolve_site_corrections(end: EndSession, negotiation_id: str, *, now: int) -> None:
    """Revisit pending sources without changing their immutable request or basis."""
    items = {item.evidence_id: item for item in EvidenceSession(end.conn).read(negotiation_id).items}
    for request in end.requests(negotiation_id):
        if request.source != "lease_ended" or classification_for(end, negotiation_id, request.source_ref) is not None:
            continue
        item = items[request.source_ref]
        report = SignedLeaseEndedReport.model_validate_json(item.body)
        event = LeaseEndedEvent.model_validate_json(report.payload)
        classification, _ = site_classification(end, negotiation_id, event)
        if classification is None:
            continue
        record = end.read(negotiation_id)
        end.resolve_correction(
            negotiation_id, request.source_ref, record.revision,
            evidence=classification.evidence_refs, classification=classification,
            filing_intent=None if classification.lawful else end.failure_filing(
                request, now=now, delivered=record.available_at is not None,
            ),
        )
