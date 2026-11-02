"""Durable, independent buyer stop, receipt-only surrender and case progress."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import TYPE_CHECKING

from market_deal_lifecycle.acknowledgements import verify_end_acknowledgement
from market_deal_lifecycle.adapters import DeliveryEndIntent
from market_deal_lifecycle.claims import DeliveryEndClaims
from market_deal_lifecycle_contracts.models import (
    Accepted, EndDeliveryAcknowledgement, EvidenceItem, Instant, LifecycleCommand,
    LifecycleOutcome, Pending, Rejected, SignedEndDeliveryReceipt, Unknown, WireModel,
)
from market_identity import canonical_json

if TYPE_CHECKING:
    from .lifecycle import BuyerLifecycle


class EndDeliveryProgress(WireModel):
    negotiation_id: str
    observed_at: Instant
    payment: LifecycleOutcome = Pending(reason="stop not yet attempted")
    delivery: LifecycleOutcome = Pending(reason="surrender not yet attempted")
    case: LifecycleOutcome = Pending(reason="filing not yet attempted")
    acknowledgement: EndDeliveryAcknowledgement | None = None


class EndPlan(WireModel):
    commitment_ref: str
    operation_key: str
    revision: int = 0
    progress: EndDeliveryProgress
    stop: LifecycleCommand
    filing: LifecycleCommand | None = None
    receipt: SignedEndDeliveryReceipt | None = None


class BuyerEndJournal:
    """CAS progress and immutable commands; no timer, payment ledger or authority."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.touch(mode=0o600, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS buyer_delivery_ends (
                negotiation_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, plan TEXT NOT NULL
            )""")

    @staticmethod
    def _decode_plan(raw: str) -> EndPlan:
        data = json.loads(raw)
        data["progress"].pop("contested", None)
        return EndPlan.model_validate(data)

    def begin(self, proposed: EndPlan) -> EndPlan:
        negotiation_id = proposed.progress.negotiation_id
        with sqlite3.connect(self.path, timeout=30) as db:
            db.execute("INSERT OR IGNORE INTO buyer_delivery_ends VALUES (?,?,?)",
                       (negotiation_id, 0, proposed.model_dump_json()))
            row = db.execute("SELECT plan FROM buyer_delivery_ends WHERE negotiation_id=?", (negotiation_id,)).fetchone()
        plan = self._decode_plan(row[0])
        if plan.commitment_ref != proposed.commitment_ref or plan.operation_key != proposed.operation_key:
            raise ValueError("buyer end journal names a different committed deal")
        return plan

    def save(self, previous: EndPlan, **updates) -> EndPlan:
        updated = previous.model_copy(update={**updates, "revision": previous.revision + 1})
        negotiation_id = previous.progress.negotiation_id
        with sqlite3.connect(self.path, timeout=30) as db:
            db.execute(
                "UPDATE buyer_delivery_ends SET revision=?,plan=? WHERE negotiation_id=? AND revision=?",
                (updated.revision, updated.model_dump_json(), negotiation_id, previous.revision),
            )
            row = db.execute("SELECT plan FROM buyer_delivery_ends WHERE negotiation_id=?", (negotiation_id,)).fetchone()
        return self._decode_plan(row[0])


async def end_delivery(lifecycle: BuyerLifecycle, negotiation_id: str) -> EndDeliveryProgress:
    deal = lifecycle._deal(negotiation_id)
    if deal.buyer is None or deal.seller is None or lifecycle.end_journal is None or lifecycle.evidence is None:
        raise ValueError("end_delivery requires Agreement principals, durable end journal and evidence store")
    key = hashlib.sha256(canonical_json(["buyer-end", negotiation_id, deal.commitment_ref])).hexdigest()
    journal = lifecycle.end_journal
    plan = journal.begin(EndPlan(
        commitment_ref=deal.commitment_ref, operation_key=key,
        progress=EndDeliveryProgress(negotiation_id=negotiation_id, observed_at=lifecycle.clock()),
        stop=LifecycleCommand(negotiation_id=negotiation_id, kind="stop", operation_key=key + ":stop"),
    ))
    observed = canonical_json({
        "kind": "end_delivery", "negotiation_id": negotiation_id,
        "operation_key": key, "observed_at": plan.progress.observed_at,
    })
    await lifecycle.evidence.put(negotiation_id, EvidenceItem(
        evidence_id="end-observation:" + key, kind="end_delivery_observation",
        classification="buyer_observation", recorded_at=plan.progress.observed_at,
        body=base64.b64encode(observed), context={
            "producer": deal.buyer.model_dump(mode="json"),
            "digest": hashlib.sha256(observed).hexdigest(),
        },
    ))
    if not isinstance(plan.progress.payment, (Accepted, Rejected)):
        try:
            payment = await lifecycle.submit(plan.stop)
        except Exception:
            payment = Unknown(reason="payment stop is unreachable; billing continues until it lands")
        plan = journal.save(plan, progress=plan.progress.model_copy(update={"payment": payment}))
    # Surrender is independent of payment availability and never carries at.
    if plan.receipt is None:
        try:
            acknowledgement = await lifecycle.peer.end_delivery(negotiation_id, operation_key=key + ":surrender")
            receipt = lifecycle.peer.end_receipt(negotiation_id, key + ":surrender")
            verified = verify_end_acknowledgement(
                receipt, negotiation_id=negotiation_id, buyer=deal.buyer, seller=deal.seller,
            )
            if verified != acknowledgement or verified.operation_key != key + ":surrender":
                raise ValueError("peer acknowledgement differs from its exact signed receipt")
            intent = DeliveryEndIntent(ended_at=verified.receipt_at, delivered=True, cause="payer")
            adapter = lifecycle.disputes.resolve(deal.dispute) if deal.dispute else None
            # The exact seller-signed receipt acknowledges surrender even when
            # no dispute adapter is installed. That absence cannot confer a
            # refund; concurrence is interpreted only by an installed adapter.
            if verified.signed_delivery_end_claim is not None and adapter is not None and (
                not isinstance(adapter, DeliveryEndClaims)
                or not adapter.verify_delivery_end(verified.signed_delivery_end_claim, intent)
            ):
                raise ValueError("receipt concurrence does not bind the exact Agreement claim")
            body = canonical_json(receipt)
            await lifecycle.evidence.put(negotiation_id, EvidenceItem(
                evidence_id="end-receipt:" + hashlib.sha256(body).hexdigest(),
                kind="end_delivery_receipt", classification="seller_assertion",
                recorded_at=verified.receipt_at, body=base64.b64encode(body), context={
                    "producer": deal.seller.model_dump(mode="json"),
                    "digest": hashlib.sha256(body).hexdigest(),
                },
            ))
            plan = journal.save(plan, receipt=receipt, progress=plan.progress.model_copy(update={
                "acknowledgement": verified, "delivery": Accepted(),
            }))
        except Exception:
            plan = journal.save(plan, progress=plan.progress.model_copy(update={
                "delivery": Unknown(reason="storefront surrender was not acknowledged; observed time is contested"),
            }))
    if plan.filing is None and not isinstance(plan.progress.case, Rejected):
        adapter = lifecycle.disputes.resolve(deal.dispute) if deal.dispute else None
        if adapter is None:
            plan = journal.save(plan, progress=plan.progress.model_copy(update={
                "case": Rejected(reason="no Agreement dispute adapter; surrender invents no refund"),
            }))
        else:
            kept_acknowledgement = plan.progress.acknowledgement
            if kept_acknowledgement is None:
                # An uncertain surrender may already be durable at the seller.
                # Resolve its same key before fixing a claim or signing a time.
                return journal.save(plan, progress=plan.progress.model_copy(update={
                    "case": Pending(reason="filing awaits the original surrender acknowledgement"),
                })).progress
            if kept_acknowledgement.selected_end.cause != "buyer_surrender":
                return journal.save(plan, progress=plan.progress.model_copy(update={
                    "case": Rejected(reason="selected end is not buyer surrender; no automatic payer filing"),
                })).progress
            intent = DeliveryEndIntent(
                ended_at=kept_acknowledgement.receipt_at,
                delivered=True, cause="payer",
            )
            signed = kept_acknowledgement.signed_delivery_end_claim
            request = (adapter.concurrent_request(intent, signed) if isinstance(adapter, DeliveryEndClaims)
                       else adapter.build_request(intent))
            if isinstance(request, Rejected):
                plan = journal.save(plan, progress=plan.progress.model_copy(update={"case": request}))
            else:
                # Persist the exact receipt-backed request before authority I/O;
                # retries cannot change its evidence basis.
                plan = journal.save(plan, filing=LifecycleCommand(
                    negotiation_id=negotiation_id, kind="dispute", operation_key=key + ":case",
                    payload=request.model_dump(mode="json"),
                ))
    if plan.filing is not None and not isinstance(plan.progress.case, (Accepted, Rejected)):
        try:
            outcome = await lifecycle.submit(plan.filing)
        except Exception:
            outcome = Unknown(reason="delivery-end filing is unreachable; retry uses its original key")
        plan = journal.save(plan, progress=plan.progress.model_copy(update={"case": outcome}))
    return plan.progress
