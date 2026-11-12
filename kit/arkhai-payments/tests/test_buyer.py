"""Buyer approval checks and its own attachment policy."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from market_core.schemas import Agreement, SettlementOption
from market_deal_lifecycle.configuration import DisputeEntry
from market_settlement_runtime import SettlementPublicationClause
from market_settlement_runtime.rate_publication import derive_rate_preset
from market_settlement_runtime.rate_servicing import RateServicing, RateServicingDeclaration
from market_settlement_runtime.terms_policy import PermissiveBuyerTermsPolicy

from market_arkhai_payments import (
    MandatePolicyError,
    PaymentApproval,
    PaymentApprovalDeclined,
    PaymentSettlementData,
    ReceiptVerificationError,
    derive_mandate,
    mandate_policy_for_agreement,
    transaction_id,
)
from market_arkhai_payments.fixtures import FakePaymentsClient, build_signed_receipt, dispute_lifecycle
from market_arkhai_payments.presets import PaymentsRatePresetHelper, rate_contract_revision

from payment_terms import (
    BUYER,
    DISPUTE,
    IMPOSTOR,
    OTHER,
    PAYEE,
    SERVICE,
    agreement,
    agreement_bytes,
    config,
)


def _seller_data(terms):
    return PaymentSettlementData.for_agreement(terms, config()).to_wire()


def _approval(fake, **overrides):
    return PaymentApproval(config(**overrides), BUYER, client_for_owner=fake)


def test_approval_returns_the_transaction_and_never_runs_the_seller_deposit():
    fake = FakePaymentsClient(signer=SERVICE)
    terms = agreement(deposit=True)
    txid = _approval(fake).approve(agreement_bytes(terms), _seller_data(terms))
    assert txid == _seller_data(terms)["transaction_id"]
    assert fake.owners == [BUYER]
    assert fake.count("ensure_agreement_attached") == 0
    assert fake.count("attach_agreement") == 0


@pytest.mark.parametrize("attach", [False, True])
@pytest.mark.parametrize("deposit", [False, True])
def test_attachment_follows_only_the_buyer_policy(attach, deposit):
    fake = FakePaymentsClient(signer=SERVICE)
    terms = agreement(deposit=deposit)
    _approval(fake, attach_agreement=attach).approve(agreement_bytes(terms), _seller_data(terms))
    assert fake.calls[0] == ("approve", attach)


def test_a_seller_transaction_id_for_another_mandate_is_refused():
    terms = agreement()
    data = _seller_data(terms)
    data["transaction_id"] = "0" * 64
    with pytest.raises(MandatePolicyError):
        _approval(FakePaymentsClient(signer=SERVICE)).check(agreement_bytes(terms), data)


@pytest.mark.parametrize("change", ["fee", "stop", "hold", "extend", "cap", "reverse"])
def test_a_mandate_the_buyer_policy_does_not_derive_is_refused(change):
    terms = agreement()
    mandate = _seller_data(terms)["mandate"]
    part = mandate["parts"][0]
    if change == "fee":
        mandate["fee"] = {"bps": 0}
    elif change == "stop":
        part["authorities"]["stop"] = [
            {"account": mandate["to"], "notice": "PT0S", "partialPeriod": "charged"}
        ]
    elif change == "hold":
        part["hold"] = {"afterStop": "PT0S"}
    elif change == "cap":
        part["maxHoldExtension"] = "PT0S"
    else:
        part["authorities"][change] = [OTHER]
    data = {"mandate": mandate, "transaction_id": transaction_id(mandate)}
    with pytest.raises(MandatePolicyError):
        _approval(FakePaymentsClient(signer=SERVICE)).check(agreement_bytes(terms), data)


def test_another_payer_is_refused():
    terms = agreement(payer=OTHER)
    with pytest.raises(MandatePolicyError):
        _approval(FakePaymentsClient()).check(agreement_bytes(terms), _seller_data(terms))


def test_a_declined_confirmation_approves_nothing():
    fake = FakePaymentsClient(signer=SERVICE)
    terms = agreement()
    with pytest.raises(PaymentApprovalDeclined):
        _approval(fake).approve(
            agreement_bytes(terms), _seller_data(terms), confirm=lambda *_: False
        )
    assert fake.count("approve") == 0


@pytest.mark.parametrize(
    "configured,signed,verifies",
    [(True, True, True), (True, False, False), (None, True, False)],
    ids=["live-accepts-live", "live-refuses-test", "default-refuses-live"],
)
def test_an_approval_receipt_verifies_only_in_the_configured_mode(configured, signed, verifies):
    fake = FakePaymentsClient(signer=SERVICE, livemode=signed)
    terms = agreement()
    approval = _approval(fake) if configured is None else _approval(fake, livemode=configured)
    if verifies:
        txid = approval.approve(agreement_bytes(terms), _seller_data(terms))
        assert txid == _seller_data(terms)["transaction_id"]
    else:
        with pytest.raises(ReceiptVerificationError):
            approval.approve(agreement_bytes(terms), _seller_data(terms))


def test_a_polled_receipt_is_verified_apart_from_the_approval_receipt():
    class PolledInTestMode(FakePaymentsClient):
        """Approves with a live receipt, then serves a test-mode one when polled."""

        def approve(self, mandate, **kwargs):
            self.approved_mandate = mandate
            return super().approve(mandate, **kwargs)

        def poll(self, transaction, **kwargs):
            self.serve(
                build_signed_receipt(
                    signer=SERVICE, mandate=self.approved_mandate, livemode=False
                )
            )
            return super().poll(transaction, **kwargs)

    fake = PolledInTestMode(signer=SERVICE, livemode=True)
    terms = agreement()
    with pytest.raises(ReceiptVerificationError, match="transaction receipt"):
        _approval(fake, livemode=True).approve(agreement_bytes(terms), _seller_data(terms))
    assert fake.count("approve") == 1


def test_an_approval_receipt_from_another_key_is_refused():
    fake = FakePaymentsClient(signer=IMPOSTOR)
    terms = agreement()
    with pytest.raises(ReceiptVerificationError):
        _approval(fake).approve(agreement_bytes(terms), _seller_data(terms))

# --- the buyer's terms policy at approval ------------------------------------


def _recurring(*, delivery_deadline_seconds):
    """A recurring Agreement and the seller's data for it, derived as a storefront does."""
    mechanism = "arkhai.payments.v1"
    authority = DisputeEntry.model_validate({
        **dispute_lifecycle(DISPUTE)["adjudication"]["dispute"],
        "advertisement": {"mechanisms": [mechanism], "minimum_dispute_window_seconds": 0,
                          "minimum_case_hold_seconds": None},
    })
    servicing = RateServicing(
        required_contracts={mechanism: rate_contract_revision()},
        declarations={mechanism: RateServicingDeclaration(mechanism, rate_contract_revision(), "published")},
    )
    clause = SettlementPublicationClause.model_validate({
        "mechanism": mechanism, "asset": "USD/2", "rate": "60", "per": "hour",
        "mechanism_input": {"asset": "USD/2", "payee_account": PAYEE,
                            "approval_window": "PT10S", "dispute_window_seconds": 3600},
        "recurring": {"period": "PT60S", "reserve_ahead_seconds": 120},
    })
    now = datetime.fromtimestamp(1_800_000_000, timezone.utc)
    derived = derive_rate_preset(
        clause, helper=PaymentsRatePresetHelper(), servicing=servicing, authorities=(authority,),
        max_duration_seconds=3600, available_until_utc=None,
        delivery_deadline_seconds=delivery_deadline_seconds, now=now, default_penalty_periods=24,
    )
    assert isinstance(derived, SettlementOption), derived
    stamp = now.isoformat().replace("+00:00", "Z")
    terms = Agreement.model_validate({
        "negotiation_id": "rate", "listing_id": "listing-1", "listing_hash": "a" * 64,
        "buyer": {"scheme": "ed25519", "identifier": "buyer-key"},
        "seller": {"scheme": "ed25519", "identifier": "seller-key"},
        "settlement": derived, "settlement_params": {"payer_account": BUYER},
        "amount": 100, "asset": "USD/2", "duration_seconds": 3600,
        "accepted_at": stamp, "start_utc": stamp,
        "provision_terms": {"kind": "test.v1", "version": 1, "payload": {}},
    }).model_dump(mode="json", exclude_none=True)
    data = PaymentSettlementData.for_agreement(terms, config(), rate_servicing=servicing).to_wire()
    return terms, data


def test_approval_asks_the_buyer_terms_policy_about_the_accepted_option():
    terms, data = _recurring(delivery_deadline_seconds=None)
    fake = FakePaymentsClient(signer=SERVICE)
    with pytest.raises(MandatePolicyError, match="a default buyer refuses this option: no delivery deadline"):
        _approval(fake).check(agreement_bytes(terms), data)
    permissive = PaymentApproval(
        config(), BUYER, client_for_owner=fake, terms_policy=PermissiveBuyerTermsPolicy(),
    )
    permissive.check(agreement_bytes(terms), data)

    class Declining:
        def refusals(self, offer):
            assert offer.has_adapter and offer.lifecycle is not None
            return ("not on these terms",)

    with pytest.raises(MandatePolicyError, match="not on these terms"):
        PaymentApproval(config(), BUYER, client_for_owner=fake, terms_policy=Declining()).check(
            agreement_bytes(terms), data,
        )


def test_a_permissive_terms_policy_does_not_waive_the_mandate_check():
    terms, data = _recurring(delivery_deadline_seconds=30)
    data["mandate"]["fee"] = {"bps": 0}
    with pytest.raises(MandatePolicyError):
        PaymentApproval(
            config(), BUYER, client_for_owner=FakePaymentsClient(signer=SERVICE),
            terms_policy=PermissiveBuyerTermsPolicy(),
        ).check(agreement_bytes(terms), data)
