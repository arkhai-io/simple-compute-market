"""Bare-metal lifecycle authorities, delivery ordering and exact evidence."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sqlite3
import time

from arkhai_compute.end_classification import (
    payment_actor,
    resolve_site_corrections as pending_site_corrections,
    site_classification as classify_journal,
)
from compute_provisioning_contracts.lease_ends import LeaseEndedEvent, SignedLeaseEndedReport, verify_lease_end

from market_alkahest import ALKAHEST_MECHANISM_ID
from market_alkahest.payment_adapter import AlkahestOnceAdapter
from market_arkhai_mediation.adapter import MediationAdapter
from market_arkhai_mediation.client import MediationClient, MediationCredential
from market_arkhai_mediation.contract import INTERFACE
from market_core.schemas import Agreement
from market_deal_lifecycle.adapters import DeliveryEndIntent, DisputeAdapterTable, PaymentAdapterTable, PaymentSelector
from market_deal_lifecycle.claims import DeliveryEndClaims
from market_deal_lifecycle.delivery import DeliveryEvidence
from market_deal_lifecycle_contracts.models import Accepted, CommitMessage, ListDealsRequest, Pending, Rejected, SubmitResponse, Unknown
from market_deal_servicing import (
    Classification, DealWatch, DeliveryIngress, EndService, EndSession,
    FinalRequest, LifecycleRouteBinding, LifecycleRouteServices, RespondentPoller,
    PhysicalResult, SellerDeal, SellerServicing, SellerSession, SQLiteEvidenceStore, VerifiedSiteEnd,
    seller_retention,
)
from market_deal_servicing.evidence import EvidenceSession, in_transaction, transaction
from market_deal_servicing.journal import stable_ref
from market_identity import Identity, canonical_json

from .lifecycle_records import commitment_ref, register_agreement
from .models import BareMetalSettleRequest
from .settlement_stages import SettlementRequestError


logger = logging.getLogger(__name__)


class BareMetalLifecycle:
    def __init__(self, runtime):
        self.runtime = runtime
        self.path = runtime.db.db_path
        self.clock = lambda: int(time.time())
        self.evidence = SQLiteEvidenceStore(self.path)
        self.locks: dict[str, asyncio.Lock] = {}
        self.clients = {}
        with transaction(self.path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS bare_metal_lifecycle_cursor (id INTEGER PRIMARY KEY CHECK (id=1), continuation TEXT)")
        self.end = EndService(self.path, self, clock=self.clock)
        # An Alkahest deal authorizes delivery through its once-only adapter,
        # since a mechanism with no adapter is never allowed.
        self.seller = SellerServicing(
            self.path,
            payments=PaymentAdapterTable([
                (PaymentSelector("arkhai.payments.v1"), self.payment),
                (PaymentSelector(ALKAHEST_MECHANISM_ID), self.alkahest_adapter),
            ]),
            disputes=DisputeAdapterTable([(INTERFACE, self.dispute)]),
            credential_available=self.credential_available,
            watch_factory=self.watch, clock=self.clock,
        )
        self.ingress = DeliveryIngress(
            self.path, clock=self.clock, verify_site=self.verify_site,
            classify_site=self.classify_site, receipt_claim=self.receipt_claim,
        )

    def lock(self, negotiation_id):
        return self.locks.setdefault(negotiation_id, asyncio.Lock())

    def agreement_bytes(self, negotiation_id):
        with sqlite3.connect(self.path) as conn:
            row = conn.execute("SELECT agreement_bytes FROM negotiation_threads WHERE negotiation_id=?", (negotiation_id,)).fetchone()
        if row is None or row[0] is None:
            raise KeyError(negotiation_id)
        return bytes(row[0])

    def agreement(self, negotiation_id):
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                "SELECT agreement_bytes, settlement_data FROM negotiation_threads WHERE negotiation_id=?",
                (negotiation_id,),
            ).fetchone()
        if row is None or row[0] is None:
            raise KeyError(negotiation_id)
        return Agreement.model_validate_json(row[0]), json.loads(row[1]) if row[1] else None

    def binding(self, negotiation_id):
        agreement, data = self.agreement(negotiation_id)
        with transaction(self.path) as conn:
            register_agreement(conn, self.agreement_bytes(negotiation_id), data)
        return LifecycleRouteBinding(
            buyer=Identity.model_validate(agreement.buyer),
            seller=Identity.model_validate(agreement.seller),
            settlement=(agreement.settlement is not None and not self.runtime.domain.settlement.seller_stages[agreement.settlement.settlement_schema].completes_outside_settlement),
        )

    def payment(self, binding):
        _, data = self.agreement(binding.negotiation_id)
        stage = self.runtime.settlement_composition.arkhai_payments_stage()
        if stage is None:
            raise ValueError("accepted payments mechanism is not configured")
        raw, data = stage.accepted(self.agreement_bytes(binding.negotiation_id), data)
        return stage.payment_adapter(raw, data)

    def commitment_ref(self, negotiation_id):
        """The commitment the deal's servicing record is registered under."""
        _, data = self.agreement(negotiation_id)
        return commitment_ref(self.agreement_bytes(negotiation_id), data)

    def alkahest_adapter(self, binding):
        return AlkahestOnceAdapter(
            negotiation_id=binding.negotiation_id,
            commitment_ref=self.commitment_ref(binding.negotiation_id),
            validate_commitment=self.alkahest_commitment_valid,
        )

    async def alkahest_commitment_valid(self, evidence: DeliveryEvidence) -> bool:
        """Whether delivery evidence names the deal's verified Alkahest settlement.

        The adapter has already bound the evidence to the Agreement's
        commitment; the settlement record must be the verified Alkahest
        settlement of that same Agreement, not merely carry a reference.
        """
        record = await self.runtime.db.load_bare_metal_settlement_record(
            negotiation_id=evidence.negotiation_id,
        )
        if record is None:
            return False
        agreement_bytes = await asyncio.to_thread(self.agreement_bytes, evidence.negotiation_id)
        return (
            record["mechanism"] == ALKAHEST_MECHANISM_ID
            and record["status"] == "settlement_verified"
            and bool(record["settlement_ref"])
            and record["agreement_sha256"] == hashlib.sha256(agreement_bytes).hexdigest()
        )

    def credential_available(self, authority):
        composition = self.runtime.settlement_composition
        credential = composition.disputes.config.credential_for(authority) if composition else None
        if credential is None:
            return False
        try:
            credential.resolve()
            return True
        except ValueError:
            return False

    def dispute(self, binding):
        client = None
        if self.credential_available(binding.authority):
            credential = self.runtime.settlement_composition.disputes.config.credential_for(binding.authority)
            key = binding.authority.model_dump_json()
            if key not in self.clients:
                self.clients[key] = MediationClient(
                    binding.authority,
                    MediationCredential(binding.authority.identity, token=credential.resolve()),
                )
            client = self.clients[key]
        return MediationAdapter(binding, json.loads(self.agreement_bytes(binding.negotiation_id)), client, clock=self.clock)

    def watch(self, deal, payment, dispute):
        # Only an Arkhai payment carries a mandate naming the two accounts; an
        # Alkahest deal's once-only adapter names none, and moves no money.
        mandate = (
            payment.data.mandate
            if payment is not None and deal.payment.mechanism == "arkhai.payments.v1"
            else None
        )
        account = mandate.to.root if mandate is not None else ""
        agreement, _ = self.agreement(deal.negotiation_id)
        buyer = Identity.model_validate(agreement.buyer)

        authority = None
        if deal.dispute:
            scheme, separator, key = deal.dispute.record_key.partition(":")
            authority = Identity(scheme=scheme if separator else "ed25519", identifier=key if separator else scheme)

        def actor(value):
            return payment_actor(
                value, payer_account=mandate.from_.root if mandate is not None else None,
                payee_account=account if mandate is not None else None, buyer=buyer,
                seller=self.runtime.seller_principal,
                authority_account=deal.dispute.account if deal.dispute else None, authority=authority,
            )

        return DealWatch(
            self.path, negotiation_id=deal.negotiation_id, commitment_ref=deal.commitment_ref,
            payment=payment, dispute=dispute, dispute_binding=deal.dispute_binding,
            seller_account=account, actor=actor, clock=self.clock,
            observe_retention=seller_retention(self.path, deal.negotiation_id, clock=self.clock),
        )

    async def delivery_available(self, negotiation_id):
        """Whether the deal's delivery is recorded available."""
        record = await in_transaction(self.path, lambda conn: EndSession(conn).read(negotiation_id))
        return record.available_at is not None

    async def ended_before_delivery(self, negotiation_id):
        """Whether the deal's end has taken effect while it was never available.

        Delivery stops at an end in effect, so such a deal is never delivered
        later. An end recorded for a later instant has not taken effect: the
        deal may still be delivered before it.
        """
        def read(conn):
            session = EndSession(conn)
            try:
                record = session.read(negotiation_id)
            except KeyError:
                return None, None
            return record, session.selected_end(negotiation_id)

        record, end = await in_transaction(self.path, read)
        return (
            record is not None
            and record.available_at is None
            and end is not None
            and end.ended_at <= self.clock()
        )

    async def apply_end(self, negotiation_id, *, terminate, at, operation_key):
        # Do not terminate a lease before its in-flight dispatch has been adopted.
        # The end is already durable; the fulfillment hook, once it releases the
        # deal's lock, and the recovery loop retry it.
        if self.lock(negotiation_id).locked():
            return PhysicalResult(progress="end_recorded", done=False)
        return await self.runtime.fulfillment_service().apply_end(
            negotiation_id, terminate=terminate, at=at, operation_key=operation_key,
            reason=operation_key,
        )

    async def local_end(self, negotiation_id, *, cause):
        await asyncio.to_thread(self.binding, negotiation_id)
        now = self.clock()
        def record(conn):
            session = EndSession(conn)
            if not any(request.source_ref == cause for request in session.requests(negotiation_id)):
                self._record_local_end(session, negotiation_id, cause, now)
        await in_transaction(self.path, record)
        await self.end.drive_physical(negotiation_id)

    def _record_local_end(self, session, negotiation_id, cause, now):
        session.record_end(FinalRequest(
                negotiation_id=negotiation_id, source_ref=cause,
                ended_at=now, observed_at=now, actor=self.runtime.seller_principal,
                cause=cause, source="terminal_settlement", evidence_refs=[cause],
        ), now=now, classification=Classification(kind="terms", evidence_refs=[cause]))

    def receipt_claim(self, negotiation_id, at):
        # Ingress holds its write transaction; this immutable binding read
        # must not open a competing writer while building a local claim.
        with sqlite3.connect(self.path) as conn:
            binding = SellerSession(conn, initialize=False).read(negotiation_id).dispute_binding
        adapter = self.seller.disputes.resolve(binding) if binding else None
        if not isinstance(adapter, DeliveryEndClaims):
            return None
        return adapter.sign_delivery_end(
            DeliveryEndIntent(ended_at=at, delivered=True, cause="payer"), self.runtime.marketplace_signer,
        )

    def verify_site(self, negotiation_id, body, headers):
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                "SELECT capacity_reservation_id,site_id FROM bare_metal_fulfillment_lifecycle WHERE negotiation_id=?",
                (negotiation_id,),
            ).fetchone()
        if row is None:
            raise ValueError("site report has no owned reservation")
        trust = self.runtime.service_peer_trust
        if trust is None:
            raise ValueError("site peer trust is unavailable")
        report = SignedLeaseEndedReport.model_validate_json(body)
        event = verify_lease_end(
            report, capacity_reservation_id=row[0], site_id=row[1],
            expected_sites=trust.site_trusted_set(row[1]),
        )
        with transaction(self.path) as conn:
            session = EndSession(conn)
            prior = next((request for request in session.requests(negotiation_id)
                          if request.source_ref == "site-event:" + event.event_id), None)
            controlling = (prior.controlling_source_ref if prior else
                           self.site_classification(session, negotiation_id, event).controlling_source_ref)
        return VerifiedSiteEnd(
            event_id=event.event_id, capacity_reservation_id=row[0], ended_at=event.effective_at,
            actor=event.caller or report.signer, cause=event.cause, controlling_source_ref=controlling,
        )

    async def recover_delivery(self, deal):
        """Drive a started delivery that has not finished, through the fulfillment hook.

        A deal waiting for its Agreement start, one whose fulfillment is still
        settling, and one available whose result is not yet recorded are each
        driven again; the path rechecks admission, so an end recorded meanwhile
        stops it. A delivery not yet started is started by its settlement: the
        payment reconciliation loop or the servicing worker.
        """
        row = await self.runtime.db.load_bare_metal_fulfillment_lifecycle(
            negotiation_id=deal.negotiation_id,
        )
        if row is None or row.get("state") == "released":
            return
        record = await in_transaction(
            self.path, lambda conn: EndSession(conn).read(deal.negotiation_id),
        )
        if record.progress not in ("unstarted", "active"):
            return
        if record.available_at is not None:
            result = await self.runtime.db.load_bare_metal_result(
                negotiation_id=deal.negotiation_id,
            )
            receipt = await self.runtime.db.load_bare_metal_receipt(
                negotiation_id=deal.negotiation_id,
            )
            if result is not None and receipt is not None:
                return
        await self.runtime.fulfillment_service().deliver(
            negotiation_id=deal.negotiation_id, buyer_principal=deal.buyer,
        )

    async def recover_site(self, negotiation_id):
        row = await self.runtime.db.load_bare_metal_fulfillment_lifecycle(negotiation_id=negotiation_id)
        if row is None or not row.get("capacity_reservation_id"):
            return
        lease = await self.runtime.fulfillment_client.get_lease(row["capacity_reservation_id"])
        for report in lease.end_reports:
            await asyncio.to_thread(self.ingress.site_report, negotiation_id, body=canonical_json(report), headers={})
        # Intended ends never establish capacity return. The authenticated site
        # lease read uses the same release guard as its separate callback.
        if lease.status == "released":
            await self.runtime.db.update_bare_metal_fulfillment_lifecycle(
                negotiation_id=negotiation_id, state="released",
            )
            await in_transaction(self.path, lambda conn: EndSession(conn).physical_progress(negotiation_id, "released"))

    def classify_site(self, event, session):
        row = session.conn.execute(
            "SELECT negotiation_id FROM bare_metal_fulfillment_lifecycle WHERE capacity_reservation_id=?",
            (event.capacity_reservation_id,),
        ).fetchone()
        negotiation_id = row[0]
        item = next(item for item in EvidenceSession(session.conn).read(negotiation_id).items
                    if item.evidence_id == "site-event:" + event.event_id)
        report = LeaseEndedEvent.model_validate_json(SignedLeaseEndedReport.model_validate_json(item.body).payload)
        record = session.read(negotiation_id)
        session.admit(negotiation_id, record.phase, record.revision, now=self.clock())
        result = self.site_classification(session, negotiation_id, report)
        return Classification(kind=result.kind, evidence_refs=result.evidence_refs) if result.kind else None

    @staticmethod
    def classification_for(session, negotiation_id, source_ref):
        row = session.conn.execute(
            "SELECT classification FROM servicing_final_requests WHERE negotiation_id=? AND source_ref=?",
            (negotiation_id, source_ref),
        ).fetchone()
        return Classification.model_validate_json(row[0]) if row and row[0] else None

    def site_classification(self, session, negotiation_id, event):
        record = session.read(negotiation_id)
        requests = session.requests(negotiation_id)
        return classify_journal(
            event, seller=record.seller, term_end=record.term_end,
            available=record.available_at is not None, intents=session.intents(negotiation_id),
            requests=requests,
            classifications={request.source_ref: self.classification_for(session, negotiation_id, request.source_ref)
                             for request in requests},
            termination_ref=stable_ref(negotiation_id, "terminate", "terminate"),
        )

    def resolve_site_corrections(self, session, negotiation_id, *, now):
        items = {item.evidence_id: item for item in EvidenceSession(session.conn).read(negotiation_id).items}
        requests = session.requests(negotiation_id)

        def report_for(source_ref):
            report = SignedLeaseEndedReport.model_validate_json(items[source_ref].body)
            return LeaseEndedEvent.model_validate_json(report.payload)

        for request, result in pending_site_corrections(
            requests,
            classifications={request.source_ref: self.classification_for(session, negotiation_id, request.source_ref)
                             for request in requests},
            report_for=report_for,
            classify=lambda event: self.site_classification(session, negotiation_id, event),
        ):
            record = session.read(negotiation_id)
            classification = Classification(kind=result.kind, evidence_refs=result.evidence_refs)
            session.resolve_correction(
                negotiation_id, request.source_ref, record.revision,
                evidence=result.evidence_refs, classification=classification,
                controlling_source_ref=result.controlling_source_ref,
                filing_intent=None if classification.lawful or result.controlling_source_ref else session.failure_filing(
                    request, now=now, delivered=record.available_at is not None,
                ),
            )

    def reconcile_local(self, negotiation_id):
        now = self.clock()
        with transaction(self.path) as conn:
            session = EndSession(conn)
            record = session.read(negotiation_id)
            if record.committed_at is None:
                return False
            # Admission establishes a missed delivery deadline before a later
            # terms expiry can incorrectly turn non-delivery into a lawful end.
            session.admit(negotiation_id, record.phase, record.revision, now=now)
            if now >= record.term_end and not any(
                request.source_ref == "term-end" for request in session.requests(negotiation_id)
            ):
                session.record_end(FinalRequest(
                    negotiation_id=negotiation_id, source_ref="term-end", ended_at=record.term_end,
                    observed_at=now, actor=record.seller, cause="terms", source="agreement",
                    evidence_refs=[record.commitment_ref],
                ), now=now, classification=Classification(kind="terms", evidence_refs=[record.commitment_ref]))
        return True

    async def peer(self, message):
        if isinstance(message, CommitMessage):
            deal = self.seller._deal(message.negotiation_id)
            if message.commitment_ref != deal.commitment_ref:
                return SubmitResponse(outcome=Rejected(reason="commitment differs from Agreement"))
            if deal.payment.mechanism != "arkhai.payments.v1":
                return SubmitResponse(outcome=Rejected(reason="mechanism has no commit adapter"))
            try:
                result = await self.runtime.settlement_service().verify(
                    escrow_uid=message.negotiation_id,
                    request=self._settle_request(message.negotiation_id, deal.buyer),
                    buyer_principal=deal.buyer,
                )
            except SettlementRequestError as exc:
                return SubmitResponse(outcome=Unknown(reason=str(exc)) if exc.status_code >= 500 else Rejected(reason=str(exc)))
            return SubmitResponse(outcome=Pending(reason="payment receipt is pending") if result.status_code == 202 else Accepted())
        await self.seller.read(message.negotiation_id)
        await self.end.drive_physical(message.negotiation_id)
        return SubmitResponse(outcome=Accepted())

    @staticmethod
    def _settle_request(negotiation_id, buyer):
        return BareMetalSettleRequest(negotiation_id=negotiation_id, buyer_principal=buyer)

    def routes(self):
        return LifecycleRouteServices(
            seller=self.seller, binding=self.binding, signer=self.runtime.marketplace_signer,
            administrators=self.runtime.admin_principals, peer=self.peer, ingress=self.ingress, end=self.end,
        )

    async def cycle(self):
        # One bounded page per cycle, with durable rotation even if one peer is
        # unavailable. A bad deal must not starve physical recovery of the rest.
        def page(conn):
            row = conn.execute("SELECT continuation FROM bare_metal_lifecycle_cursor WHERE id=1").fetchone()
            return SellerSession(conn).page(
                ListDealsRequest(limit=100, continuation=row[0] if row else None),
                committed_only=False,
            )
        deals, continuation = await in_transaction(self.path, page)
        authorities = {}
        for deal in deals:
            if deal.dispute and self.credential_available(deal.dispute):
                authorities.setdefault(deal.dispute.model_dump_json(), deal)
        for deal in authorities.values():
            try:
                adapter = self.dispute(deal.dispute_binding)

                def resolve(case):
                    with transaction(self.path) as conn:
                        rows = conn.execute(
                            "SELECT deal FROM servicing_seller_deals WHERE json_extract(deal, '$.commitment_ref')=?",
                            (case.commitment_ref,),
                        ).fetchall()
                    for row in rows:
                        candidate = SellerDeal.model_validate_json(row[0])
                        if candidate.dispute == deal.dispute:
                            resolved = self.dispute(candidate.dispute_binding)
                            if resolved.agreement_digest == case.agreement_ref:
                                return candidate.negotiation_id, resolved
                    return None

                await RespondentPoller(
                    self.path, authority=deal.dispute, account=self.payment(deal).data.mandate.to.root,
                    read=adapter.respondent, resolve=resolve, signer=self.runtime.marketplace_signer,
                    clock=self.clock,
                ).poll()
            except Exception:
                logger.exception("bare-metal respondent recovery failed")
        for deal in deals:
            try:
                await self.recover_delivery(deal)
            except Exception:
                logger.exception("bare-metal delivery recovery failed for %s", deal.negotiation_id)
            # Physical work is independent of authority availability and payment
            # publication. Always attempt it, including an uncommitted surrender.
            try:
                await self.recover_site(deal.negotiation_id)
            except Exception:
                logger.exception("bare-metal site recovery failed for %s", deal.negotiation_id)
            try:
                await self.end.drive_physical(deal.negotiation_id)
                if await asyncio.to_thread(self.reconcile_local, deal.negotiation_id):
                    await self.seller.read(deal.negotiation_id)
                    await in_transaction(self.path, lambda conn: self.resolve_site_corrections(
                        EndSession(conn), deal.negotiation_id, now=self.clock(),
                    ))
                    await self.seller.dispatch_filings(deal.negotiation_id)
            except Exception:
                logger.exception("bare-metal lifecycle recovery failed for %s", deal.negotiation_id)
            finally:
                try:
                    await self.end.drive_physical(deal.negotiation_id)
                except Exception:
                    logger.exception("bare-metal physical recovery failed for %s", deal.negotiation_id)
        await in_transaction(self.path, lambda conn: conn.execute(
            "INSERT OR REPLACE INTO bare_metal_lifecycle_cursor VALUES (1,?)", (continuation,),
        ).close())
        return len(deals)

    async def close(self):
        for client in self.clients.values():
            await client.close()
        self.clients.clear()
