"""Bare-metal lifecycle authorities, delivery ordering and exact evidence."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone

from compute_provisioning_contracts.lease_ends import SignedLeaseEndedReport, verify_lease_end

from market_arkhai_mediation.adapter import MediationAdapter
from market_arkhai_mediation.claims import sign_claim
from market_arkhai_mediation.client import MediationClient, MediationCredential
from market_arkhai_mediation.contract import INTERFACE, wire
from market_arkhai_mediation.models import DeliveryEndClaim
from market_core.schemas import Agreement
from market_deal_lifecycle.adapters import DisputeAdapterTable, PaymentAdapterTable, PaymentSelector
from market_deal_lifecycle_contracts.models import Accepted, CommitMessage, ListDealsRequest, Pending, Rejected, SubmitResponse, Unknown
from market_deal_servicing import (
    Classification, DealWatch, DeliveryIngress, EndService, EndSession,
    FinalRequest, LifecycleRouteBinding, LifecycleRouteServices, RespondentPoller,
    SellerServicing, SellerSession, SQLiteEvidenceStore, VerifiedSiteEnd,
)
from market_deal_servicing.evidence import transaction
from market_identity import Identity, canonical_json

from .lifecycle_records import register_agreement
from .models import BareMetalSettleRequest
from .settlement_stages import SettlementRequestError


class BareMetalLifecycle:
    def __init__(self, runtime):
        self.runtime = runtime
        self.path = runtime.db.db_path
        self.clock = lambda: int(time.time())
        self.evidence = SQLiteEvidenceStore(self.path)
        self.locks: dict[str, asyncio.Lock] = {}
        self.clients = {}
        self.end = EndService(self.path, self, clock=self.clock)
        self.seller = SellerServicing(
            self.path,
            payments=PaymentAdapterTable([(PaymentSelector("arkhai.payments.v1"), self.payment)]),
            disputes=DisputeAdapterTable([(INTERFACE, self.dispute)]),
            credential_available=self.credential_available,
            watch_factory=self.watch, clock=self.clock,
        )
        self.ingress = DeliveryIngress(
            self.path, clock=self.clock, verify_site=self.verify_site,
            receipt_claim=self.receipt_claim,
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
        credential = self.runtime.settlement_composition.disputes.config.credential_for(binding.authority)
        if credential is None:
            raise ValueError("Agreement dispute credential is missing")
        key = binding.authority.model_dump_json()
        if key not in self.clients:
            self.clients[key] = MediationClient(
                binding.authority, MediationCredential(binding.authority.identity, credential.api_key_env),
            )
        return MediationAdapter(binding, json.loads(self.agreement_bytes(binding.negotiation_id)), self.clients[key], clock=self.clock)

    def watch(self, deal, payment, dispute):
        account = payment.data.mandate.to.root if payment else ""
        agreement, _ = self.agreement(deal.negotiation_id)
        buyer = Identity.model_validate(agreement.buyer)

        def actor(value):
            if payment and value == payment.data.mandate.from_.root:
                return buyer
            if value == account or value == "terms":
                return self.runtime.seller_principal
            if deal.dispute and value == deal.dispute.account:
                # The authority identity remains in the verified event evidence;
                # the neutral attribution requires a marketplace principal.
                return self.runtime.seller_principal
            raise ValueError("unrecognized payment actor")

        return DealWatch(
            self.path, negotiation_id=deal.negotiation_id, commitment_ref=deal.commitment_ref,
            payment=payment, dispute=dispute, dispute_binding=deal.dispute_binding,
            seller_account=account, actor=actor, clock=self.clock,
        )

    def admit(self, negotiation_id, phase):
        with transaction(self.path) as conn:
            session = EndSession(conn)
            record = session.read(negotiation_id)
            result = session.admit(negotiation_id, phase, record.revision, now=self.clock())
        if result.status != "admitted":
            raise ValueError("delivery ended before " + phase.value)

    def lease_window(self, negotiation_id):
        with transaction(self.path) as conn:
            record = EndSession(conn).read(negotiation_id)
        return tuple(datetime.fromtimestamp(at, timezone.utc).isoformat() for at in (record.start_at, record.term_end))

    def available(self, negotiation_id, at):
        with transaction(self.path) as conn:
            session = EndSession(conn)
            record = session.read(negotiation_id)
            if record.available_at is not None:
                return
            result = session.available(negotiation_id, at=at, expected_revision=record.revision, now=self.clock())
        if result.status != "admitted":
            raise ValueError("delivery ended before disclosure")

    async def apply_end(self, negotiation_id, *, terminate, at, operation_key):
        with transaction(self.path) as conn:
            selected = EndSession(conn).selected_end(negotiation_id)
        result = await self.runtime.fulfillment_service().apply_end(
            negotiation_id, terminate=terminate, at=at, operation_key=operation_key,
            reason=selected.cause if selected else "lifecycle_end",
        )
        # A reservation or dispatched create may still be in flight. Its owner
        # adopts the returned identity and re-drives this pending end on exit.
        in_flight = self.lock(negotiation_id).locked()
        return result.model_copy(update={
            "done": result.done and not in_flight,
            "progress": "end_recorded" if in_flight and result.progress == "released" else result.progress,
        })

    async def local_end(self, negotiation_id, *, cause):
        self.binding(negotiation_id)
        now = self.clock()
        with transaction(self.path) as conn:
            session = EndSession(conn)
            if not any(request.source_ref == cause for request in session.requests(negotiation_id)):
                self._record_local_end(session, negotiation_id, cause, now)
        await self.end.drive_physical(negotiation_id)

    def _record_local_end(self, session, negotiation_id, cause, now):
        session.record_end(FinalRequest(
                negotiation_id=negotiation_id, source_ref=cause,
                ended_at=now, observed_at=now, actor=self.runtime.seller_principal,
                cause=cause, source="terminal_settlement", evidence_refs=[cause],
        ), now=now, classification=Classification(kind="terms", evidence_refs=[cause]))

    def receipt_claim(self, negotiation_id, at):
        agreement, _ = self.agreement(negotiation_id)
        if agreement.settlement is None or agreement.settlement.lifecycle is None:
            return None
        return wire(sign_claim(
            agreement=hashlib.sha256(canonical_json(json.loads(self.agreement_bytes(negotiation_id)))).hexdigest(),
            signer=self.runtime.marketplace_signer,
            claim=DeliveryEndClaim(kind="delivery_end", ended_at=at, delivered=True, cause="payer"),
        ))

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
        return VerifiedSiteEnd(
            event_id=event.event_id, capacity_reservation_id=row[0], ended_at=event.effective_at,
            actor=report.signer, cause=event.cause,
        )

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
        with transaction(self.path) as conn:
            deals, _ = SellerSession(conn).page(ListDealsRequest(limit=100))
        authorities = {}
        for deal in deals:
            if deal.dispute and self.credential_available(deal.dispute):
                authorities.setdefault(deal.dispute.model_dump_json(), deal)
        # Discovery and answering precede watch, sharing its case-keyed journal.
        for deal in authorities.values():
            adapter = self.dispute(deal.dispute_binding)

            def resolve(case):
                for candidate in deals:
                    if candidate.dispute == deal.dispute and candidate.commitment_ref == case.commitment_ref:
                        resolved = self.dispute(candidate.dispute_binding)
                        if resolved.agreement_digest == case.agreement_ref:
                            return candidate.negotiation_id, resolved
                return None

            await RespondentPoller(
                self.path, authority=deal.dispute, account=self.payment(deal).data.mandate.to.root,
                read=adapter.respondent, resolve=resolve, signer=self.runtime.marketplace_signer,
                clock=self.clock,
            ).poll()
        for deal in deals:
            await self.seller.read(deal.negotiation_id)
            await self.seller.dispatch_filings(deal.negotiation_id)
            await self.end.drive_physical(deal.negotiation_id)
        return len(deals)

    async def close(self):
        for client in self.clients.values():
            await client.close()
        self.clients.clear()
