"""First use of the hosted rate library against an invocation-owned authority.

No services, credentials, database or deployed recurring servicing are required.
The printed observations are fixture evidence, not hosted qualification.
"""

import asyncio
from datetime import datetime, timezone
import json

from market_core.schemas import Agreement
from market_deal_lifecycle.configuration import DisputeEntry
from market_deal_lifecycle.delivery import DeliveryEvidence, DeliveryPhase
from market_deal_lifecycle.operations import OperationKeys
from market_deal_lifecycle_contracts.models import LifecycleCommand
from market_identity import Ed25519Signer
from market_settlement_runtime import SettlementPublicationClause
from market_settlement_runtime.rate_publication import derive_rate_preset, RatePresetRefusal
from market_settlement_runtime.rate_servicing import RateServicing, RateServicingDeclaration

from market_arkhai_payments.adapter import pinned_snapshot_verifier
from market_arkhai_payments.agreement import PaymentSettlementData
from market_arkhai_payments.buyer import PaymentApproval
from market_arkhai_payments.fixtures import FakePaymentsClient, dispute_lifecycle
from market_arkhai_payments.errors import PaymentsTransportError
from market_arkhai_payments.operations import operations_digest
from market_arkhai_payments.presets import PaymentsRatePresetHelper, rate_contract_revision
from market_arkhai_payments.rate_adapter import RatePaymentAdapter
from market_arkhai_payments.settlement_config import ArkhaiPaymentsConfig

MECHANISM = "arkhai.payments.v1"
PAYER = "11111111-1111-4111-8111-111111111111"
PAYEE = "22222222-2222-4222-8222-222222222222"
DISPUTE = "33333333-3333-4333-8333-333333333333"


async def main() -> None:
    # Public deterministic development identity, never use on a public network.
    signer = Ed25519Signer(bytes([7]) * 32)
    now = 1_800_000_000
    authority = DisputeEntry.model_validate({
        **dispute_lifecycle(DISPUTE)["adjudication"]["dispute"],
        "advertisement": {"mechanisms": [MECHANISM], "minimum_dispute_window_seconds": 0,
                          "minimum_case_hold_seconds": None},
    })
    servicing = RateServicing(
        required_contracts={MECHANISM: rate_contract_revision()},
        declarations={MECHANISM: RateServicingDeclaration(MECHANISM, rate_contract_revision(), "published")},
    )
    clause = SettlementPublicationClause.model_validate({
        "mechanism": MECHANISM, "asset": "USD/2", "rate": "60", "per": "hour",
        "mechanism_input": {"asset": "USD/2", "payee_account": PAYEE,
                            "approval_window": "PT10S", "dispute_window_seconds": 3600},
        "recurring": {"period": "PT60S", "reserve_ahead_seconds": 120,
                      "setup_amount": "25", "payee_notice_seconds": 30},
    })
    option = derive_rate_preset(
        clause, helper=PaymentsRatePresetHelper(), servicing=servicing, authorities=(authority,),
        max_duration_seconds=3600, available_until_utc=None, delivery_deadline_seconds=30,
        now=datetime.fromtimestamp(now, timezone.utc), default_penalty_periods=24,
    )
    if isinstance(option, RatePresetRefusal):
        raise RuntimeError(option)
    stamp = datetime.fromtimestamp(now, timezone.utc).isoformat().replace("+00:00", "Z")
    agreement = Agreement.model_validate({
        "negotiation_id": "rate-first-use", "listing_id": "example", "listing_hash": "a" * 64,
        "buyer": {"scheme": "ed25519", "identifier": "buyer-fixture"},
        "seller": {"scheme": "ed25519", "identifier": "seller-fixture"},
        "settlement": option, "settlement_params": {"payer_account": PAYER},
        "amount": 100, "asset": "USD/2", "duration_seconds": 3600,
        "accepted_at": stamp, "start_utc": stamp,
        "provision_terms": {"kind": "example.v1", "version": 1, "payload": {}},
    }).model_dump(mode="json", exclude_none=True)
    config = ArkhaiPaymentsConfig(enabled=True, service_url="http://127.0.0.1:9",
                                 service_identity=signer.identity, fee_bps=250, development_auth=True)
    data = PaymentSettlementData.for_agreement(agreement, config, rate_servicing=servicing)
    PaymentApproval(config, PAYER).check(json.dumps(agreement), data.to_wire())

    class LostResponse(FakePaymentsClient):
        lose = True

        def submit_event(self, transaction, event, *, request_id):
            result = super().submit_event(transaction, event, request_id=request_id)
            if self.lose:
                self.lose = False
                raise PaymentsTransportError("response lost after authority recorded start")
            return result

    fake = LostResponse(signer=signer, observed_at=now)
    fake.approve(data.mandate)
    seller = RatePaymentAdapter(agreement, data, account=PAYEE, client_for_owner=fake,
                               verify_snapshot=pinned_snapshot_verifier(agreement, data, config), clock=lambda: fake.observed_at)
    evidence = DeliveryEvidence.model_validate({
        "negotiation_id": agreement["negotiation_id"], "commitment_ref": data.transaction_id,
        "reservation_ref": "fixture-reservation", "fulfillment_ref": "fixture-fulfillment",
        "activated_delivery": {"record_ref": "fixture-site-activation", "activated_at": now},
        "ready": {"schema_id": "example.ready.v1", "resource_ref": "fixture-resource", "digest": "b" * 64},
    })
    before = await seller.authorize(DeliveryPhase.START, evidence)
    operations = seller.billing_operations("sole-end-service-start", evidence)
    # A real caller persists these exact descriptors with its activation envelope
    # under the sole end-service key, before issuing either call.
    digest = operations_digest(operations)
    first = await seller.start_billing("sole-end-service-start", evidence, journaled_digest=digest)
    retry = await seller.start_billing("sole-end-service-start", evidence, journaled_digest=digest)
    disclosed = await seller.authorize(DeliveryPhase.DISCLOSE, evidence, billing_operation_key="sole-end-service-start")
    stop = LifecycleCommand(negotiation_id=agreement["negotiation_id"], kind="stop", operation_key="spot-notice", payload={"part": "1"})
    keys = OperationKeys(stop.negotiation_id, stop.operation_key)
    stopped = await seller.submit(stop, keys, journaled_digest=seller.describe(stop, keys).digest)
    pending = await seller.read()
    payer = RatePaymentAdapter(agreement, data, account=PAYER, client_for_owner=fake,
                              verify_snapshot=pinned_snapshot_verifier(agreement, data, config), clock=lambda: fake.observed_at)
    fake.observed_at += 1
    payer_stop = LifecycleCommand(negotiation_id=agreement["negotiation_id"], kind="stop",
                                  operation_key="payer-protection-stop", payload={"part": "1"})
    payer_keys = OperationKeys(payer_stop.negotiation_id, payer_stop.operation_key)
    payer_stopped = await payer.submit(payer_stop, payer_keys,
                                       journaled_digest=payer.describe(payer_stop, payer_keys).digest)
    fake.observed_at += 29
    ended = await seller.read()
    print(json.dumps({
        "evidence_class": "fixture", "before_activation": before.status,
        "lost_start_response": first.outcome.status, "same_key_retry": retry.outcome.status,
        "disclose": disclosed.status, "notice": stopped.status, "payer_stop": payer_stopped.status,
        "pending": pending.model_dump(mode="json"), "ended": ended.model_dump(mode="json"),
        "mandate": data.to_wire(),
    }, indent=2))
    if (before.status, first.outcome.status, retry.outcome.status, disclosed.status, stopped.status,
        pending.state, ended.state, payer_stopped.status) != ("allow", "unknown", "accepted", "allow", "accepted", "ending", "ended", "accepted"):
        raise RuntimeError("rate first-use outcome differs from the expected library flow")


if __name__ == "__main__":
    asyncio.run(main())
