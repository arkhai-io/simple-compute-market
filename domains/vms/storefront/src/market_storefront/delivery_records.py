"""VM commitment registration and delivery admission in the caller transaction."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime

from market_core.schemas import Agreement
from market_deal_lifecycle.adapters import PaymentSelector
from market_deal_lifecycle.delivery import DeliveryPhase
from market_deal_lifecycle.terms import decode_terms
from market_deal_servicing import DeliveryRecord, EndSession, SellerDeal, SellerSession
from market_deal_servicing.journal import FinalRequest
from market_identity import Identity


def register_delivery(conn, negotiation_id):
    """Register only verified commitment evidence, in its caller's transaction."""
    if conn.execute("SELECT 1 FROM servicing_delivery WHERE negotiation_id=?", (negotiation_id,)).fetchone():
        return
    row = conn.execute(
        """SELECT t.agreement_bytes,t.settlement_data,e.settlement_ref,e.evidence_json
           FROM negotiation_threads t JOIN vm_settlement_evidence e USING(negotiation_id)
           WHERE t.negotiation_id=? AND e.status IN ('verified','refunding','refunded')""",
        (negotiation_id,),
    ).fetchone()
    if row is None or row[0] is None:
        raise ValueError("delivery requires an accepted Agreement and verified evidence")
    agreement = Agreement.model_validate_json(row[0])
    option = agreement.settlement
    if option is None:
        raise ValueError("delivery requires settlement")
    terms = decode_terms(option.lifecycle)
    source = json.loads(row[3])["source"]
    receipt = source.get("receipt", {}).get("receipt", {})
    accepted = int(datetime.fromisoformat(agreement.accepted_at.replace("Z", "+00:00")).timestamp())
    committed = receipt.get("approvedAt", accepted)
    start = int(datetime.fromisoformat(agreement.start_utc.replace("Z", "+00:00")).timestamp())
    commitment = row[2] or hashlib.sha256(row[0]).hexdigest()
    EndSession(conn).register(DeliveryRecord(
        negotiation_id=negotiation_id, seller=Identity.model_validate(agreement.seller),
        commitment_ref=commitment, start_at=start, term_end=start + agreement.duration_seconds,
        committed_at=committed,
        delivery_deadline_seconds=terms.delivery_deadline_seconds if terms else None,
    ))
    SellerSession(conn).register(SellerDeal(
        negotiation_id=negotiation_id, commitment_ref=commitment, domain="vms",
        buyer=Identity.model_validate(agreement.buyer), payment=PaymentSelector(option.settlement_schema),
        dispute=terms.adjudication.dispute if terms else None, once_only=True,
        entitlements=terms.early_termination.model_dump(mode="json")["entitlements"]
        if terms and terms.early_termination else {},
    ))


def record_delivery_end(conn, negotiation_id, *, source_ref, cause, now):
    register_delivery(conn, negotiation_id)
    end = EndSession(conn)
    prior = next((item for item in end.requests(negotiation_id) if item.source_ref == source_ref), None)
    if prior is None:
        end.record_end(FinalRequest(
            negotiation_id=negotiation_id, source_ref=source_ref, ended_at=now,
            observed_at=now, actor=end.read(negotiation_id).seller,
            cause=cause, source="settlement", evidence_refs=[source_ref],
        ), now=now, pending_classification=True)
    return end.view(negotiation_id)


def admit_delivery(conn, negotiation_id, phase):
    """Order admission and the delivery record it permits in one write."""
    register_delivery(conn, negotiation_id)
    end = EndSession(conn)
    record = end.read(negotiation_id)
    return end.admit(negotiation_id, phase, record.revision, now=int(time.time())).status == "admitted"

