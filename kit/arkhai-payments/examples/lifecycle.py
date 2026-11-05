"""Invocation-owned once payment lifecycle using the installed authority fixture."""

import asyncio
import json
import logging
from typing import cast

from market_arkhai_payments.adapter import PaymentAdapter, pinned_snapshot_verifier
from market_arkhai_payments.agreement import PaymentSettlementData
from market_core.schemas import Agreement, derive_settlement_option_id
from market_arkhai_payments.errors import PaymentsTransportError
from market_arkhai_payments.fixtures import FakePaymentsClient, dispute_lifecycle, sign_snapshot
from market_arkhai_payments.settlement_config import ArkhaiPaymentsConfig
from market_arkhai_payments.seller import ClientForOwner, PaymentSellerStage, Refunded, RefundUnavailable
from market_arkhai_payments.reconciliation import reconcile_accepted_payments
from market_deal_lifecycle.operations import OperationKeys
from market_deal_lifecycle_contracts.models import Accepted, LifecycleCommand, Unknown
from market_identity import Ed25519Signer


async def main() -> None:
    # Public deterministic development identity, never use on a public network.
    signer = Ed25519Signer(bytes([7]) * 32)
    lifecycle = dispute_lifecycle("33333333-3333-4333-8333-333333333333")
    settlement = {"schema": "arkhai.payments.v1", "payee_account": "22222222-2222-4222-8222-222222222222",
                  "window": "P7D", "deposit_agreement": False}
    price = {"asset": "USD/2", "rates": []}
    agreement = Agreement.model_validate({
        "negotiation_id": "once-lifecycle-example", "listing_id": "example", "listing_hash": "a" * 64,
        "buyer": {"scheme": "ed25519", "identifier": "buyer-fixture"},
        "seller": {"scheme": "ed25519", "identifier": "seller-fixture"},
        "settlement": {
            "option_id": derive_settlement_option_id(price=price, settlement=settlement, lifecycle=lifecycle),
            "price": price, "settlement": settlement, "lifecycle": lifecycle,
        },
        "settlement_params": {"payer_account": "11111111-1111-4111-8111-111111111111"},
        "amount": 10000, "asset": "USD/2", "duration_seconds": 3600,
        "accepted_at": "2026-10-07T12:00:00Z", "start_utc": "2026-10-07T12:00:10Z",
        "provision_terms": {"kind": "example.v1", "version": 1, "payload": {}},
    }).model_dump(mode="json", exclude_none=True)
    config = ArkhaiPaymentsConfig(
        enabled=True, service_url="http://127.0.0.1:9", service_identity=signer.identity,
        fee_bps=250, development_auth=True,
    )
    data = PaymentSettlementData.for_agreement(agreement, config)

    class LostResponse(FakePaymentsClient):
        lose = True

        def submit_event(self, transaction, event, *, request_id):
            result = super().submit_event(transaction, event, request_id=request_id)
            if self.lose:
                self.lose = False
                raise PaymentsTransportError("response lost after authority recorded reverse")
            return result

    fake = LostResponse(signer=signer)
    fake.approve(data.mandate)
    adapter = PaymentAdapter(
        agreement, data, account=data.mandate.to.root, client_for_owner=fake,
        verify_snapshot=pinned_snapshot_verifier(agreement, data, config),
    )
    command = LifecycleCommand(
        negotiation_id=agreement["negotiation_id"], kind="reverse", operation_key="voluntary-discount",
        payload={"part": "0", "amount": "100"},
    )
    keys = OperationKeys(command.negotiation_id, command.operation_key)
    initial = await adapter.submit(command, keys)
    recovered = await adapter.read()
    replay = await adapter.submit(command, keys)
    assert isinstance(initial, Unknown)
    assert isinstance(recovered.outcome, Accepted) and len(recovered.events) == 1
    assert isinstance(replay, Accepted) and replay.records == recovered.events
    changed = command.model_copy(update={"payload": {"part": "0", "amount": "101"}})
    assert (await adapter.submit(changed, keys)).status == "rejected"
    assert recovered.state == "running" and recovered.deadline is None
    # Script only the observation boundary: rulings are the dispute authority's
    # actions, not operations this party's once adapter sends or computes.
    class CaseProjection(LostResponse):
        def get_transaction(self, transaction):
            body = super().get_transaction(transaction).snapshot.model_dump(
                mode="json", by_alias=True, exclude_none=True,
            )
            for sequence, event, case in [
                (2, {"kind": "extend", "part": 0}, "case-A"),
                (3, {"kind": "reverse", "part": 0, "amount": "2500"}, "case-A"),
                (4, {"kind": "extend", "part": 0}, "case-B"),
                (5, {"kind": "reverse", "part": 0, "amount": "1000"}, "case-B"),
                (6, {"kind": "lift", "part": 0, "ref": 2}, "case-A"),
            ]:
                body["events"].append({
                    "account": "33333333-3333-4333-8333-333333333333",
                    "requestId": f"case-effect-{sequence}", "sequence": sequence,
                    "receivedAt": self.observed_at, "event": {**event, "payload": {"case_ref": case}},
                })
            body["latestEventSequence"] = 6
            body["parts"][0].update(held="6400", reversed="3600", extensions=[{"ref": 4}])
            return sign_snapshot(signer, body)

    projection = CaseProjection(signer=signer)
    projection.serve(fake.receipt, mandate=data.mandate)
    projection.submit(data.transaction_id, {
        "account": data.mandate.to.root, "requestId": keys.part_event("0", "reverse"),
        "event": {"kind": "reverse", "part": 0, "amount": "100"},
    })
    observed = await PaymentAdapter(
        agreement, data, account=data.mandate.to.root, client_for_owner=projection,
        verify_snapshot=pinned_snapshot_verifier(agreement, data, config),
    ).read()
    assert isinstance(observed.outcome, Accepted) and observed.state == "running"
    assert [e.amount for e in observed.events if e.case_ref and e.kind == "reverse"] == ["2500", "1000"]
    assert len(observed.extensions) == 1 and observed.extensions[0].case_ref == "case-B"
    assert observed.extensions[0].extension_ref == "4" and observed.deadline is None
    seller = PaymentSellerStage(config, client_for_owner=cast(ClientForOwner, fake))
    fake.lose = True
    refunds = []

    async def settle_unreported(negotiation_id):
        assert negotiation_id == agreement["negotiation_id"]
        answer = await seller.reverse(agreement, data)
        refunds.append(type(answer).__name__)
        if isinstance(answer, RefundUnavailable):
            raise RuntimeError(answer.reason)
        assert isinstance(answer, Refunded)

    logger = logging.getLogger("once-lifecycle-example")
    first = await reconcile_accepted_payments([command.negotiation_id], settle_unreported, logger=logger)
    retry = await reconcile_accepted_payments([command.negotiation_id], settle_unreported, logger=logger)
    crash_replay = await reconcile_accepted_payments([command.negotiation_id], settle_unreported, logger=logger)
    assert (first.failed, retry.failed, crash_replay.failed) == (1, 0, 0)
    assert len(fake.engine.snapshot(data.transaction_id).snapshot.events) == 2
    print(json.dumps({
        "initial": initial.status, "read": recovered.model_dump(mode="json"),
        "replay": replay.status, "recorded_reverses": len(recovered.events),
        "changed_retry": "rejected", "observed_case_effects": observed.model_dump(mode="json"),
        "unreported_refund_reconciliation": refunds, "total_voluntary_reverses": 2,
    }, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
