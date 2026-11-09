"""Programmed rulings: recorded, applied at payments, resumed, and their extensions lifted.

A rule installed through the typed control client rules the case a matching
filing reaches; the kit's real ``MediationClient`` files and reads the record,
and the payments kit's engine shows each effect and lift (``support``).
"""

from __future__ import annotations

from typing import Any

import pytest

from lane_double_controls import ControlError, Rule, Ruling
from market_arkhai_mediation.contract import wire
from market_arkhai_mediation.models import ReadAfter
from market_arkhai_payments.canonical import agreement_hash
from market_arkhai_payments.errors import PaymentsAPIError, PaymentsTransportError

from support import AGREEMENT, Failing, Lane, filing, run

RULE = {"rule_id": "payee-end", "match": {"operation": "file", "filer": "payee",
                                          "kind": "delivery_end"}}


def _ruling(*effects: dict[str, Any], delivery_end: bool = True, close: bool = True) -> dict:
    return {"basis": "payee_filed", "delivery_end": delivery_end, "close": close,
            "effects": list(effects)}


def _file(lane: Lane, transaction: str) -> dict:
    async def file() -> dict:
        async with lane.client("seller") as client:
            return wire(await client.file(filing(transaction), idempotency_key="filing-1"))
    return run(file())


def _record(lane: Lane, transaction: str) -> list[dict]:
    async def read() -> list[dict]:
        async with lane.client("buyer") as client:
            page = await client.read_record(ReadAfter.model_validate(
                {"agreement": agreement_hash(AGREEMENT), "after": 0}), transaction=transaction)
            return [entry["entry"] for entry in wire(page)["entries"]]
    return run(read())


def test_a_programmed_ruling_is_recorded_applied_and_its_extensions_lifted() -> None:
    lane = Lane()
    transaction = lane.approve(parts=2)
    lane.controls().install_rule(Rule.model_validate(RULE | {"ruling": _ruling(
        {"kind": "reverse", "part": 0, "amount": "400"})}))

    answer = _file(lane, transaction)

    assert answer["case"]["state"] == "closed"
    entries = _record(lane, transaction)
    assert [entry["kind"] for entry in entries] == ["filed", "ruled", "closed"]
    ruled, closed = entries[1], entries[2]
    assert ruled["basis"] == "payee_filed"
    assert [(item["effect"]["kind"], item["state"]) for item in ruled["outcome"]] == [
        ("end_delivery", "applied"), ("reverse", "prepared")]
    assert [item["state"] for item in closed["outcome"]] == ["applied", "applied"]
    assert closed["reason"] == "ruled"
    reverses = lane.events(transaction, "reverse")
    assert [(event["event"]["part"], event["event"]["amount"]) for event in reverses] == [
        (0, "400")]
    assert reverses[0]["event"]["payload"] == {"case_ref": answer["case"]["case_ref"],
                                               "effect_id": ruled["outcome"][1]["id"]}
    assert lane.part(transaction, 0)["reversed"] == "400"
    lifts = lane.events(transaction, "lift")
    assert sorted(event["event"]["part"] for event in lifts) == [0, 1]
    assert lane.part(transaction, 0)["extensions"] == []
    assert lane.part(transaction, 1)["extensions"] == []
    [view] = lane.controls().rules().rules
    assert (view.matched, view.waiting) == (1, 0)


def test_a_case_whose_ruling_is_not_yet_applied_is_not_closed() -> None:
    lane = Lane()
    transaction = lane.approve(amount="1000")
    controls = lane.controls()
    # More than the part holds: payments refuses it however often it is resent.
    controls.install_rule(Rule.model_validate(RULE | {"ruling": _ruling(
        {"kind": "reverse", "part": 0, "amount": "5000"})}))
    case_ref = _file(lane, transaction)["case"]["case_ref"]
    extensions = lane.part(transaction)["extensions"]
    assert extensions

    with pytest.raises(ControlError) as refused:
        controls.close_case(case_ref)

    assert (refused.value.status, refused.value.code) == (409, "case_applying")
    assert controls.cases(transaction).cases[0].state == "applying"
    assert controls.rules().rules[0].waiting == 1
    last = _record(lane, transaction)[-1]
    assert last["kind"] == "ruled"
    assert [item["state"] for item in last["outcome"]] == ["applied", "prepared"]
    assert lane.part(transaction)["extensions"] == extensions
    assert lane.events(transaction, "lift") == []


def test_a_ruling_held_at_its_gate_applies_only_once_resumed() -> None:
    lane = Lane()
    transaction = lane.approve()
    controls = lane.controls()
    controls.install_rule(Rule.model_validate(RULE | {"pause_before_effects": True, "ruling":
        _ruling({"kind": "reverse", "part": 0, "amount": "100"})}))

    answer = _file(lane, transaction)

    assert answer["case"]["state"] == "applying"
    assert lane.events(transaction, "reverse") == []
    assert controls.rules().rules[0].waiting == 1
    # The gate holds the delivery end too: it is recorded prepared.
    ruled = _record(lane, transaction)[1]
    assert [(item["effect"]["kind"], item["state"]) for item in ruled["outcome"]] == [
        ("end_delivery", "prepared"), ("reverse", "prepared")]
    resumed = controls.resume_rule("payee-end")
    assert resumed.waiting == 0
    assert [event["event"]["amount"] for event in lane.events(transaction, "reverse")] == ["100"]
    assert controls.cases(transaction).cases[0].state == "closed"


@pytest.mark.parametrize(("error", "after_commit"), [
    (PaymentsAPIError(503, "ledger_unavailable"), False),
    (PaymentsTransportError("payments service request failed"), False),
    (PaymentsTransportError("payments service request failed"), True),
], ids=["refused", "unreachable", "lost after commit"])
def test_a_payments_failure_between_effects_is_resumed_without_a_duplicate(
    error: Exception, after_commit: bool,
) -> None:
    # The ruling's second effect fails once: refused or unreachable before
    # payments takes it, or taken by payments and its answer lost.
    lane = Lane(lambda peer: Failing(
        peer, lambda call, key: error if key.endswith(":1:effect:2") else None,
        after_commit=after_commit))
    transaction = lane.approve()
    controls = lane.controls()
    controls.install_rule(Rule.model_validate(RULE | {"ruling": _ruling(
        {"kind": "reverse", "part": 0, "amount": "100"},
        {"kind": "reverse", "part": 0, "amount": "200"})}))

    answer = _file(lane, transaction)

    assert answer["case"]["state"] == "applying"
    taken = ["100", "200"] if after_commit else ["100"]
    assert [event["event"]["amount"] for event in lane.events(transaction, "reverse")] == taken
    assert controls.rules().rules[0].waiting == 1
    controls.resume_rule("payee-end")
    assert [event["event"]["amount"] for event in lane.events(transaction, "reverse")] == [
        "100", "200"]
    assert lane.part(transaction)["reversed"] == "300"
    assert controls.cases(transaction).cases[0].state == "closed"
    assert [entry["kind"] for entry in _record(lane, transaction)] == ["filed", "ruled", "closed"]


def test_a_ruling_that_does_not_close_attests_its_effects_and_leaves_the_case_open() -> None:
    lane = Lane()
    transaction = lane.approve()
    lane.controls().install_rule(Rule.model_validate(RULE | {"ruling": _ruling(
        {"kind": "reverse", "part": 0, "amount": "100"}, delivery_end=False, close=False)}))

    answer = _file(lane, transaction)

    assert answer["case"]["state"] == "open"
    entries = _record(lane, transaction)
    assert [entry["kind"] for entry in entries] == ["filed", "ruled", "ruled"]
    assert [item["state"] for item in entries[2]["outcome"]] == ["applied"]
    assert lane.events(transaction, "lift") == []
    assert lane.part(transaction)["extensions"]


def test_a_second_ruling_on_an_open_case_applies_its_own_effects() -> None:
    lane = Lane()
    transaction = lane.approve()
    controls = lane.controls()
    controls.install_rule(Rule.model_validate(RULE | {"ruling": _ruling(
        {"kind": "reverse", "part": 0, "amount": "100"}, delivery_end=False, close=False)}))
    case_ref = _file(lane, transaction)["case"]["case_ref"]

    controls.decide(case_ref, Ruling.model_validate(_ruling(
        {"kind": "reverse", "part": 0, "amount": "100"}, delivery_end=False, close=True)))

    reverses = lane.events(transaction, "reverse")
    assert [event["event"]["amount"] for event in reverses] == ["100", "100"]
    assert [event["event"]["payload"]["effect_id"] for event in reverses] == [
        f"{case_ref}:1:1", f"{case_ref}:2:1"]
    assert lane.part(transaction)["reversed"] == "200"
    assert controls.cases(transaction).cases[0].state == "closed"
