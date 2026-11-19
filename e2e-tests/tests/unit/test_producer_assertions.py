"""The payment rows' shared assertions hold on what the payments double emits.

Each output is the signed transaction snapshot of the payments kit's
``PaymentsAuthority`` engine, the engine the lanes' payments double serves,
driven through each row's input on the lane's own terms: a quarter-hour rate
part at one period's price, the payer free to stop at once with its started
period charged, a spot seller on two minutes' notice with its period returned,
and the term ending with its partial final period returned. Each assertion passes
on its row's output, fails naming the field and both values when an exact or a
related field is altered, and ignores identifiers, signatures, ``observedAt`` and
the latest event sequence. Every
account and key below is a development fixture, never used on any network.
"""

from __future__ import annotations

import copy
from typing import Any, Callable

import pytest
from market_arkhai_payments.fixtures import PaymentsAuthority
from market_identity import Ed25519Signer

from tests.e2e.roles.helpers.producer_assertions import (
    ABSENT,
    assert_funds_exhausted,
    assert_payee_stop,
    assert_payee_stop_pending,
    assert_payer_stop,
    assert_term_end,
    field,
)

# Development fixtures: two party accounts, the dispute authority's, and a
# receipt-signing seed.
PAYER = "11111111-1111-4111-8111-111111111111"
PAYEE = "22222222-2222-4222-8222-222222222222"
AUTHORITY = "33333333-3333-4333-8333-333333333333"
SIGNER = Ed25519Signer(bytes([9]) * 32)

T0 = 1_794_823_200
PERIOD_SECONDS = 900
PRICE = 250_000
#: Twelve whole periods and five minutes of a thirteenth, which the term end
#: returns.
TERM_END = T0 + 3 * 3600 + 300
SPOT_NOTICE_SECONDS = 120
ASSET = "USD/6"


class Engine:
    """The payments engine on a clock the test moves, and one rate deal on it."""

    def __init__(self, *, funds: int) -> None:
        self.now = T0
        self.authority = PaymentsAuthority(signer=SIGNER, clock=lambda: self.now)
        self.authority.fund(PAYER, ASSET, funds)

    def approve_and_start(self, *, payee_notice_seconds: int | None) -> str:
        stops = [{"account": PAYER, "notice": "PT0S", "partialPeriod": "charged"}]
        if payee_notice_seconds is not None:
            stops.append({"account": PAYEE, "notice": f"PT{payee_notice_seconds}S",
                          "partialPeriod": "returned"})
        stops.append({"account": AUTHORITY, "notice": "PT0S", "partialPeriod": "chosen"})
        mandate = {
            "from": PAYER, "to": PAYEE, "fee": {"bps": 250}, "nonce": "unit-rate",
            "deal": "ab" * 32, "expires": T0 + 300,
            "parts": [{
                "kind": "rate", "asset": ASSET, "amount": str(PRICE), "period": "PT15M",
                "reserveAhead": "PT15M", "hold": {"for": "P7D"},
                "end": {"at": TERM_END, "partialPeriod": "returned"},
                "authorities": {"stop": stops, "reverse": [PAYEE, AUTHORITY],
                                "extend": [AUTHORITY], "start": [PAYEE]},
                "maxHoldExtension": None,
            }],
        }
        transaction = self.authority.approve(mandate, account=PAYER).receipt.transaction.root
        self.authority.submit(transaction, {"account": PAYEE, "requestId": "start",
                                         "event": {"kind": "start"}})
        return transaction

    def stop(self, transaction: str, account: str) -> None:
        self.authority.submit(transaction, {"account": account, "requestId": f"stop-{account}",
                                         "event": {"kind": "stop"}})

    def snapshot(self, transaction: str) -> dict[str, Any]:
        signed = self.authority.snapshot(transaction)
        return signed.snapshot.model_dump(mode="json", by_alias=True, exclude_none=True)


def payer_stop_output() -> dict[str, Any]:
    engine = Engine(funds=10 * PRICE)
    transaction = engine.approve_and_start(payee_notice_seconds=None)
    engine.now = T0 + 60
    engine.stop(transaction, PAYER)
    return engine.snapshot(transaction)


def funds_exhausted_output() -> tuple[dict[str, Any], int]:
    """The output once funds run out, and the funded boundary read before."""
    engine = Engine(funds=3 * PRICE)
    transaction = engine.approve_and_start(payee_notice_seconds=None)
    engine.authority.reserve(transaction, TERM_END)
    boundary = int(engine.snapshot(transaction)["fundedThrough"])
    engine.now = boundary
    return engine.snapshot(transaction), boundary


def preemption_outputs() -> tuple[dict[str, Any], dict[str, Any]]:
    """The output with the seller's notice pending, then once it takes effect."""
    engine = Engine(funds=10 * PRICE)
    transaction = engine.approve_and_start(payee_notice_seconds=SPOT_NOTICE_SECONDS)
    engine.stop(transaction, PAYEE)
    pending = engine.snapshot(transaction)
    engine.now = T0 + SPOT_NOTICE_SECONDS
    return pending, engine.snapshot(transaction)


def term_end_output() -> dict[str, Any]:
    engine = Engine(funds=20 * PRICE)
    transaction = engine.approve_and_start(payee_notice_seconds=None)
    engine.authority.reserve(transaction, TERM_END)
    engine.now = TERM_END
    return engine.snapshot(transaction)


def _payer_stop(output: dict[str, Any]) -> None:
    assert_payer_stop(output, payer=PAYER, period_price=PRICE, period_seconds=PERIOD_SECONDS)


def _funds_exhausted(output: dict[str, Any], boundary: int) -> None:
    assert_funds_exhausted(output, funded_boundary=boundary, funded_periods=3, period_price=PRICE)


def _pending(output: dict[str, Any]) -> None:
    assert_payee_stop_pending(output, payee=PAYEE, payee_notice_seconds=SPOT_NOTICE_SECONDS)


def _payee_stop(output: dict[str, Any]) -> None:
    assert_payee_stop(output, payee=PAYEE, payee_notice_seconds=SPOT_NOTICE_SECONDS,
                      period_price=PRICE, period_seconds=PERIOD_SECONDS)


def _term_end(output: dict[str, Any]) -> None:
    assert_term_end(output, agreement_end=TERM_END, period_price=PRICE,
                    period_seconds=PERIOD_SECONDS)


def _cases() -> list[tuple[str, dict[str, Any], Callable[[dict[str, Any]], None]]]:
    exhausted, boundary = funds_exhausted_output()
    pending, preempted = preemption_outputs()
    return [
        ("buyer's stop", payer_stop_output(), _payer_stop),
        ("funds running out", exhausted, lambda output: _funds_exhausted(output, boundary)),
        ("seller's notice pending", pending, _pending),
        ("seller's stop", preempted, _payee_stop),
        ("term end", term_end_output(), _term_end),
    ]


CASES = _cases()
IDS = [name for name, _, _ in CASES]


def _set(output: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    altered = copy.deepcopy(output)
    keys = path.split(".")
    target: Any = altered
    for key in keys[:-1]:
        target = target[int(key)] if key.isdigit() else target[key]
    target[keys[-1]] = value
    return altered


@pytest.mark.parametrize(("name", "output", "check"), CASES, ids=IDS)
def test_each_assertion_holds_on_the_engines_output(name, output, check):
    check(output)


def test_the_outputs_are_what_each_row_produces():
    """The rows' inputs reached the engine as each assertion expects: a charged
    stop of the started period, a funding stop after three periods, a pending
    then final seller stop returning its period, and the term end."""
    (_, payer, _), (_, exhausted, _), (_, pending, _), (_, preempted, _), (_, ended, _) = CASES
    assert field(payer, "parts.0.stop.settled.gross") == str(PRICE)
    assert field(exhausted, "parts.0.stop.settled.gross") == str(3 * PRICE)
    assert field(pending, "parts.0.stop") is ABSENT
    assert field(preempted, "parts.0.stop.settled.gross") == "0"
    assert field(ended, "parts.0.stop.effectiveAt") == TERM_END
    assert field(ended, "parts.0.stop.settled.gross") == str(12 * PRICE)


#: An exact field of each output, and a value it does not have.
EXACT = {
    "buyer's stop": ("parts.0.stop.partialPeriod", "returned"),
    "funds running out": ("parts.0.stop.cause", "payer"),
    "seller's notice pending": ("parts.0.pendingStop.cause", "authority"),
    "seller's stop": ("parts.0.stop.partialPeriod", "charged"),
    "term end": ("parts.0.stop.partialPeriod", "prorated"),
}


@pytest.mark.parametrize(("name", "output", "check"), CASES, ids=IDS)
def test_an_altered_exact_field_fails_naming_it_and_both_values(name, output, check):
    path, wrong = EXACT[name]
    expected = field(output, path)
    with pytest.raises(AssertionError) as failure:
        check(_set(output, path, wrong))
    message = str(failure.value)
    assert path in message, message
    assert repr(wrong) in message and repr(expected) in message, message


def test_an_amount_left_reserved_fails_naming_both_amounts():
    output = CASES[4][1]
    with pytest.raises(AssertionError) as failure:
        _term_end(_set(output, "parts.0.reserved", "250000"))
    assert "parts.0.reserved: expected 0, got 250000" in str(failure.value)


#: A field compared by relation in each output, shifted off its relation.
RELATED = {
    "buyer's stop": "parts.0.stop.effectiveAt",
    "funds running out": "parts.0.stop.effectiveAt",
    "seller's notice pending": "parts.0.pendingStop.at",
    "seller's stop": "parts.0.stop.effectiveAt",
    "term end": "parts.0.stop.effectiveAt",
}


@pytest.mark.parametrize(("name", "output", "check"), CASES, ids=IDS)
def test_an_instant_off_its_relation_fails_naming_it_and_both_values(name, output, check):
    path = RELATED[name]
    shifted = int(field(output, path)) + 1
    with pytest.raises(AssertionError) as failure:
        check(_set(output, path, shifted))
    message = str(failure.value)
    assert path in message and repr(shifted) in message and repr(shifted - 1) in message, message


def test_an_altered_refund_fails_naming_the_relation_and_both_values():
    output = CASES[0][1]
    refunded = int(field(output, "parts.0.refunded"))
    with pytest.raises(AssertionError) as failure:
        _payer_stop(_set(output, "parts.0.refunded", "1"))
    message = str(failure.value)
    assert (f"parts.0.refunded: expected {refunded!r} (parts.0.gross less the settled and "
            f"reversed amounts), got 1") in message, message


def test_a_term_end_charging_its_final_period_fails_naming_the_settlement():
    """The term end returns its partial final period: a settlement charging it
    as a whole period differs."""
    output = CASES[4][1]
    charged = str(13 * PRICE)
    with pytest.raises(AssertionError) as failure:
        _term_end(_set(output, "parts.0.stop.settled.gross", charged))
    assert f"parts.0.stop.settled.gross: expected {12 * PRICE!r}" in str(failure.value)


def test_every_differing_field_is_named():
    output = CASES[0][1]
    altered = _set(_set(output, "parts.0.stop.cause", "payee"),
                   "parts.0.stop.partialPeriod", "returned")
    with pytest.raises(AssertionError) as failure:
        _payer_stop(altered)
    message = str(failure.value)
    assert "parts.0.stop.cause: expected 'payer', got 'payee'" in message, message
    assert "parts.0.stop.partialPeriod: expected 'charged', got 'returned'" in message, message


@pytest.mark.parametrize(("name", "output", "check"), CASES, ids=IDS)
def test_identifiers_signatures_and_observed_at_are_ignored(name, output, check):
    altered = copy.deepcopy(output)
    altered["transaction"] = "cd" * 32
    altered["observedAt"] = int(altered["observedAt"]) + 86_400
    altered["latestEventSequence"] = 99
    altered["receipt"]["proof"]["value"] = "A" * 86
    altered["receipt"]["receipt"]["ledger"] = "another-ledger"
    for entry in altered["events"]:
        entry["requestId"] = f"renamed-{entry['requestId']}"
    check(altered)


def test_a_missing_stop_is_reported_absent():
    pending = CASES[2][1]
    with pytest.raises(AssertionError) as failure:
        _payee_stop(pending)
    assert "parts.0.stop.cause: expected 'payee', got <absent>" in str(failure.value)
