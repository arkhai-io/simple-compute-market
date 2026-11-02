"""VM composition of committed deals, authority watches and retained envelopes."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime
from pathlib import Path

from market_arkhai_mediation.adapter import MediationAdapter
from market_arkhai_mediation.client import MediationClient, MediationCredential
from market_arkhai_mediation.contract import INTERFACE
from market_arkhai_payments import PaymentSettlementData
from market_core.schemas import Agreement
from market_deal_lifecycle.adapters import (
    DisputeAdapterTable, PaymentAdapterTable, PaymentBinding, PaymentSelector,
)
from market_deal_lifecycle.evidence import CommitmentAttempt
from market_deal_lifecycle.terms import decode_terms
from market_deal_lifecycle_contracts.models import (
    Accepted, CommitMessage, ListDealsRequest, Pending, Rejected, SubmitResponse, Unknown,
)
from market_deal_servicing import (
    DealWatch, DeliveryRecord, EndSession, LifecycleRouteBinding,
    LifecycleRouteServices, RespondentPoller, SellerDeal, SellerServicing,
    SellerSession, SQLiteEvidenceStore,
)
from market_deal_servicing.evidence import EvidenceSession, transaction
from market_deal_servicing.journal import atomic
from market_deal_servicing.watch import WatchSession, create_schema as create_watch_schema
from market_identity import Identity, canonical_json

from market_storefront.settlement_stages import PaymentSettlementError

logger = logging.getLogger(__name__)


def instant(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


class VmDealLifecycle:
    def __init__(self, db, signer, payments, disputes, *, clock=lambda: int(time.time())):
        self.db = db
        self.path = Path(db.db_path)
        self.signer = signer
        self.payments_coordinator = payments
        self.dispute_config = disputes.config
        self.clock = clock
        self.evidence = SQLiteEvidenceStore(self.path)
        with transaction(self.path) as conn:
            create_watch_schema(conn)
        self.clients = {}
        self.respondents = {}
        self.continuation = None
        payment_entries = []
        if payments is not None:
            payment_entries.append((PaymentSelector("arkhai.payments.v1"), self.payment_adapter))
        self.seller = SellerServicing(
            self.path, payments=PaymentAdapterTable(payment_entries),
            disputes=DisputeAdapterTable([(INTERFACE, self.dispute_adapter)]),
            credential_available=self.credential_available,
            watch_factory=self.watch, clock=clock,
        )

    def accepted(self, negotiation_id):
        with transaction(self.path) as conn:
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
                authority, MediationCredential(authority.identity, credential.api_key_env),
            )
        return self.clients[key]

    def dispute_adapter(self, binding):
        agreement, _ = self.accepted(binding.negotiation_id)
        return MediationAdapter(binding, agreement, self.client(binding.authority), clock=self.clock)

    def watch(self, deal, payment, dispute):
        agreement, raw = self.accepted(deal.negotiation_id)
        data = PaymentSettlementData.parse(raw)
        return DealWatch(
            self.path, negotiation_id=deal.negotiation_id, commitment_ref=deal.commitment_ref,
            payment=payment, dispute=dispute, dispute_binding=deal.dispute_binding,
            seller_account=data.mandate.to.root,
            actor=lambda _: Identity.model_validate(agreement["seller"]), clock=self.clock,
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

    async def cycle(self, *, limit=100):
        with transaction(self.path) as conn:
            deals, self.continuation = SellerSession(conn).page(ListDealsRequest(
                limit=limit, continuation=self.continuation,
            ))
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
            try:
                async for _ in self.seller.watch(deal.negotiation_id):
                    pass
            except Exception:
                logger.exception("VM lifecycle watch awaits recovery for %s", deal.negotiation_id)
        return len(deals)

    def routes(self, administrators):
        return LifecycleRouteServices(
            seller=self.seller, binding=self.binding, signer=self.signer,
            administrators=administrators, peer=self.peer,
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
        acceptance = self.accepted(negotiation_id) if payload.get("action") == "accept" and payload.get("agreement_bytes") else None
        with transaction(self.path) as conn, atomic(conn):
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
