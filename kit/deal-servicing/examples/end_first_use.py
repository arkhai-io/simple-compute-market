"""Try durable admission, end replay, correction and no-op billing without a server."""

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from market_deal_lifecycle.delivery import (
    ActivatedDeliveryRef, DeliveryEvidence, DeliveryPhase, OnceDeliveryPolicy,
)
from market_identity import Ed25519Signer

from market_deal_servicing import (
    Classification, DeliveryRecord, EndService, EndSession, FinalRequest, PhysicalResult,
)
from market_deal_servicing.evidence import transaction


class DemoDelivery:
    def __init__(self):
        self.dispatched: set[str] = set()
        self.effects: dict[str, PhysicalResult] = {}

    async def apply_end(self, negotiation_id, *, terminate, at, operation_key):
        if operation_key not in self.effects:
            self.effects[operation_key] = PhysicalResult(
                done=True,
                progress="tearing_down" if negotiation_id in self.dispatched else "released",
            )
        return self.effects[operation_key]


async def main():
    # Public deterministic development identity; never use on a public network.
    seller = Ed25519Signer(bytes([2]) * 32).identity
    now = [150]
    physical = DemoDelivery()
    with TemporaryDirectory(prefix="seller-end-") as root:
        path = Path(root) / "storefront.sqlite"
        service = EndService(path, physical, clock=lambda: now[0])
        with transaction(path) as conn:
            session = EndSession(conn)
            for name in ("before", "racing", "billing", "late", "pending"):
                session.register(DeliveryRecord(
                    negotiation_id=name, seller=seller, commitment_ref="commitment",
                    start_at=200 if name == "pending" else 100,
                    term_end=1000, committed_at=100,
                    delivery_deadline_seconds=20 if name == "late" else 500,
                ))
            request = FinalRequest(
                negotiation_id="before", source_ref="ruling", actor=seller,
                cause="ruling", source="dispute", ended_at=150, observed_at=150,
                evidence_refs=["verified-ruling"],
            )
            session.record_end(request, now=150, classification=Classification(
                kind="ruling", evidence_refs=request.evidence_refs,
            ))
            dispatch = session.admit("racing", DeliveryPhase.DISPATCH, 0, now=150)
            if dispatch.status == "admitted":
                physical.dispatched.add("racing")
            session.record_end(request.model_copy(update={"negotiation_id": "racing"}), now=150,
                               classification=Classification(kind="ruling", evidence_refs=request.evidence_refs))
            pending = request.model_copy(update={
                "negotiation_id": "pending", "source_ref": "site-failure",
                "source": "site", "cause": "withdrawal",
            })
            session.record_end(pending, now=150, pending_classification=True)
            record = session.read("pending")
            session.resolve_correction(
                "pending", pending.source_ref, record.revision, evidence=["site-report"],
                classification=Classification(kind="unentitled_withdrawal", evidence_refs=["site-report"]),
                filing_intent=session.failure_filing(pending, now=160, delivered=False),
            )
        await service.drive_physical("before")
        await service.drive_physical("racing")
        await service.drive_physical("racing")
        with transaction(path) as conn:
            session = EndSession(conn)
            assert session.admit("before", DeliveryPhase.ACTIVATE, 0, now=150).status == "retry"
            assert session.view("before").recorded_end.ended_at == 150
            assert session.view("racing").progress == "tearing_down"
            assert len(physical.effects) == 2
            print(json.dumps({
                "restart_admission": session.admit("before", DeliveryPhase.ACTIVATE, 0, now=150).status,
                "current_end": session.view("before").recorded_end.ended_at,
                "racing_progress": session.view("racing").progress,
                "physical_effects": len(physical.effects),
            }))
            earlier = request.model_copy(update={
                "negotiation_id": "racing", "source_ref": "earlier-report", "ended_at": 140,
            })
            session.record_end(earlier, now=150, classification=Classification(
                kind="ruling", evidence_refs=earlier.evidence_refs,
            ))
            pending_filing = next(item for item in session.intents("pending") if item.kind == "filing")
            assert pending_filing.payload["payload"]["ended_at"] == pending_filing.not_before == 200
            assert session.view("racing").recorded_end.ended_at == 140
            print(json.dumps({
                "deferred_filing_at": pending_filing.payload["payload"]["ended_at"],
                "deferred_not_before": pending_filing.not_before,
                "earliest_after_late_report": session.view("racing").recorded_end.ended_at,
            }))
        await service.drive_physical("racing")
        assert len(physical.effects) == 2
        print(json.dumps({"effects_after_earlier_report": len(physical.effects)}))

        async def valid(evidence):
            return evidence.commitment_ref == "commitment"

        adapter = OnceDeliveryPolicy(valid)
        for name in ("billing", "late"):
            evidence = DeliveryEvidence(
                negotiation_id=name, commitment_ref="commitment",
                activated_delivery=ActivatedDeliveryRef(record_ref="activation", activated_at=110),
            )
            result = await service.begin_billing("stable-start", evidence, adapter=adapter)
            assert result.result.outcome.status == ("accepted" if name == "billing" else "rejected")
            assert result.result.no_op == (name == "billing")
            print(json.dumps({
                "deal": name, "billing": result.result.outcome.status,
                "no_financial_action": result.result.no_op,
            }))
        # Retry after reopening uses the same intent and no second start.
        restarted = EndService(path, physical, clock=lambda: now[0])
        result = await restarted.begin_billing(
            "stable-start", DeliveryEvidence(
                negotiation_id="billing", commitment_ref="commitment",
                activated_delivery=ActivatedDeliveryRef(record_ref="activation", activated_at=110),
            ), adapter=adapter,
        )
        assert result.result.outcome.status == "accepted"
        print(json.dumps({"billing_after_restart": result.result.outcome.status}))


if __name__ == "__main__":
    asyncio.run(main())
