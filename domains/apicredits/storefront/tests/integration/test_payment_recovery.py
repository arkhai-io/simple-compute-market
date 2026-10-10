"""Payment recovery through seller settlement and durable SQLite evidence."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from market_arkhai_payments import (
    ARKHAI_PAYMENTS_MECHANISM,
    ArkhaiPaymentsConfig,
    servicing_stage,
)
from market_arkhai_payments.fixtures import FakePaymentsClient, build_signed_receipt
from market_core.schemas import Agreement, SettlementOption, derive_settlement_option_id
from market_identity import Ed25519Signer

from apicredits_storefront import settlement_stages
from apicredits_storefront.domain_runtime import get_market_domain_contract
from apicredits_storefront.services.payment_settlement_service import (
    ApiCreditPaymentSettlementService,
)
from apicredits_storefront.settlement_composition import SELLER_STAGES
from apicredits_storefront.settlement_models import ApiCreditsSettleRequest
from apicredits_storefront.settlement_stages import SettlementRefusal
from apicredits_storefront.utils.sqlite_client import SQLiteClient
from arkhai_apicredits.negotiation.terms import make_api_credits_provision_terms
from arkhai_apicredits.settlement.credits_client import CreditIssuanceResult

BUYER = Ed25519Signer(bytes.fromhex("11" * 32))
SELLER = Ed25519Signer(bytes.fromhex("22" * 32))
SERVICE = Ed25519Signer(bytes.fromhex("55" * 32))
PAYER = "11111111-1111-4111-8111-111111111111"
PAYEE = "22222222-2222-4222-8222-222222222222"
DISPUTE = "33333333-3333-4333-8333-333333333333"


class IssuanceBoundary:
    def __init__(self):
        self.grants = {}
        self.lose_ack = True

    async def submit_credit_issuance(self, request):
        already_issued = request.fulfillment_id in self.grants
        self.grants.setdefault(request.fulfillment_id, request)
        if self.lose_ack:
            self.lose_ack = False
            raise TimeoutError("lost acknowledgement after grant commit")
        return CreditIssuanceResult(
            fulfillment_id=request.fulfillment_id, grant_id=request.fulfillment_id,
            negotiation_id=request.negotiation_id, owner=request.owner,
            service=request.service, resource_id=request.resource_id, quantity=request.quantity,
            key_mode=request.key.mode, key_id="ak_new", balance=request.quantity,
            request_digest=request.request_digest, committed_at_unix=1_790_000_000,
            already_issued=already_issued, secret="ak_new.test-secret",
        )


@pytest.fixture
async def payment_context(tmp_path):
    db = SQLiteClient(str(tmp_path / "storefront.db"))
    payments = FakePaymentsClient()
    kit_stage = servicing_stage(
        ArkhaiPaymentsConfig(
            enabled=True, service_url="http://127.0.0.1:3180",
            service_identity=SERVICE.identity, fee_bps=0,
            dispute_authority=DISPUTE, development_auth=True,
        ),
        client_for_owner=payments,
    )
    issuance = IssuanceBoundary()
    composition = SimpleNamespace(
        domain=get_market_domain_contract(), credits_client=issuance, arkhai_payments_stage=kit_stage,
    )
    composition.payment_service = lambda store: ApiCreditPaymentSettlementService(
        db=store, composition=composition, stage=kit_stage, mechanism=ARKHAI_PAYMENTS_MECHANISM,
    )
    stage = SELLER_STAGES[ARKHAI_PAYMENTS_MECHANISM]
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    await db.upsert_listing(
        listing_id="listing-payment", status="open", created_at=now, updated_at=now,
        listing_resource={"service_name": "test-api", "resource_id": "svc-quota",
                          "capacity_site_id": "quota", "offering_mode": "api_credits",
                          "base_url": "http://api.local"},
        fulfillment_resource=None, max_duration_seconds=None,
        storefront_url="http://storefront.local", seller_principal=SELLER.identity,
    )
    params = {"payee_account": PAYEE, "asset": "USD/2", "window": "P7D", "deposit_agreement": True}
    option = SettlementOption(
        option_id=derive_settlement_option_id(mechanism=ARKHAI_PAYMENTS_MECHANISM, asset="USD/2", rates=[], params=params),
        mechanism=ARKHAI_PAYMENTS_MECHANISM, asset="USD/2", rates=[], params=params,
    )
    terms = make_api_credits_provision_terms(quantity=3, key_mode="new")
    agreement = Agreement(
        negotiation_id="neg-payment", listing_id="listing-payment", listing_hash="a" * 64,
        buyer=BUYER.identity.model_dump(mode="json"), seller=SELLER.identity.model_dump(mode="json"),
        settlement=option, settlement_params={"payer_account": PAYER}, amount=100,
        asset="USD/2", duration_seconds=0, start_utc=now, accepted_at=now,
        provision_terms=terms.model_dump(mode="json"),
    )
    wire = agreement.model_dump(mode="json", exclude_none=True)
    data = kit_stage.settlement_data(wire)
    await db.create_negotiation_thread(
        negotiation_id=agreement.negotiation_id, our_listing_id=agreement.listing_id,
        their_listing_id="", our_agent_id="seller", their_agent_id="buyer", owner_id="seller",
        buyer_principal=BUYER.identity, seller_principal=SELLER.identity,
        provision_terms=terms.model_dump(mode="json"),
    )
    await db.commit_agreed_terms(
        negotiation_id=agreement.negotiation_id, agreed_price=100, agreed_duration_seconds=0,
        agreement_bytes=agreement.model_dump_json(exclude_none=True).encode(),
        accepted_at=now, agreed_start_utc=now,
        settlement_data=stage.agreement_artifacts(wire, composition),
    )
    await db.update_negotiation_thread_terminal(negotiation_id=agreement.negotiation_id, terminal_state="success")
    payments.serve(build_signed_receipt(signer=SERVICE, mandate=data.mandate))
    context = {
        "db": db, "composition": composition, "coordinator": None,
        "reference": agreement.negotiation_id,
        "body": ApiCreditsSettleRequest(negotiation_id=agreement.negotiation_id, buyer_principal=BUYER.identity),
        "signer": SELLER,
        "thread": await db.load_negotiation_thread_row(negotiation_id=agreement.negotiation_id),
    }
    return stage, context, payments, issuance


async def test_lost_ack_recovery_revalidates_stored_receipt_without_rechecking(payment_context):
    stage, context, payments, issuance = payment_context
    pending = await stage.settle(**context)
    assert pending.status_code == 202
    assert pending.payload["status"] == "provisioning" and pending.payload["retryable"]
    assert len(issuance.grants) == 1
    evidence = await context["db"].load_settlement_evidence(negotiation_id=context["reference"])
    assert evidence.status == "verified"
    reads = payments.count("get_transaction")

    payments.unavailable = True
    context["db"] = SQLiteClient(context["db"].db_path)
    ready = await stage.status(**context)

    assert ready.payload["status"] == "ready"
    assert ready.payload["settlement_ref"] == evidence.settlement_ref
    assert len(issuance.grants) == 1
    assert payments.count("get_transaction") == reads
    assert payments.count("reverse") == 0
    assert await context["db"].load_settlement_evidence(negotiation_id=context["reference"]) == evidence


@pytest.mark.parametrize("change", ["status", "source"])
async def test_verified_evidence_refuses_changed_retry_and_preserves_receipt(payment_context, change):
    stage, context, _payments, _issuance = payment_context
    await stage.settle(**context)
    db = context["db"]
    evidence = await db.load_settlement_evidence(negotiation_id=context["reference"])
    assert await db.save_settlement_evidence(evidence) == evidence
    if change == "status":
        changed = replace(evidence, status="pending")
    else:
        source = dict(evidence.evidence["source"])
        source.pop("receipt")
        changed = replace(evidence, evidence={**dict(evidence.evidence), "source": source})
    with pytest.raises(ValueError, match="verified settlement evidence is immutable"):
        await db.save_settlement_evidence(changed)
    assert await db.load_settlement_evidence(negotiation_id=context["reference"]) == evidence


async def test_refund_status_moves_only_through_ordered_transitions(payment_context):
    stage, context, _payments, _issuance = payment_context
    await stage.settle(**context)
    db, reference = context["db"], context["reference"]
    evidence = await db.load_settlement_evidence(negotiation_id=reference)

    intent = await db.record_credit_refund_intent(negotiation_id=reference)
    assert intent == {"status": "verified", "delivery_started": True}
    assert not await db.claim_credit_delivery_start(negotiation_id=reference)
    with pytest.raises(ValueError, match="immutable"):
        await db.save_settlement_evidence(evidence)

    await db.abandon_credit_refund_intent(negotiation_id=reference, prior_status="verified")
    assert (await db.load_settlement_evidence(negotiation_id=reference)) == evidence
    assert await db.claim_credit_delivery_start(negotiation_id=reference)

    await db.record_credit_refund_intent(negotiation_id=reference)
    await db.complete_credit_refund(negotiation_id=reference)
    await db.abandon_credit_refund_intent(negotiation_id=reference, prior_status="verified")
    refunded = await db.load_settlement_evidence(negotiation_id=reference)
    assert refunded == replace(evidence, status="refunded")
    assert not await db.claim_credit_delivery_start(negotiation_id=reference)


async def test_recovery_refuses_a_stored_receipt_with_invalid_signature(payment_context):
    stage, context, payments, issuance = payment_context
    db = context["db"]
    agreement, raw = settlement_stages.accepted_agreement(context["thread"])
    receipt = payments.receipt.model_dump(mode="json", by_alias=True, exclude_none=True)
    receipt["receipt"]["ledger"] = "tampered"
    data = context["thread"]["settlement_data"]
    evidence = settlement_stages.settlement_evidence(
        agreement, raw, reference=data["transaction_id"], status="verified",
        source={**data, "receipt": receipt},
        order=await db.load_listing(listing_id=agreement.listing_id),
    )
    await db.save_settlement_evidence(evidence)

    with pytest.raises(SettlementRefusal, match="does not prove this Agreement") as refused:
        await stage.settle(**context)
    assert refused.value.status_code == 409
    assert issuance.grants == {}
    assert payments.count("get_transaction") == 0
    assert payments.count("ensure_agreement_attached") == 0
    assert await db.load_settlement_evidence(negotiation_id=agreement.negotiation_id) == evidence
