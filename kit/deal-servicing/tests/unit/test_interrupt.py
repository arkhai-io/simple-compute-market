"""The seller half's classification of an administrator interruption.

The identities are deterministic development fixtures; never use them on a
public network.
"""

import pytest
from market_deal_lifecycle.adapters import PaymentSelector
from market_deal_servicing import InterruptRefused, SellerDeal, interrupt_command, interrupt_operation_key
from market_identity import Ed25519Signer

ADMIN, BUYER = (Ed25519Signer(bytes([n]) * 32).identity for n in (1, 2))
PAYER = {"notice_seconds": 0, "settles_through": "started_period"}
PAYEE = {"notice_seconds": 600, "settles_through": "last_boundary"}


def deal(*, once_only, payee):
    return SellerDeal(
        negotiation_id="negotiation-1", commitment_ref="txn-1", domain="fixture",
        buyer=BUYER,
        payment=PaymentSelector("arkhai.payments.v1"), once_only=once_only,
        entitlements={"payer": PAYER} | ({"payee": PAYEE} if payee else {}),
    )


def classify(target, kind, reason="hardware failure"):
    return interrupt_command(target, operation_key="op", reason=reason, interruption_kind=kind)


@pytest.mark.parametrize("once_only", [True, False])
def test_failure_ends_delivery_and_files_whatever_the_entitlement(once_only):
    command = classify(deal(once_only=once_only, payee=False), "failure")
    assert (command.kind, command.negotiation_id, command.operation_key) == ("delivery_end", "negotiation-1", "op")
    assert command.at is None and command.payload == {}


def test_preemption_is_the_sellers_notice_under_the_payee_entitlement():
    assert classify(deal(once_only=False, payee=True), "preemption").kind == "notice"


def test_a_once_only_deal_with_no_kind_is_a_failure():
    assert classify(deal(once_only=True, payee=False), None).kind == "delivery_end"


@pytest.mark.parametrize("target,kind,reason,refusal", [
    (deal(once_only=False, payee=True), None, "hardware failure", "requires interruption_kind"),
    (deal(once_only=False, payee=False), "preemption", "reclaim", "no payee entitlement"),
    (deal(once_only=True, payee=False), "preemption", "reclaim", "no payee entitlement"),
    (deal(once_only=False, payee=True), "failure", " ", "requires a reason"),
    (deal(once_only=False, payee=True), "preemption", None, "requires a reason"),
    (deal(once_only=False, payee=True), "outage", "reclaim", "unknown interruption kind"),
])
def test_refusals_name_what_the_request_lacks(target, kind, reason, refusal):
    with pytest.raises(InterruptRefused, match=refusal):
        classify(target, kind, reason)


def test_a_derived_operation_key_is_the_requests_own():
    key = interrupt_operation_key("negotiation-1", actor=ADMIN, reason="reclaim", interruption_kind="preemption")
    assert key == interrupt_operation_key("negotiation-1", actor=ADMIN, reason="reclaim", interruption_kind="preemption")
    assert key != interrupt_operation_key("negotiation-1", actor=ADMIN, reason="other", interruption_kind="preemption")
    assert key != interrupt_operation_key("negotiation-1", actor=ADMIN, reason="reclaim", interruption_kind="failure")
