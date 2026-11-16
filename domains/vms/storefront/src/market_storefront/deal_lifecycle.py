"""VM composition of committed deals, authority watches and retained envelopes."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from arkhai_compute.end_classification import classify_payment_stop, payment_actor
from compute_provisioning_contracts import LeaseEndedEvent, SignedLeaseEndedReport, verify_lease_end
from market_alkahest import ALKAHEST_MECHANISM_ID
from market_alkahest.payment_adapter import AlkahestOnceAdapter
from market_arkhai_mediation.adapter import MediationAdapter
from market_arkhai_mediation.client import MediationClient, MediationCredential
from market_arkhai_mediation.contract import INTERFACE
from market_arkhai_payments import PaymentSettlementData
from market_core.schemas import Agreement
from market_deal_lifecycle.adapters import (
    DeliveryEndIntent, DisputeAdapterTable, PaymentAdapterTable, PaymentBinding, PaymentSelector,
)
from market_deal_lifecycle.claims import DeliveryEndClaims
from market_deal_lifecycle.delivery import DeliveryEvidence
from market_deal_lifecycle.evidence import CommitmentAttempt
from market_deal_lifecycle.terms import decode_terms
from market_deal_lifecycle_contracts.models import (
    Accepted, CommitMessage, EvidenceItem, Pending, Rejected, SubmitResponse, Unknown,
)
from market_deal_servicing import (
    Classification, DealWatch, DeliveryIngress, DeliveryRecord, EndSession, LifecycleRouteBinding,
    LifecycleRouteServices, SellerDeal, SellerServicing, SellerSession, ServicingCycle,
    SQLiteEvidenceStore, seller_retention,
)
from market_deal_servicing.end import EndService
from market_deal_servicing.evidence import EvidenceSession, in_transaction, transaction
from market_deal_servicing.ingress import VerifiedSiteEnd
from market_deal_servicing.journal import atomic
from market_deal_servicing.watch import WatchSession
from market_identity import Identity, canonical_json

from market_storefront import container
from market_storefront.delivery_lifecycle import VmPhysicalEnd
from market_storefront.end_classification import resolve_site_corrections, site_classification
from market_storefront.settlement_stages import PaymentSettlementError
from market_storefront.services.capacity_client import build_capacity_runtime, build_fulfillment_client
from market_storefront.services.vm_fulfillment_planner import VERIFIED_EVIDENCE_STATUSES

logger = logging.getLogger(__name__)

#: The configuration that composes the payments seller stage, without which an
#: accepted payments deal, once-only or rate, cannot be serviced.
PAYMENTS_SERVICING_FIELDS = "[Settlement].arkhai_payments service_url and service_identity"

#: The servicing loop whose page position the kit keeps.
SERVICING_LOOP = "deal-servicing"


def instant(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


class VmDealLifecycle:
    def __init__(
        self, db, signer, payments, disputes, *, clock=lambda: int(time.time()), fulfillment=None,
        mediation_transport=None,
    ):
        self.db = db
        self.path = Path(db.db_path)
        self.signer = signer
        self.payments_coordinator = payments
        self.dispute_config = disputes.config
        self.clock = clock
        self.fulfillment = fulfillment
        # The transport every mediation client sends through; None gives each
        # client its own connection to the Agreement-pinned origin.
        self.mediation_transport = mediation_transport
        self.evidence = SQLiteEvidenceStore(self.path)
        self.clients = {}
        self.end = EndService(self.path, VmPhysicalEnd(db), clock=clock)
        self.ingress = DeliveryIngress(
            self.path, clock=clock, verify_site=self.verify_site, receipt_claim=self.receipt_claim,
            classify_site=self.classify_site,
        )
        # An Alkahest deal authorizes delivery through its once-only adapter,
        # since a mechanism with no adapter is never allowed.
        payment_entries = [(PaymentSelector(ALKAHEST_MECHANISM_ID), self.alkahest_adapter)]
        if payments is not None:
            payment_entries.append((PaymentSelector("arkhai.payments.v1"), self.payment_adapter))
        self.seller = SellerServicing(
            self.path, payments=PaymentAdapterTable(payment_entries),
            disputes=DisputeAdapterTable([(INTERFACE, self.dispute_adapter)]),
            credential_available=self.credential_available,
            watch_factory=self.watch, clock=clock,
            missing_adapters={} if payments is not None else {"arkhai.payments.v1": PAYMENTS_SERVICING_FIELDS},
        )

    def accepted(self, negotiation_id):
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                "SELECT agreement_bytes,settlement_data FROM negotiation_threads WHERE negotiation_id=?",
                (negotiation_id,),
            ).fetchone()
        if row is None or row[0] is None:
            raise KeyError(negotiation_id)
        Agreement.model_validate_json(row[0])
        agreement = json.loads(row[0])
        return agreement, json.loads(row[1]) if isinstance(row[1], str) else row[1]

    def binding(self, negotiation_id):
        agreement, _ = self.accepted(negotiation_id)
        return LifecycleRouteBinding(
            buyer=Identity.model_validate(agreement["buyer"]),
            seller=Identity.model_validate(agreement["seller"]),
            settlement=agreement["settlement"]["settlement"]["schema"] != "contact-exchange.v1",
        )

    def register(self, agreement, data, receipt):
        terms = decode_terms(agreement["settlement"].get("lifecycle"))
        start = instant(agreement["start_utc"])
        with transaction(self.path) as conn, atomic(conn):
            EndSession(conn).register(DeliveryRecord(
                negotiation_id=agreement["negotiation_id"],
                seller=Identity.model_validate(agreement["seller"]),
                commitment_ref=data.transaction_id, start_at=start,
                term_end=start + agreement["duration_seconds"],
                committed_at=receipt.receipt.approvedAt,
                delivery_deadline_seconds=terms.delivery_deadline_seconds if terms else None,
            ))
            SellerSession(conn).register(SellerDeal(
                negotiation_id=agreement["negotiation_id"], commitment_ref=data.transaction_id,
                domain="vms", buyer=Identity.model_validate(agreement["buyer"]),
                payment=PaymentSelector("arkhai.payments.v1"),
                dispute=terms.adjudication.dispute if terms else None,
                once_only=all(part.root.kind == "once" for part in data.mandate.parts),
                entitlements=terms.early_termination.model_dump(mode="json")["entitlements"]
                if terms and terms.early_termination else {},
            ))
            EvidenceSession(conn).record_commitment(
                agreement["negotiation_id"], CommitmentAttempt(commitment_ref=data.transaction_id),
            )

    def payment_adapter(self, binding: PaymentBinding):
        agreement, raw = self.accepted(binding.negotiation_id)
        data = PaymentSettlementData.parse(raw)
        with transaction(self.path) as conn:
            floor = max(0, WatchSession(conn).cursor(binding.negotiation_id, "payment:" + data.transaction_id))
        return self.payments_coordinator.stage.payment_adapter(
            agreement, data, minimum_sequence=floor,
        )

    def alkahest_adapter(self, binding: PaymentBinding):
        with transaction(self.path) as conn:
            commitment_ref = EndSession(conn).read(binding.negotiation_id).commitment_ref
        return AlkahestOnceAdapter(
            negotiation_id=binding.negotiation_id, commitment_ref=commitment_ref,
            validate_commitment=self.alkahest_commitment_valid,
        )

    async def alkahest_commitment_valid(self, evidence: DeliveryEvidence) -> bool:
        """Whether delivery evidence names the deal's verified Alkahest settlement.

        A reference being present proves nothing: it must be the escrow the
        deal's recorded settlement evidence was verified for, under the
        evidence schema delivery reads.
        """
        recorded = await self.db.load_vm_settlement_evidence(negotiation_id=evidence.negotiation_id)
        return (
            recorded is not None
            and recorded.mechanism == ALKAHEST_MECHANISM_ID
            and recorded.status in VERIFIED_EVIDENCE_STATUSES
            and recorded.settlement_ref == evidence.commitment_ref
            and recorded.evidence.get("schema") == "vm.settlement-evidence.v1"
        )

    def credential_available(self, authority):
        credential = self.dispute_config.credential_for(authority)
        if credential is None:
            return False
        # Usable means a client can be built from it: its token resolves and its
        # CA bundle loads. One that cannot reports the deal for repair, as a
        # missing one does, rather than failing every deal's servicing cycle. The
        # deal's repair reason names the credential missing, so the log names why
        # it is unusable: the exception's type, not its message, so no part of
        # the credential reaches the log.
        try:
            self.client(authority)
            return True
        except (ValueError, OSError) as exc:
            logger.warning(
                "Dispute credential for authority %s is unusable (%s); its CA bundle path is %r",
                authority.identity, type(exc).__name__, credential.ca_bundle_path,
            )
            return False

    def client(self, authority):
        key = canonical_json(authority)
        if key not in self.clients:
            credential = self.dispute_config.credential_for(authority)
            if credential is None:
                raise ValueError("Agreement authority credential is missing")
            self.clients[key] = MediationClient(
                authority, MediationCredential(authority.identity, token=credential.resolve()),
                transport=self.mediation_transport, ca_bundle=credential.ca_bundle_path,
            )
        return self.clients[key]

    def dispute_adapter(self, binding):
        agreement, _ = self.accepted(binding.negotiation_id)
        client = self.client(binding.authority) if self.credential_available(binding.authority) else None
        return MediationAdapter(binding, agreement, client, clock=self.clock)

    def watch(self, deal, payment, dispute):
        agreement, raw = self.accepted(deal.negotiation_id)
        data = PaymentSettlementData.parse(raw) if deal.payment.mechanism == "arkhai.payments.v1" else None
        authority = None
        if deal.dispute is not None:
            scheme, separator, key = deal.dispute.record_key.partition(":")
            authority = Identity(scheme=scheme if separator else "ed25519", identifier=key if separator else scheme)

        def actor(value):
            return payment_actor(
                value, payer_account=data.mandate.from_.root if data is not None else None,
                payee_account=data.mandate.to.root if data is not None else None,
                buyer=Identity.model_validate(agreement["buyer"]),
                seller=Identity.model_validate(agreement["seller"]),
                authority_account=deal.dispute.account if deal.dispute is not None else None,
                authority=authority,
            )

        term_end = instant(agreement["start_utc"]) + agreement["duration_seconds"]

        def classify(event):
            kind = classify_payment_stop(event, entitlements=deal.entitlements, term_end=term_end)
            return Classification(kind=kind, evidence_refs=[event.authority_record_ref]) if kind else None

        return DealWatch(
            self.path, negotiation_id=deal.negotiation_id, commitment_ref=deal.commitment_ref,
            payment=payment, dispute=dispute, dispute_binding=deal.dispute_binding,
            seller_account=data.mandate.to.root if data is not None else "",
            actor=actor, clock=self.clock, classify_payment_end=classify,
            observe_retention=seller_retention(self.path, deal.negotiation_id, clock=self.clock),
        )

    async def interrupt(self, negotiation_id, *, actor, operation_key, reason, interruption_kind=None, dry_run=False):
        """An administrator interruption, classified and carried out by the seller half."""
        return await self.seller.interrupt(
            negotiation_id, actor=actor, operation_key=operation_key, reason=reason or "",
            interruption_kind=interruption_kind, dry_run=dry_run, physical=self.end.drive_physical,
        )

    async def peer(self, message):
        if isinstance(message, CommitMessage):
            agreement, raw = self.accepted(message.negotiation_id)
            data = PaymentSettlementData.parse(raw)
            if message.commitment_ref != data.transaction_id:
                return SubmitResponse(outcome=Rejected(reason="commitment differs from accepted mandate"))
            if self.payments_coordinator is None:
                return SubmitResponse(outcome=Rejected(reason="payment servicing is unavailable"))
            thread = await self.db.load_negotiation_thread_row(negotiation_id=message.negotiation_id)
            try:
                result = await self.payments_coordinator.start(message.negotiation_id, thread)
            except PaymentSettlementError as exc:
                outcome = Rejected(reason=exc.detail) if exc.status_code < 500 else Unknown(reason=exc.detail)
                return SubmitResponse(outcome=outcome)
            outcome = Pending(reason="payment receipt is pending") if result.payload.get("status") == "pending" else Accepted()
            return SubmitResponse(outcome=outcome)
        # A hint triggers authority reads, never relays a buyer command.
        await self.seller.read(message.negotiation_id)
        return SubmitResponse(outcome=Accepted())

    def servicing(self):
        """The kit's servicing order over this lifecycle.

        The lifecycle is its own respondent port. Its one recovery step reads
        the site's lease end reports; its site-report correction applies the
        compute family's site classifier.
        """
        return ServicingCycle(
            self.path, domain="vms", loop=SERVICING_LOOP, seller=self.seller, end=self.end,
            respondents=self, signer=self.signer, clock=lambda: self.clock(),
            recovery=[("site-report recovery", lambda deal: self.recover_site_reports(deal.negotiation_id))],
            resolve_site_corrections=lambda session, negotiation_id, now: resolve_site_corrections(
                session, negotiation_id, now=now,
            ),
        )

    async def cycle(self, *, limit=100):
        """Service one page of deals in the kit's order; the page's size."""
        return await self.servicing().cycle(limit=limit)

    def receipt_claim(self, negotiation_id, at):
        # Ingress holds its write transaction; this immutable binding read
        # must not open a competing writer while building a local claim.
        with sqlite3.connect(self.path) as conn:
            binding = SellerSession(conn).read(negotiation_id).dispute_binding
        adapter = self.seller.disputes.resolve(binding) if binding else None
        if not isinstance(adapter, DeliveryEndClaims):
            return None
        return adapter.sign_delivery_end(
            DeliveryEndIntent(ended_at=at, delivered=True, cause="payer"), self.signer,
        )

    def reservation_deal(self, capacity_reservation_id, site_id):
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                """SELECT DISTINCT t.negotiation_id,t.site_id FROM negotiation_threads t
                   LEFT JOIN vm_delivery_records d USING(negotiation_id)
                   LEFT JOIN capacity_holds h USING(negotiation_id)
                   WHERE d.capacity_reservation_id=? OR h.capacity_reservation_id=?""",
                (capacity_reservation_id, capacity_reservation_id),
            ).fetchall()
        if not rows:
            raise KeyError(capacity_reservation_id)
        if len(rows) != 1 or rows[0][1] != site_id:
            raise ValueError("site report differs from durable reservation binding")
        return rows[0][0]

    async def recover_site_reports(self, negotiation_id):
        view, evidence = await in_transaction(self.path, lambda conn: (
            EndSession(conn).view(negotiation_id), EvidenceSession(conn).read(negotiation_id),
        ))
        delivery = await self.db.load_vm_delivery(negotiation_id=negotiation_id)
        hold = await self.db.load_capacity_hold(negotiation_id=negotiation_id)
        reservation = (delivery or {}).get("capacity_reservation_id") or (hold or {}).get("capacity_reservation_id")
        if not reservation:
            return
        history_ref = "site-history:" + reservation
        # A push proves only one event. Retire polling only after a complete,
        # successfully ingested lease read made after proven physical release.
        if view.progress == "released" and any(item.evidence_id == history_ref for item in evidence.items):
            return
        thread = await self.db.load_thread_binding(negotiation_id=negotiation_id)
        fulfillment = self.fulfillment or build_fulfillment_client(build_capacity_runtime(lambda: self.db).client())
        lease = await fulfillment.get_lease(reservation, site_id=thread.site_id)
        for report in lease.end_reports:
            await asyncio.to_thread(self.ingress.site_report, negotiation_id, body=canonical_json(report), headers={})
        if view.progress == "released" and lease.end_reports:
            def reconciled(conn):
                session = EvidenceSession(conn)
                if not any(item.evidence_id == history_ref for item in session.read(negotiation_id).items):
                    session.put(negotiation_id, EvidenceItem(
                        evidence_id=history_ref, kind="site_history_reconciled",
                        classification="seller_assertion", recorded_at=self.clock(),
                        body=base64.b64encode(canonical_json({"capacity_reservation_id": reservation})),
                    ))
            await in_transaction(self.path, reconciled)

    def capacity_released(self, capacity_reservation_id, site_id):
        try:
            negotiation_id = self.reservation_deal(capacity_reservation_id, site_id)
        except KeyError:
            # Capacity can be reserved administratively, outside a committed deal.
            return
        with transaction(self.path) as conn, atomic(conn):
            end = EndSession(conn)
            try:
                end.read(negotiation_id)
            except KeyError:
                return
            end.physical_progress(negotiation_id, "released")

    def verify_site(self, negotiation_id, body, headers):
        report = SignedLeaseEndedReport.model_validate_json(body)
        with transaction(self.path) as conn:
            row = conn.execute(
                """SELECT t.site_id,d.capacity_reservation_id,h.capacity_reservation_id
                   FROM negotiation_threads t
                   LEFT JOIN vm_delivery_records d USING(negotiation_id)
                   LEFT JOIN capacity_holds h USING(negotiation_id)
                   WHERE t.negotiation_id=?""", (negotiation_id,),
            ).fetchone()
        if row is None or not (row[1] or row[2]):
            raise ValueError("site report has no durable deal reservation")
        trust = container.resolved_service_peer_trust
        if trust is None:
            raise ValueError("site report trust is unavailable")
        event = verify_lease_end(
            report, capacity_reservation_id=row[1] or row[2], site_id=row[0],
            expected_sites=trust.site_authorities(row[0])(),
        )
        with transaction(self.path) as conn:
            end = EndSession(conn)
            prior = next((request for request in end.requests(negotiation_id)
                          if request.source_ref == "site-event:" + event.event_id), None)
            controlling = prior.controlling_source_ref if prior else site_classification(end, negotiation_id, event)[1]
        return VerifiedSiteEnd(
            controlling_source_ref=controlling,
            event_id=event.event_id, capacity_reservation_id=event.capacity_reservation_id,
            ended_at=event.effective_at, actor=event.caller or report.signer, cause=event.cause,
        )

    def classify_site(self, verified, end):
        rows = end.conn.execute(
            """SELECT DISTINCT t.negotiation_id FROM negotiation_threads t
               LEFT JOIN vm_delivery_records d USING(negotiation_id)
               LEFT JOIN capacity_holds h USING(negotiation_id)
               WHERE d.capacity_reservation_id=? OR h.capacity_reservation_id=?""",
            (verified.capacity_reservation_id, verified.capacity_reservation_id),
        ).fetchall()
        if len(rows) != 1:
            raise ValueError("site report has ambiguous deal binding")
        negotiation_id = rows[0][0]
        item = next(item for item in EvidenceSession(end.conn).read(negotiation_id).items
                    if item.evidence_id == "site-event:" + verified.event_id)
        event = LeaseEndedEvent.model_validate_json(SignedLeaseEndedReport.model_validate_json(item.body).payload)
        record = end.read(negotiation_id)
        end.admit(negotiation_id, record.phase, record.revision, now=self.clock())
        return site_classification(end, negotiation_id, event)[0]

    def routes(self, administrators):
        return LifecycleRouteServices(
            seller=self.seller, binding=self.binding, signer=self.signer,
            administrators=administrators, peer=self.peer, ingress=self.ingress, end=self.end,
        )

    async def close(self):
        for client in self.clients.values():
            await client.__aexit__(None, None, None)

    async def capture_negotiation(
        self, request, response_body, response_headers, *, operation, resource, status,
    ):
        authenticated = getattr(request.state, "marketplace_authenticated", None)
        if authenticated is None:
            return
        payload = json.loads(response_body)
        negotiation_id = payload.get("negotiation_id")
        if not negotiation_id:
            return
        raw = await request.body()

        def capture(conn):
            acceptance = (
                self.accepted(negotiation_id)
                if payload.get("action") == "accept" and payload.get("agreement_bytes") else None
            )
            session = EvidenceSession(conn)
            message_id = "buyer-envelope:" + hashlib.sha256(canonical_json(dict(request.headers)) + raw).hexdigest()
            session.capture(
                negotiation_id, evidence_id=message_id, body=raw,
                headers=dict(request.headers),
                context={
                    "operation": operation, "resource": resource, "method": request.method,
                    "role": "buyer", "principal": authenticated.principal.model_dump(mode="json"),
                },
                recorded_at=authenticated.timestamp,
            )
            session.capture(
                negotiation_id,
                evidence_id="seller-envelope:" + hashlib.sha256(
                    canonical_json([response_headers, response_body.decode()])
                ).hexdigest(),
                body=response_body, headers=response_headers, context={
                    "operation": operation, "resource": resource, "method": request.method,
                    "role": "seller", "principal": self.signer.identity.model_dump(mode="json"),
                    "status": status,
                },
                recorded_at=self.clock(),
            )
            if acceptance is not None:
                agreement, data = acceptance
                expiry = (
                    PaymentSettlementData.parse(data).mandate.expires
                    if agreement["settlement"]["settlement"]["schema"] == "arkhai.payments.v1"
                    else instant(agreement["accepted_at"])
                )
                session.accept(
                    negotiation_id, message_id=message_id, accepted_by=self.signer.identity,
                    expires_at=expiry, terms=decode_terms(agreement["settlement"].get("lifecycle")),
                )

        await in_transaction(self.path, capture)
