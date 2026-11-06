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

from arkhai_compute.end_classification import payment_actor
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
    Accepted, CommitMessage, EvidenceItem, LifecycleCommand, ListDealsRequest,
    Pending, Rejected, SubmitResponse, Unknown,
)
from market_deal_servicing import (
    DealWatch, DeliveryIngress, DeliveryRecord, EndSession, LifecycleRouteBinding,
    LifecycleRouteServices, RespondentPoller, SellerDeal, SellerServicing,
    SellerSession, SQLiteEvidenceStore, seller_retention,
)
from market_deal_servicing.end import EndService
from market_deal_servicing.evidence import EvidenceSession, in_transaction, transaction
from market_deal_servicing.ingress import VerifiedSiteEnd
from market_deal_servicing.journal import atomic
from market_deal_servicing.watch import WatchSession, create_schema as create_watch_schema
from market_identity import Identity, canonical_json

from market_storefront import container
from market_storefront.delivery_lifecycle import VmPhysicalEnd
from market_storefront.end_classification import resolve_site_corrections, site_classification
from market_storefront.settlement_stages import PaymentSettlementError
from market_storefront.services.capacity_client import build_capacity_runtime, build_fulfillment_client
from market_storefront.services.vm_fulfillment_planner import VERIFIED_EVIDENCE_STATUSES

logger = logging.getLogger(__name__)


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
        with transaction(self.path) as conn:
            create_watch_schema(conn)
        self.clients = {}
        self.respondents = {}
        self.continuation = None
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
                dispute=terms.adjudication.dispute if terms else None, once_only=True,
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
        try:
            credential.resolve()
            return True
        except ValueError:
            return False

    def client(self, authority):
        key = canonical_json(authority)
        if key not in self.clients:
            credential = self.dispute_config.credential_for(authority)
            if credential is None:
                raise ValueError("Agreement authority credential is missing")
            self.clients[key] = MediationClient(
                authority, MediationCredential(authority.identity, token=credential.resolve()),
                transport=self.mediation_transport,
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

        return DealWatch(
            self.path, negotiation_id=deal.negotiation_id, commitment_ref=deal.commitment_ref,
            payment=payment, dispute=dispute, dispute_binding=deal.dispute_binding,
            seller_account=data.mandate.to.root if data is not None else "",
            actor=actor, clock=self.clock,
            observe_retention=seller_retention(self.path, deal.negotiation_id, clock=self.clock),
        )

    async def interrupt(self, negotiation_id, *, actor, operation_key, reason, dry_run=False):
        agreement, _ = await asyncio.to_thread(self.accepted, negotiation_id)
        terms = decode_terms(agreement["settlement"].get("lifecycle"))
        entitled = bool(terms and terms.early_termination and "payee" in terms.early_termination.entitlements)
        command = LifecycleCommand(
            negotiation_id=negotiation_id, operation_key=operation_key,
            kind="stop" if entitled else "delivery_end",
        )
        if not reason or not reason.strip():
            raise ValueError("administrator interruption requires a reason")
        if dry_run:
            return command.kind, Pending(reason="dry run; no interruption submitted"), (await asyncio.to_thread(self.seller.delivery_read, negotiation_id)).delivery
        # Keep operator attribution for notice stops as well as exceptional ends.
        # The immutable evidence ID rejects a same-key retry changing its author.
        await in_transaction(self.path, lambda conn: EvidenceSession(conn).put(negotiation_id, EvidenceItem(
                evidence_id="administrator-interrupt:" + operation_key,
                kind="administrator_interrupt", classification="seller_assertion",
                recorded_at=self.clock(), body=base64.b64encode(canonical_json({
                    "command": command.model_dump(mode="json"),
                    "administrator": actor.model_dump(mode="json"), "reason": reason,
                })),
            )))
        if entitled:
            outcome = await self.seller.submit(command, actor=actor, reason=reason)
            # Only a verified authority stop may set an entitled delivery end.
            return command.kind, outcome, (await asyncio.to_thread(self.seller.delivery_read, negotiation_id)).delivery

        # Journal before either task: off-loop preparation can yield before it
        # writes, so racing submit with teardown alone can miss the new end.
        refusal = await self.seller.record_operator_end(command, actor=actor, reason=reason)
        if refusal is not None:
            return command.kind, refusal, (await asyncio.to_thread(self.seller.delivery_read, negotiation_id)).delivery

        async def physical():
            await self.end.drive_physical(negotiation_id)

        outcome, progress = await asyncio.gather(
            self.seller.submit(command, actor=actor, reason=reason), physical(),
            return_exceptions=True,
        )
        if isinstance(progress, BaseException):
            logger.error("VM administrator end awaits physical recovery: %s", progress)
        if isinstance(outcome, BaseException):
            logger.error("VM administrator filing awaits authority recovery: %s", outcome)
            outcome = Unknown(reason="delivery-end filing awaits authority recovery")
        return command.kind, outcome, (await asyncio.to_thread(self.seller.delivery_read, negotiation_id)).delivery

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

    async def cycle(self, *, limit=100):
        deals, self.continuation = await in_transaction(
            self.path, lambda conn: SellerSession(conn).page(ListDealsRequest(
                limit=limit, continuation=self.continuation,
            )),
        )
        # Discovery precedes watch so both reuse the same prepared answer journal.
        for deal in deals:
            if deal.dispute is None or not self.credential_available(deal.dispute):
                continue
            agreement, raw = self.accepted(deal.negotiation_id)
            account = PaymentSettlementData.parse(raw).mandate.to.root
            key = (canonical_json(deal.dispute), account)
            if key not in self.respondents:
                adapter = self.dispute_adapter(deal.dispute_binding)

                def resolve(case, *, authority=deal.dispute):
                    with transaction(self.path) as conn:
                        row = conn.execute(
                            "SELECT deal FROM servicing_seller_deals WHERE json_extract(deal, '$.commitment_ref')=?",
                            (case.commitment_ref,),
                        ).fetchone()
                    matched = SellerDeal.model_validate_json(row[0]) if row else None
                    if matched is None or matched.dispute != authority:
                        return None
                    candidate = self.dispute_adapter(matched.dispute_binding)
                    if candidate.agreement_digest != case.agreement_ref:
                        raise ValueError("respondent case differs from accepted Agreement")
                    return matched.negotiation_id, candidate

                self.respondents[key] = RespondentPoller(
                    self.path, authority=deal.dispute, account=account, read=adapter.respondent,
                    resolve=resolve, signer=self.signer, clock=self.clock,
                )
        for poller in self.respondents.values():
            try:
                await poller.poll()
            except Exception:
                logger.exception("VM respondent discovery awaits recovery")
        for deal in deals:
            def admit_deadline(conn):
                end = EndSession(conn)
                record = end.read(deal.negotiation_id)
                # A recovery sweep observes missed delivery, not a new admission.
                # Re-admitting an unchanged phase invalidates concurrent CAS readers.
                now = self.clock()
                if now > record.deadline and (record.available_at is None or record.available_at > record.deadline):
                    end.admit(deal.negotiation_id, record.phase, record.revision, now=now)
            await in_transaction(self.path, admit_deadline)
            try:
                await self.recover_site_reports(deal.negotiation_id)
            except Exception:
                logger.exception("VM site-report recovery awaits retry for %s", deal.negotiation_id)
            try:
                await self.end.drive_physical(deal.negotiation_id)
            except Exception:
                logger.exception("VM physical end awaits recovery for %s", deal.negotiation_id)
            try:
                async for _ in self.seller.watch(deal.negotiation_id):
                    pass
            except Exception:
                logger.exception("VM lifecycle watch awaits recovery for %s", deal.negotiation_id)
            try:
                await in_transaction(self.path, lambda conn: resolve_site_corrections(
                    EndSession(conn), deal.negotiation_id, now=self.clock(),
                ))
            except Exception:
                logger.exception("VM end classification awaits recovery for %s", deal.negotiation_id)
            try:
                await self.end.drive_physical(deal.negotiation_id)
            except Exception:
                logger.exception("VM observed end awaits recovery for %s", deal.negotiation_id)
        return len(deals)

    def receipt_claim(self, negotiation_id, at):
        # Ingress holds its write transaction; this immutable binding read
        # must not open a competing writer while building a local claim.
        with sqlite3.connect(self.path) as conn:
            binding = SellerSession(conn, initialize=False).read(negotiation_id).dispute_binding
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
