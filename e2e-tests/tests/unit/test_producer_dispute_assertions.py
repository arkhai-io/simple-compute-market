"""The rate-dispute rows' shared assertions hold on outputs shaped as the doubles emit them.

Each output is two producers'. The payments snapshot is the payments kit's
``PaymentsAuthority`` engine's (``payments_engine``), the engine the lanes'
payments double serves, driven through the payment events this test writes as
the mediation double sends them for the row's ruling, its payloads included — its
extend on filing, the stop, the reverse, a penalty's reversal of what the part
still holds, the lift. The dispute authority's record of the case is entries this
test writes in the shape the mediation double writes them, each validated by the
mediation kit's contract model; the doubles' own outputs are asserted by the
lane's rows. The seller's filing is ruled with a penalty above and below what the
part holds; the buyer's contested case with an operator's stop and reverse. Each
assertion passes on its row's output, fails naming the field and both values when
an exact or a related field is altered — the filed claim and the ruled end
included, even where the ruling's own times move together — and ignores record
references, payment payloads, signatures and ``observedAt``. Every account and key is a development
fixture, never used on any network.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from market_arkhai_mediation.models import RecordEntry

from tests.e2e.roles.helpers.producer_assertions import (
    assert_contested_case_ruled,
    assert_payee_filing_ruled,
)
from tests.unit.payments_engine import (
    AUTHORITY,
    PAYEE,
    PAYER,
    PERIOD_SECONDS,
    PRICE,
    T0,
    TERM_END,
    Engine,
)

CASE = "case-unit-1"
#: The Agreement's digest the record names; a development fixture.
AGREEMENT = "cd" * 32
#: The mediation double's record-signing identity; a development fixture.
ISSUER = {"scheme": "ed25519", "identifier": "A" * 42 + "A"}
#: A minute into the second period: the case's delivery end.
DELIVERY_END = T0 + PERIOD_SECONDS + 60
#: The seller's ruling applies a period later, past the second period's end.
RULED_AT = DELIVERY_END + PERIOD_SECONDS
#: The Agreement's premature-stop penalty: above what the part holds, then below.
PENALTIES = (24 * PRICE, PRICE // 2)

Output = tuple[list[dict[str, Any]], dict[str, Any]]


def _entry(transaction: str, kind: str, sequence: int, actor: str, at: int,
           extension: int, **fields: Any) -> dict[str, Any]:
    """One record entry as the mediation double writes it, held to the contract."""
    entry = {"agreement": AGREEMENT, "transaction": transaction, "case_ref": CASE,
             "sequence": sequence, "record_ref": f"record-{sequence}", "actor": actor, "at": at,
             "parts": [{"part": 0, "status": "held", "extension_ref": extension}],
             "issuer": ISSUER, "kind": kind, **fields}
    RecordEntry.model_validate(entry)
    return entry


def _filed(transaction: str, filer: str, cause: str, extension: int) -> dict[str, Any]:
    return _entry(transaction, "filed", 1, filer, DELIVERY_END, extension, filing={
        "transaction": transaction, "agreement": {"agreement": "fixture"},
        "request": {"kind": "delivery_end", "ended_at": DELIVERY_END, "delivered": True,
                    "cause": cause},
        "claim": "delivery ended", "items": [],
    })


def _effect_id(number: int | str) -> str:
    """An effect's id as the double numbers a case's first ruling's effects."""
    return f"{CASE}:1:{number}"


def _outcome(effects: list[dict[str, Any]], states: list[str]) -> list[dict[str, Any]]:
    """The ruling's outcome: its delivery end, then its payment effects numbered
    from one."""
    ids = [_effect_id("end"), *(_effect_id(number) for number in range(1, len(effects)))]
    return [{"id": effect_id, "effect": effect, "state": state}
            for effect_id, effect, state in zip(ids, effects, states)]


def _send(engine: Engine, transaction: str, number: int | str, event: dict[str, Any]) -> dict:
    """One payment event from the authority's account for an effect, keyed and
    carrying the payload the double sends."""
    return engine.submit(transaction, AUTHORITY, f"mediation:{CASE}:1:effect:{number}",
                         {**event, "payload": {"case_ref": CASE, "effect_id": _effect_id(number)}})


def _extend(engine: Engine, transaction: str) -> int:
    stored = engine.submit(transaction, AUTHORITY, f"mediation:{CASE}:extend:0",
                           {"kind": "extend", "part": 0, "payload": {"case_ref": CASE}})
    return int(stored["sequence"])


def _lift(engine: Engine, transaction: str, extension: int) -> None:
    engine.submit(transaction, AUTHORITY, f"mediation:{CASE}:lift:0",
                  {"kind": "lift", "part": 0, "ref": extension, "payload": {"case_ref": CASE}})


def seller_filing_output(penalty: int) -> Output:
    """The seller's filing at the delivery end, its gated mechanical ruling
    applied a period later: the stop, whose time has passed, a stop now; the
    reverse of the period earned after the end; the penalty's reversal of what
    the part still holds; the lift."""
    engine = Engine(funds=40 * PRICE)
    transaction = engine.approve_and_start(payee_notice_seconds=None)
    engine.authority.reserve(transaction, TERM_END)
    engine.now = DELIVERY_END
    extension = _extend(engine, transaction)
    engine.now = RULED_AT
    _send(engine, transaction, 1, {"kind": "stop", "part": 0, "partialPeriod": "returned"})
    _send(engine, transaction, 2, {"kind": "reverse", "part": 0, "amount": str(PRICE)})
    held = int(engine.snapshot(transaction)["parts"][0]["held"])
    _send(engine, transaction, "3:part:0",
          {"kind": "reverse", "part": 0, "amount": str(min(penalty, held))})
    _lift(engine, transaction, extension)
    effects = [{"kind": "end_delivery", "at": DELIVERY_END},
               {"kind": "stop", "part": 0, "at": DELIVERY_END, "partialPeriod": "returned"},
               {"kind": "reverse", "part": 0, "amount": str(PRICE)},
               {"kind": "penalty", "amount": str(penalty)}]
    record = [
        _filed(transaction, PAYEE, "payee", extension),
        _entry(transaction, "ruled", 2, AUTHORITY, DELIVERY_END, extension, basis="payee_filed",
               outcome=_outcome(effects, ["prepared"] * 4)),
        _entry(transaction, "closed", 3, AUTHORITY, RULED_AT, extension, reason="ruled",
               basis="payee_filed", outcome=_outcome(effects, ["applied"] * 4)),
    ]
    return record, engine.snapshot(transaction)


def contested_case_output() -> Output:
    """The buyer's filing, the seller's contest, and an operator's stop at the
    claimed end and reverse of the held first period, applied at once."""
    engine = Engine(funds=10 * PRICE)
    transaction = engine.approve_and_start(payee_notice_seconds=None)
    engine.now = DELIVERY_END
    extension = _extend(engine, transaction)
    _send(engine, transaction, 1, {"kind": "stop", "part": 0, "at": DELIVERY_END,
                                   "partialPeriod": "returned"})
    _send(engine, transaction, 2, {"kind": "reverse", "part": 0, "amount": str(PRICE)})
    _lift(engine, transaction, extension)
    effects = [{"kind": "end_delivery", "at": DELIVERY_END},
               {"kind": "stop", "part": 0, "at": DELIVERY_END, "partialPeriod": "returned"},
               {"kind": "reverse", "part": 0, "amount": str(PRICE)}]
    record = [
        _filed(transaction, PAYER, "payer", extension),
        _entry(transaction, "appended", 2, PAYEE, DELIVERY_END, extension, items=[]),
        _entry(transaction, "ruled", 3, AUTHORITY, DELIVERY_END, extension, basis="operator",
               outcome=_outcome(effects, ["applied", "prepared", "prepared"])),
        _entry(transaction, "closed", 4, AUTHORITY, DELIVERY_END, extension, reason="ruled",
               basis="operator", outcome=_outcome(effects, ["applied"] * 3)),
    ]
    return record, engine.snapshot(transaction)


def _seller(output: Output, penalty: int = PENALTIES[0]) -> None:
    record, snapshot = output
    assert_payee_filing_ruled(record, snapshot, case_ref=CASE, payee=PAYEE,
                              claimed_end=DELIVERY_END, authority=AUTHORITY, penalty=penalty,
                              period_price=PRICE, period_seconds=PERIOD_SECONDS)


def _contested(output: Output, reverse_amount: int | None = PRICE,
               ruled_end: int | None = DELIVERY_END) -> None:
    record, snapshot = output
    assert_contested_case_ruled(record, snapshot, case_ref=CASE, payer=PAYER, payee=PAYEE,
                                claimed_end=DELIVERY_END, authority=AUTHORITY,
                                ruled_end=ruled_end, reverse_amount=reverse_amount)


def _altered(data: Any, path: str, value: Any) -> Any:
    altered = copy.deepcopy(data)
    keys = path.split(".")
    target: Any = altered
    for key in keys[:-1]:
        target = target[int(key)] if key.isdigit() else target[key]
    target[keys[-1]] = value
    return altered


def _message(check, output) -> str:
    with pytest.raises(AssertionError) as failure:
        check(output)
    return str(failure.value)


@pytest.mark.parametrize("penalty", PENALTIES)
def test_the_seller_filing_assertion_holds_on_its_output(penalty):
    output = seller_filing_output(penalty)
    _seller(output, penalty)
    reversals = [int(item["event"]["amount"]) for item in output[1]["events"]
                 if item["event"]["kind"] == "reverse"]
    # The penalty above the holdings takes all the part held; the one below, itself.
    assert reversals == [PRICE, min(penalty, PRICE)], reversals


def test_the_contested_case_assertion_holds_on_its_output():
    _contested(contested_case_output())


def test_a_reverse_amount_a_policy_chose_is_not_compared():
    """Where the caller does not fix the reverse amount, any amount payments
    reversed exactly holds; where it does, another fails naming both."""
    output = contested_case_output()
    _contested(output, reverse_amount=None)
    message = _message(lambda value: _contested(value, reverse_amount=PRICE // 2), output)
    assert (f"case {CASE}: the reverse effect's amount: expected {PRICE // 2!r}, "
            f"got {PRICE!r}") in message, message


@pytest.mark.parametrize(("output", "check"), [
    (lambda: seller_filing_output(PENALTIES[0]), _seller),
    (contested_case_output, _contested),
], ids=["seller", "contested"])
def test_a_filed_claim_other_than_the_one_sent_fails_naming_it(output, check):
    """The filing's claim is the scenario's own input: another end, or another
    kind, differs from what was sent."""
    record, snapshot = output()
    message = _message(check, (_altered(record, "0.filing.request.ended_at", DELIVERY_END + 1),
                               snapshot))
    assert (f"case {CASE}: the filed claim's ended_at: expected {DELIVERY_END!r}, "
            f"got {DELIVERY_END + 1!r}") in message, message
    message = _message(check, (_altered(record, "0.filing.request.kind", "effects"), snapshot))
    assert (f"case {CASE}: the filed claim's kind: expected 'delivery_end', "
            f"got 'effects'") in message, message


def _ruled_times_moved(record: list[dict[str, Any]], seconds: int) -> list[dict[str, Any]]:
    """The record with the ruling's delivery end and stop time both moved by
    ``seconds``, in the ruled and the closed entry alike: a ruling consistent
    with itself, on an end other than the one claimed."""
    moved = copy.deepcopy(record)
    for entry in moved:
        for item in entry.get("outcome", []):
            effect = item["effect"]
            if effect["kind"] in ("end_delivery", "stop"):
                # A new mapping: the entries share their effects' mappings.
                item["effect"] = {**effect, "at": effect["at"] + seconds}
    return moved


@pytest.mark.parametrize(("output", "check"), [
    (lambda: seller_filing_output(PENALTIES[0]), _seller),
    (contested_case_output, _contested),
], ids=["seller", "contested"])
def test_a_ruling_moved_off_the_claimed_end_fails_naming_only_the_ruled_end(output, check):
    """Half a minute earlier, within the same period, every relation among the
    ruling's own times and the payments still holds; only the ruled end, held
    to the claimed one, differs."""
    record, snapshot = output()
    message = _message(check, (_ruled_times_moved(record, -30), snapshot))
    differences = [line for line in message.splitlines() if line.startswith("  ")]
    assert differences == [f"  case {CASE}: the ruling's delivery end: expected "
                           f"{DELIVERY_END!r}, got {DELIVERY_END - 30!r}"], message


def test_a_ruled_end_a_policy_chose_is_not_compared():
    """Where the caller does not fix the contested case's ruled end, a ruling
    on another end holds, its stop still related to it."""
    record, snapshot = contested_case_output()
    _contested((_ruled_times_moved(record, -30), snapshot), ruled_end=None)


def test_a_ruling_on_another_basis_fails_naming_it_and_both_values():
    record, snapshot = seller_filing_output(PENALTIES[0])
    message = _message(_seller, (_altered(record, "2.basis", "operator"), snapshot))
    assert f"case {CASE}: the closed entry's basis: expected 'payee_filed', got 'operator'" in message


def test_a_stop_by_another_cause_fails_naming_it():
    record, snapshot = contested_case_output()
    message = _message(_contested, (record, _altered(snapshot, "parts.0.stop.cause", "payee")))
    assert "parts.0.stop.cause: expected 'authority', got 'payee'" in message, message


def test_an_effect_left_prepared_fails_naming_the_states():
    record, snapshot = contested_case_output()
    message = _message(_contested, (_altered(record, "3.outcome.2.state", "prepared"), snapshot))
    assert (f"case {CASE}: the effects' states: expected ['applied', 'applied', 'applied'], "
            f"got ['applied', 'applied', 'prepared']") in message, message


def test_a_reverse_of_other_than_the_earnings_since_the_end_fails_naming_the_relation():
    record, snapshot = seller_filing_output(PENALTIES[0])
    message = _message(_seller, (_altered(record, "2.outcome.2.effect.amount", str(2 * PRICE)),
                                 snapshot))
    assert (f"case {CASE}: the reverse effect's amount: expected {PRICE!r} (1 periods earned "
            f"after the delivery end, at {PRICE}), got {2 * PRICE!r}") in message, message


def test_a_penalty_beyond_its_cap_fails_naming_the_relation():
    """A penalty taking more than the Agreement's penalty differs from the cap."""
    penalty = PENALTIES[1]
    record, snapshot = seller_filing_output(penalty)
    message = _message(lambda output: _seller(output, penalty // 2), (record, snapshot))
    assert (f"the authority's penalty reversals of part 0: expected {penalty // 2!r} (the "
            f"Agreement's penalty of {penalty // 2}, capped at what the part still held), "
            f"got {penalty!r}") in message, message


def test_a_stop_taking_effect_before_its_receipt_fails_naming_the_relation():
    record, snapshot = seller_filing_output(PENALTIES[0])
    message = _message(_seller, (record, _altered(snapshot, "parts.0.stop.effectiveAt",
                                                  DELIVERY_END)))
    assert (f"parts.0.stop.effectiveAt: expected {RULED_AT!r} (the stop effect's at, or the "
            f"authority's receipt of the stop once that passed), got {DELIVERY_END!r}") in message


def test_an_extension_left_open_fails_naming_the_lift():
    record, snapshot = contested_case_output()
    extension = record[0]["parts"][0]["extension_ref"]
    events = [item for item in snapshot["events"] if item["event"]["kind"] != "lift"]
    message = _message(_contested, (record, {**snapshot, "events": events}))
    assert (f"the authority's lift events on part 0: expected [{extension!r}] (the extension_ref "
            f"case {CASE}'s filing reports), got []") in message, message


def test_a_case_with_no_contest_fails_naming_the_answers():
    record, snapshot = contested_case_output()
    message = _message(_contested, ([entry for entry in record if entry["kind"] != "appended"],
                                    snapshot))
    assert f"case {CASE}: the answers before the ruling: expected [{PAYEE!r}], got []" in message


def _renamed(output: Output) -> Output:
    """The output with its record references renamed, its payloads replaced, a
    signature altered and its ``observedAt`` a day later."""
    record, snapshot = output
    record = [{**entry, "record_ref": f"renamed-{entry['record_ref']}"} for entry in record]
    snapshot = copy.deepcopy(snapshot)
    snapshot["observedAt"] = int(snapshot["observedAt"]) + 86_400
    snapshot["receipt"]["proof"]["value"] = "A" * 86
    for entry in snapshot["events"]:
        entry["event"]["payload"] = {"anything": "the authority's own"}
    return record, snapshot


def test_record_references_payloads_signatures_and_observed_at_are_ignored():
    _seller(_renamed(seller_filing_output(PENALTIES[0])))
    _contested(_renamed(contested_case_output()))
