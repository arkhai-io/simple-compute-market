"""Durable receipt-time surrender and verified, mechanism-neutral site ingress."""

from __future__ import annotations

import base64
from collections.abc import Callable
import hashlib
import json
from pathlib import Path
from typing import Protocol

from market_deal_lifecycle_contracts.models import (
    DeliveryView, EndDeliveryAcknowledgement, EndDeliveryMessage, EvidenceItem,
    Instant, Reference, WireModel,
)
from market_identity import (
    AuthenticatedRequest, Identity, TrustedIdentitySet, canonical_json, verify_request,
)
from pydantic import JsonValue

from .evidence import EvidenceSession, transaction
from .journal import Classification, EndSession, FinalRequest, atomic
from .seller import SellerSession


class VerifiedSiteEnd(WireModel):
    event_id: Reference
    capacity_reservation_id: Reference
    ended_at: Instant
    actor: Identity
    cause: Reference
    controlling_source_ref: Reference | None = None


class SiteReportVerifier(Protocol):
    def __call__(
        self, negotiation_id: str, body: bytes, headers: dict[str, str],
    ) -> VerifiedSiteEnd:
        """Verify proof and event binding against the reservation's configured site.

        The domain owns reservation/site lookup and the family's wire codec.
        Return only after checking event, reservation and site identity together.
        Push and authenticated lease-read recovery use this same boundary.
        """
        ...


class DeliveryIngress:
    def __init__(
        self, path: str | Path, *, clock: Callable[[], int], verify_site: SiteReportVerifier,
        classify_site: Callable[[VerifiedSiteEnd, EndSession], Classification | None] = lambda *_: None,
        max_request_skew: int = 300,
        receipt_claim: Callable[[str, int], dict[str, JsonValue] | None] = lambda *_: None,
    ):
        self.path = Path(path)
        self.clock = clock
        self.verify_site = verify_site
        self.classify_site = classify_site
        self.max_request_skew = max_request_skew
        self.receipt_claim = receipt_claim

    def site_report(self, negotiation_id: str, *, body: bytes, headers: dict[str, str]) -> DeliveryView:
        verified = self.verify_site(negotiation_id, body, headers)
        now = self.clock()
        ref = "site-event:" + verified.event_id
        with transaction(self.path) as conn, atomic(conn):
            end = EndSession(conn)
            prior = next((item for item in end.requests(negotiation_id) if item.source_ref == ref), None)
            request = FinalRequest(
                negotiation_id=negotiation_id, source_ref=ref, ended_at=verified.ended_at,
                observed_at=prior.observed_at if prior else now, actor=verified.actor,
                cause=verified.cause, source="lease_ended", evidence_refs=[ref],
                controlling_source_ref=verified.controlling_source_ref,
            )
            # Retain the original envelope, not a reconstruction from parsed fields.
            evidence = EvidenceSession(conn)
            kept = next((item for item in evidence.read(negotiation_id).items
                         if item.evidence_id == ref), None)
            if kept is not None:
                # Push retries refresh transport proofs; pull has no push
                # headers. Preserve the first exact report without conflating
                # either transport with the site's immutable signed statement.
                if json.loads(kept.body) != json.loads(body):
                    raise ValueError("site event identity changes its signed report")
            else:
                evidence.put(negotiation_id, EvidenceItem(
                    evidence_id=ref, kind="lease_ended", classification="independent", recorded_at=now,
                    body=base64.b64encode(body), headers=headers,
                    context={"capacity_reservation_id": verified.capacity_reservation_id},
                ))
            if prior is not None:
                if prior != request:
                    raise ValueError("site event identity changes its final request")
            else:
                classification = self.classify_site(verified, end)
                end.record_end(
                    request, now=now, classification=classification,
                    pending_classification=classification is None,
                    filing_intent=end.failure_filing(
                        request, now=now, delivered=end.read(negotiation_id).available_at is not None,
                    ) if (classification is not None and not classification.lawful
                          and request.controlling_source_ref is None) else None,
                )
            return end.view(negotiation_id)

    def end_delivery(
        self, envelope: AuthenticatedRequest, *, body: bytes, headers: dict[str, str],
    ) -> EndDeliveryAcknowledgement:
        value = json.loads(body)
        message = EndDeliveryMessage.model_validate(value)
        now = self.clock()
        with transaction(self.path) as conn, atomic(conn):
            deal = SellerSession(conn).read(message.negotiation_id)
            verified = verify_request(
                envelope, body=value, now=now, max_skew=self.max_request_skew,
                expected_role="buyer", expected_method="POST", expected_operation="lifecycle_peer",
                expected_resource=message.negotiation_id,
                expected_principals=TrustedIdentitySet(identities=(deal.buyer,)),
            )
            if not verified.verified:
                raise ValueError(f"buyer surrender authentication failed: {verified.code.value}")
            end = EndSession(conn)
            digest = hashlib.sha256(canonical_json(message)).hexdigest()
            row = conn.execute(
                """SELECT request_digest,receipt_at FROM servicing_end_receipts
                   WHERE negotiation_id=? AND operation_key=?""",
                (message.negotiation_id, message.operation_key),
            ).fetchone()
            if row is not None and row[0] != digest:
                raise ValueError("end-delivery operation key changes content")
            receipt_at = row[1] if row is not None else now
            if row is None:
                conn.execute(
                    "INSERT INTO servicing_end_receipts VALUES (?,?,?,?)",
                    (message.negotiation_id, message.operation_key, digest, receipt_at),
                )
            evidence_ref = "buyer-end-envelope:" + envelope.request_id
            EvidenceSession(conn).put(message.negotiation_id, EvidenceItem(
                evidence_id=evidence_ref, kind="end_delivery", classification="buyer_observation",
                recorded_at=now, body=base64.b64encode(body), headers=headers,
                context={"authenticated_request": envelope.model_dump(mode="json")},
            ))
            source_ref = "buyer-surrender:" + message.operation_key
            prior = next((item for item in end.requests(message.negotiation_id)
                          if item.source_ref == source_ref), None)
            if prior is None:
                request = FinalRequest(
                    negotiation_id=message.negotiation_id, source_ref=source_ref,
                    ended_at=receipt_at, observed_at=receipt_at, actor=deal.buyer,
                    cause="buyer_surrender", source="end_delivery", evidence_refs=[evidence_ref],
                )
                end.record_end(request, now=now, classification=Classification(
                    kind="buyer_surrender", evidence_refs=request.evidence_refs,
                ))
            selected = end.selected_end(message.negotiation_id)
            assert selected is not None
            claim = None
            if selected.source_ref == source_ref:
                claim_row = conn.execute(
                    "SELECT claim FROM servicing_receipt_claims WHERE negotiation_id=? AND operation_key=?",
                    (message.negotiation_id, message.operation_key),
                ).fetchone()
                if claim_row is None:
                    claim = self.receipt_claim(message.negotiation_id, receipt_at)
                    conn.execute(
                        "INSERT INTO servicing_receipt_claims VALUES (?,?,?)",
                        (message.negotiation_id, message.operation_key, canonical_json(claim).decode()),
                    )
                else:
                    claim = json.loads(claim_row[0])
            return EndDeliveryAcknowledgement(
                negotiation_id=message.negotiation_id, operation_key=message.operation_key,
                receipt_at=receipt_at, selected_end=selected.attribution,
                signed_delivery_end_claim=claim,
                delivery=end.view(message.negotiation_id),
            )
