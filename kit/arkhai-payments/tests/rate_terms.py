"""Deterministic accepted rate terms shared by payment contract tests."""

from datetime import datetime, timezone

from market_core.schemas import derive_settlement_option_id
from market_deal_lifecycle.delivery import DeliveryEvidence

from market_arkhai_payments import PaymentSettlementData, derive_mandate, mandate_policy_for_agreement, transaction_id
from market_arkhai_payments.adapter import pinned_snapshot_verifier
from market_arkhai_payments.fixtures import FakePaymentsClient
from market_arkhai_payments.rate_adapter import RatePaymentAdapter

from payment_terms import BUYER, PAYEE, SERVICE, agreement, config

NOW = 1_800_000_000


def rate_agreement(*, setup="25", payee_notice=30, payer_notice=300, treatment="started_period"):
    stamp = datetime.fromtimestamp(NOW, timezone.utc).isoformat().replace("+00:00", "Z")
    raw = agreement(accepted_at=stamp, start_utc=stamp, amount="100")
    option = raw["settlement"]
    option["price"]["rates"] = [{"field": "amount", "per": "hour", "value": 6000}]
    option["settlement"].update(approval_window="PT60S", period="PT60S", reserve_ahead_seconds=120)
    if setup is not None:
        option["settlement"]["setup_amount"] = setup
    rights = {"payer": {"notice_seconds": payer_notice, "settles_through": treatment}}
    if payee_notice is not None:
        rights["payee"] = {"notice_seconds": payee_notice, "settles_through": treatment}
    option["lifecycle"]["delivery_deadline_seconds"] = 30
    option["lifecycle"]["early_termination"] = {
        "version": 1, "entitlements": rights, "settles_through": treatment,
    }
    option["option_id"] = derive_settlement_option_id(**{k: v for k, v in option.items() if k != "option_id"})
    return raw


def rate_data(raw):
    # Approval/command fixtures deliberately bypass publication's installed-hook
    # gate. The production delivery composition still has no rate declaration.
    mandate = derive_mandate(raw, mandate_policy_for_agreement(raw, config()))
    return PaymentSettlementData(mandate=mandate, transaction_id=transaction_id(mandate))


def evidence(raw, data):
    return DeliveryEvidence.model_validate({
        "negotiation_id": raw["negotiation_id"], "commitment_ref": data.transaction_id,
        "reservation_ref": "reservation", "fulfillment_ref": "fulfillment",
        "activated_delivery": {"record_ref": "site-activation", "activated_at": NOW},
        "ready": {"schema_id": "example.ready.v1", "resource_ref": "resource", "digest": "b" * 64},
    })


def approved(*, client_type=FakePaymentsClient, account=PAYEE, **terms):
    raw = rate_agreement(**terms)
    data = rate_data(raw)
    fake = client_type(signer=SERVICE, observed_at=NOW)
    fake.engine.fund(BUYER, "USD/2", 1_000_000)
    fake.receipt = fake.engine.approve(data.mandate, account=BUYER)
    adapter = RatePaymentAdapter(
        raw, data, account=account, client_for_owner=fake,
        verify_snapshot=pinned_snapshot_verifier(raw, data, config()), clock=lambda: fake.observed_at,
    )
    return raw, data, fake, adapter, evidence(raw, data)
