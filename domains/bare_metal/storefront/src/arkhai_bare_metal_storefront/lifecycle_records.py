"""Accepted bare-metal bindings in the caller's delivery-ordering transaction."""

import hashlib
import json
from datetime import datetime
from contextvars import ContextVar

from market_arkhai_payments import ARKHAI_PAYMENTS_MECHANISM, PaymentSettlementData
from market_core.schemas import Agreement
from market_deal_lifecycle.adapters import PaymentSelector
from market_deal_lifecycle.terms import decode_terms
from market_deal_servicing import DeliveryRecord, EndSession, EvidenceSession, SellerDeal, SellerSession, create_schema
from market_identity import CapturedEnvelope, Identity, canonical_json


# Request-local capture follows acceptance into asyncio.to_thread without ever
# sharing one buyer's envelope with another concurrent negotiation.
acceptance_envelope: ContextVar[CapturedEnvelope | None] = ContextVar("bare_metal_acceptance", default=None)


def register_agreement(conn, agreement_bytes: bytes, settlement_data=None, *, capture=False) -> None:
    agreement = Agreement.model_validate_json(agreement_bytes)
    option = agreement.settlement
    if option is None:
        return
    terms = decode_terms(option.lifecycle)
    commitment = hashlib.sha256(canonical_json(json.loads(agreement_bytes))).hexdigest()
    expiry = None
    if option.settlement_schema == ARKHAI_PAYMENTS_MECHANISM:
        data = PaymentSettlementData.parse(settlement_data)
        data.require_bound_to(json.loads(agreement_bytes))
        commitment = data.transaction_id
        expiry = data.mandate.expires
    start = int(datetime.fromisoformat(agreement.start_utc.replace("Z", "+00:00")).timestamp())
    create_schema(conn)
    captured = acceptance_envelope.get() if capture else None
    if captured is not None:
        envelope = captured.envelope
        evidence = EvidenceSession(conn)
        evidence.capture(
            agreement.negotiation_id, evidence_id=envelope.request_id,
            body=captured.body, headers=dict(captured.headers),
            context=envelope.model_dump(mode="json"), recorded_at=captured.verified_at,
        )
        evidence.accept(
            agreement.negotiation_id, message_id=envelope.request_id,
            accepted_by=envelope.principal, expires_at=expiry if expiry is not None else start + agreement.duration_seconds,
            terms=terms,
        )
    EndSession(conn).register(DeliveryRecord(
        negotiation_id=agreement.negotiation_id, commitment_ref=commitment,
        seller=Identity.model_validate(agreement.seller), start_at=start,
        term_end=start + agreement.duration_seconds,
        delivery_deadline_seconds=terms.delivery_deadline_seconds if terms else None,
    ))
    SellerSession(conn).register(SellerDeal(
        negotiation_id=agreement.negotiation_id, commitment_ref=commitment,
        domain="bare_metal", buyer=Identity.model_validate(agreement.buyer),
        payment=PaymentSelector(option.settlement_schema),
        dispute=terms.adjudication.dispute if terms else None,
        entitlements=(terms.early_termination.model_dump(mode="json")["entitlements"]
                      if terms and terms.early_termination else {}),
        once_only=True,
    ))
