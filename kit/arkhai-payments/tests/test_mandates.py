"""Mandate derivation and the buyer's exact-terms check."""

from __future__ import annotations

from datetime import datetime

import pytest

from market_arkhai_payments import (
    MandatePolicyError,
    agreement_hash,
    check,
    derive_mandate,
    mandate_policy_for_agreement,
)

from payment_terms import BUYER, DISPUTE, PAYEE, agreement, config


def _derived(value=None):
    terms = value or agreement()
    return terms, derive_mandate(terms, mandate_policy_for_agreement(terms, config()))


def _wire(mandate):
    return mandate.model_dump(mode="json", by_alias=True, exclude_none=True)


def test_hold_rounds_the_start_interval_up_and_keeps_the_agreement_unchanged():
    terms, mandate = _derived()
    before = dict(terms)
    # ceil(10.25 s to start) + 3600 s service + 7 days window
    assert _wire(mandate)["parts"] == [
        {"kind": "once", "asset": "USD/2", "amount": "10000", "hold": {"for": "P7DT1H11S"}}
    ]
    assert terms == before
    assert _wire(mandate)["deal"] == agreement_hash(terms)


def test_approval_expiry_rounds_acceptance_down():
    terms, mandate = _derived()
    accepted = datetime.fromisoformat(terms["accepted_at"].replace("Z", "+00:00")).timestamp()
    assert _wire(mandate)["expires"] == int(accepted) + 7 * 86_400


def test_authorities_nonce_and_fee_follow_policy():
    _, mandate = _derived()
    wire = _wire(mandate)
    assert wire["authorities"] == {
        "start": [BUYER, PAYEE],
        "stop": [BUYER, PAYEE],
        "reverse": [PAYEE, DISPUTE],
    }
    assert BUYER not in wire["authorities"]["reverse"]
    assert wire["nonce"] == "arkhai.payments.v1"
    assert wire["fee"] == {"bps": 250}


def test_start_before_acceptance_is_refused():
    terms = agreement(start_utc="2026-10-07T11:59:00Z")
    with pytest.raises(MandatePolicyError):
        derive_mandate(terms, mandate_policy_for_agreement(terms, config()))


def test_check_accepts_the_identical_mandate():
    terms, mandate = _derived()
    assert check(_wire(mandate), terms, mandate_policy_for_agreement(terms, config())) == mandate


@pytest.mark.parametrize(
    "field,value",
    [
        ("to", "44444444-4444-4444-8444-444444444444"),
        ("from", "44444444-4444-4444-8444-444444444444"),
        ("deal", "b" * 64),
        ("fee", {"bps": 0}),
        ("nonce", "other"),
        ("expires", 1),
        ("parts", [{"kind": "once", "asset": "USD/2", "amount": "99", "hold": {"for": "P1D"}}]),
        (
            "authorities",
            {
                "start": [BUYER, PAYEE],
                "stop": [BUYER, PAYEE],
                "reverse": [BUYER, PAYEE, DISPUTE],
            },
        ),
    ],
)
def test_check_rejects_every_tampered_field(field, value):
    terms, mandate = _derived()
    tampered = _wire(mandate) | {field: value}
    with pytest.raises(MandatePolicyError):
        check(tampered, terms, mandate_policy_for_agreement(terms, config()))
