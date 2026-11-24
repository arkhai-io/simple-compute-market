"""The payment rows' shared assertions hold on what the payments double emits.

Each output is the signed transaction snapshot of the payments kit's
``PaymentsAuthority`` engine, the engine the lanes' payments double serves,
driven through each row's input on the lane's own terms (``payments_engine``):
the payer stopping at once with its started period charged, a spot seller on two
minutes' notice with its period returned, funds running out, and the term ending
with its partial final period returned. Each assertion passes on its row's
output, fails naming the field and both values when an exact or a related field
is altered, and ignores identifiers, signatures, ``observedAt`` and the latest
event sequence.
"""

from __future__ import annotations

import copy
from typing import Any, Callable

import pytest

from tests.e2e.roles.helpers.producer_assertions import (
    ABSENT,
    assert_funds_exhausted,
    assert_payee_stop,
    assert_payee_stop_pending,
    assert_payer_stop,
    assert_term_end,
    field,
)
from tests.unit.payments_engine import (
    PAYEE,
    PAYER,
    PERIOD_SECONDS,
    PRICE,
    T0,
    TERM_END,
    Engine,
)

SPOT_NOTICE_SECONDS = 120


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


def test_a_payer_stop_in_the_parts_start_second_fails_rather_than_passing_on_nothing():
    """A payer's stop taking effect in the second the part started has no
    started period to charge — the engine settles nothing for it — so the
    buyer's-stop observation fails naming the start and the stop, rather than
    passing on zero periods settled."""
    engine = Engine(funds=10 * PRICE)
    transaction = engine.approve_and_start(payee_notice_seconds=None)
    engine.stop(transaction, PAYER)
    output = engine.snapshot(transaction)
    started = int(field(output, "parts.0.started"))
    assert int(field(output, "parts.0.stop.effectiveAt")) == started == T0
    assert field(output, "parts.0.stop.settled.gross") == "0"
    with pytest.raises(AssertionError) as failure:
        _payer_stop(output)
    message = str(failure.value)
    assert (f"parts.0.stop.effectiveAt later than parts.0.started: expected True (a started "
            f"period for the stop to charge: started {T0!r}, stop effective {T0!r}), "
            f"got False") in message, message


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
