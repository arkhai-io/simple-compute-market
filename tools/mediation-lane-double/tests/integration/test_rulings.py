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

from support import AGREEMENT, HOUR, RATE_PRICE, T0, Failing, Lane, Recording, filing, run

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


# Rulings on a running rate part: started at T0 and, half way through its second
# hour, holding its first hour's earnings (``support.Lane.approve_rate``).
RUNNING = T0 + HOUR + HOUR // 2


def _rate_lane(fail: Any = None, *, after_commit: bool = False) -> tuple[Lane, Recording, str]:
    """A lane over a recording payments peer, failing once each call ``fail`` picks."""

    recording: list[Recording] = []

    def wrap(peer: Any) -> Any:
        recording.append(Recording(peer))
        if fail is None:
            return recording[0]
        return Failing(recording[0], fail, after_commit=after_commit)

    lane = Lane(wrap)
    transaction = lane.approve_rate()
    lane.controls().set_time(RUNNING)
    assert lane.part(transaction)["held"] == RATE_PRICE
    return lane, recording[0], transaction


def _stop(at: int = RUNNING) -> dict[str, Any]:
    return {"kind": "stop", "part": 0, "at": at, "partialPeriod": "returned"}


def test_a_ruled_stop_stops_a_running_rate_part_as_the_authority_and_resends_the_same_event(
) -> None:
    # The stop's first answer is lost after payments took it.
    lane, sent, transaction = _rate_lane(
        lambda call, key: (PaymentsTransportError("payments service request failed")
                           if key.endswith(":1:effect:1") else None), after_commit=True)
    controls = lane.controls()
    controls.install_rule(Rule.model_validate(RULE | {"ruling": _ruling(_stop())}))

    case_ref = _file(lane, transaction)["case"]["case_ref"]
    assert controls.cases(transaction).cases[0].state == "applying"
    controls.resume_rule("payee-end")

    first, resent = sent.sent("stop")
    assert first == resent
    assert first[1] == {"kind": "stop", "part": 0, "at": RUNNING, "partialPeriod": "returned",
                        "payload": {"case_ref": case_ref, "effect_id": f"{case_ref}:1:1"}}
    [stop] = lane.events(transaction, "stop")
    assert stop["account"] == lane.authority.account
    part = lane.part(transaction)
    assert (part["stop"]["cause"], part["stop"]["partialPeriod"], part["stop"]["effectiveAt"]) == (
        "authority", "returned", RUNNING)
    # Returned: the started second hour is not charged, only the first is earned.
    assert part["rate"]["grossEarned"] == RATE_PRICE
    assert controls.cases(transaction).cases[0].state == "closed"


@pytest.mark.parametrize(("at", "requested"), [
    (RUNNING + HOUR, True), (T0, False),
], ids=["not yet reached", "already passed"])
def test_a_ruled_stop_time_is_requested_until_it_has_passed(at: int, requested: bool) -> None:
    lane, sent, transaction = _rate_lane()
    lane.controls().install_rule(Rule.model_validate(RULE | {"ruling": _ruling(_stop(at))}))

    _file(lane, transaction)

    [(_, event)] = sent.sent("stop")
    assert ("at" in event) is requested
    part = lane.part(transaction)
    if requested:
        assert (part["pendingStop"]["at"], part["pendingStop"]["cause"]) == (at, "authority")
        assert "stop" not in part
    else:
        # Payments never backdates a stop: one already passed stops the part now.
        assert (part["stop"]["effectiveAt"], part["stop"]["cause"]) == (RUNNING, "authority")


def test_an_operator_decision_stops_a_running_rate_part_as_the_authority() -> None:
    lane, sent, transaction = _rate_lane()
    case_ref = _file(lane, transaction)["case"]["case_ref"]

    decided = lane.controls().decide(case_ref, Ruling.model_validate(_ruling(_stop())))

    assert decided.state == "closed"
    [(_, event)] = sent.sent("stop")
    assert event["partialPeriod"] == "returned"
    part = lane.part(transaction)
    assert (part["stop"]["cause"], part["stop"]["partialPeriod"]) == ("authority", "returned")


def test_a_refused_stop_whose_time_passes_before_it_is_resumed_is_a_stop_now() -> None:
    # Payments refuses the stop once, taking nothing; lane time then passes its time.
    lane, sent, transaction = _rate_lane(
        lambda call, key: (PaymentsAPIError(503, "ledger_unavailable")
                           if key.endswith(":1:effect:1") else None))
    controls = lane.controls()
    controls.install_rule(Rule.model_validate(RULE | {"ruling": _ruling(_stop(RUNNING + 60))}))
    _file(lane, transaction)
    assert controls.cases(transaction).cases[0].state == "applying"

    controls.set_time(RUNNING + 120)
    controls.resume_rule("payee-end")

    # Only the resend reached payments, built afresh: a stop now, with no passed time.
    [(_, resent)] = sent.sent("stop")
    assert "at" not in resent
    assert (lane.part(transaction)["stop"]["effectiveAt"],
            lane.part(transaction)["stop"]["cause"]) == (RUNNING + 120, "authority")
    assert controls.cases(transaction).cases[0].state == "closed"


PENALTY_RULING = _ruling({"kind": "reverse", "part": 0, "amount": "100"},
                         {"kind": "penalty", "amount": "1000"})


def test_a_penalty_larger_than_is_held_reverses_what_earlier_effects_left_in_mandate_order(
) -> None:
    lane = Lane()
    transaction = lane.approve(parts=2, amount="300")
    controls = lane.controls()
    controls.install_rule(Rule.model_validate(RULE | {"ruling": PENALTY_RULING}))

    case_ref = _file(lane, transaction)["case"]["case_ref"]

    reverses = lane.events(transaction, "reverse")
    assert [(event["event"]["part"], event["event"]["amount"]) for event in reverses] == [
        (0, "100"), (0, "200"), (1, "300")]
    # The penalty's reversals are keyed beneath its effect, and carry its id.
    assert [event["requestId"] for event in reverses[1:]] == [
        f"mediation:{case_ref}:1:effect:2:part:{part}" for part in (0, 1)]
    assert {event["event"]["payload"]["effect_id"] for event in reverses[1:]} == {
        f"{case_ref}:1:2"}
    assert [lane.part(transaction, index)["held"] for index in (0, 1)] == ["0", "0"]
    assert controls.cases(transaction).cases[0].state == "closed"


def test_a_penalty_on_a_rate_part_reverses_its_held_earnings_not_its_reservation() -> None:
    lane, sent, transaction = _rate_lane()
    reserved = lane.part(transaction)["reserved"]
    assert int(reserved) > 0
    lane.controls().install_rule(Rule.model_validate(RULE | {"ruling": _ruling(
        {"kind": "penalty", "amount": "100000"})}))

    _file(lane, transaction)

    assert [(event["part"], event["amount"]) for _, event in sent.sent("reverse")] == [
        (0, RATE_PRICE)]
    part = lane.part(transaction)
    assert (part["held"], part["reversed"], part["reserved"]) == ("0", RATE_PRICE, reserved)


def test_a_penalty_whose_later_reversal_fails_resumes_without_reversing_twice() -> None:
    lane = Lane(lambda peer: Failing(
        peer, lambda call, key: (PaymentsAPIError(503, "ledger_unavailable")
                                 if key.endswith(":effect:2:part:1") else None)))
    transaction = lane.approve(parts=2, amount="300")
    controls = lane.controls()
    controls.install_rule(Rule.model_validate(RULE | {"ruling": PENALTY_RULING}))

    _file(lane, transaction)
    assert controls.cases(transaction).cases[0].state == "applying"
    controls.resume_rule("payee-end")

    assert [(event["event"]["part"], event["event"]["amount"])
            for event in lane.events(transaction, "reverse")] == [
        (0, "100"), (0, "200"), (1, "300")]
    assert controls.cases(transaction).cases[0].state == "closed"


class _LostThenRefused:
    """The payments peer: the first send of the key ending ``suffix`` is taken and its
    answer lost, the second refused before payments replays it, the rest answered."""

    def __init__(self, peer: Any, suffix: str) -> None:
        self.peer = peer
        self.suffix = suffix
        self.sends = 0

    def get_transaction(self, transaction: str) -> Any:
        return self.peer.get_transaction(transaction)

    def submit_event(self, transaction: str, event: Any, *, request_id: str) -> Any:
        if request_id.endswith(self.suffix):
            self.sends += 1
            if self.sends == 1:
                self.peer.submit_event(transaction, event, request_id=request_id)
                raise PaymentsTransportError("payments service request failed")
            if self.sends == 2:
                raise PaymentsAPIError(503, "ledger_unavailable")
        return self.peer.submit_event(transaction, event, request_id=request_id)


def test_a_refusal_after_a_lost_answer_resends_the_stop_payments_took() -> None:
    lane = Lane(lambda peer: _LostThenRefused(peer, ":1:effect:1"))
    transaction = lane.approve_rate()
    controls = lane.controls()
    controls.set_time(RUNNING)
    controls.install_rule(Rule.model_validate(RULE | {"ruling": _ruling(_stop(RUNNING + 60))}))
    _file(lane, transaction)

    controls.set_time(RUNNING + 120)
    controls.resume_rule("payee-end")
    assert controls.cases(transaction).cases[0].state == "applying"
    controls.resume_rule("payee-end")

    # The resend is the stop payments took, scheduled before its time passed.
    [stop] = lane.events(transaction, "stop")
    assert stop["event"]["at"] == RUNNING + 60
    assert lane.part(transaction)["stop"]["effectiveAt"] == RUNNING + 60
    assert controls.cases(transaction).cases[0].state == "closed"


def test_a_ruling_held_at_its_gate_with_a_stop_sends_nothing_until_resumed() -> None:
    lane, sent, transaction = _rate_lane()
    controls = lane.controls()
    controls.install_rule(Rule.model_validate(RULE | {"pause_before_effects": True,
                                                      "ruling": _ruling(_stop())}))

    _file(lane, transaction)

    assert sent.sent("stop") == []
    assert "stop" not in lane.part(transaction)
    controls.resume_rule("payee-end")
    assert len(sent.sent("stop")) == 1
    assert lane.part(transaction)["stop"]["cause"] == "authority"
    assert controls.cases(transaction).cases[0].state == "closed"


def test_a_payments_failure_after_a_stop_and_before_a_reverse_resumes_without_stopping_twice(
) -> None:
    lane, sent, transaction = _rate_lane(
        lambda call, key: (PaymentsAPIError(503, "ledger_unavailable")
                           if key.endswith(":1:effect:2") else None))
    controls = lane.controls()
    controls.install_rule(Rule.model_validate(RULE | {"ruling": _ruling(
        _stop(), {"kind": "reverse", "part": 0, "amount": RATE_PRICE})}))

    _file(lane, transaction)
    assert controls.cases(transaction).cases[0].state == "applying"
    assert lane.events(transaction, "reverse") == []
    controls.resume_rule("payee-end")

    assert len(sent.sent("stop")) == 1
    assert len(lane.events(transaction, "stop")) == 1
    assert [event["event"]["amount"] for event in lane.events(transaction, "reverse")] == [
        RATE_PRICE]
    assert lane.part(transaction)["held"] == "0"
    assert controls.cases(transaction).cases[0].state == "closed"


# A stop whose time has passed: payments stops the part now, and what it earned
# since that time is reversed to the payer, attributed to the stop.
@pytest.mark.parametrize(("at", "reversed_amount"), [
    (T0 + HOUR // 2, RATE_PRICE), (T0 + HOUR + 60, None), (RUNNING + HOUR, None),
], ids=["passed, with earnings since", "passed, with none since", "not yet reached"])
def test_a_ruled_stop_reverses_what_the_part_earned_since_its_passed_time(
    at: int, reversed_amount: str | None,
) -> None:
    lane, sent, transaction = _rate_lane()
    lane.controls().install_rule(Rule.model_validate(RULE | {"ruling": _ruling(_stop(at))}))

    case_ref = _file(lane, transaction)["case"]["case_ref"]

    reverses = lane.events(transaction, "reverse")
    if reversed_amount is None:
        assert reverses == []
        assert lane.part(transaction)["held"] == RATE_PRICE
    else:
        [reverse] = reverses
        assert reverse["account"] == lane.authority.account
        assert reverse["requestId"] == f"mediation:{case_ref}:1:effect:1:reverse"
        assert reverse["event"] == {"kind": "reverse", "part": 0, "amount": reversed_amount,
                                    "payload": {"case_ref": case_ref,
                                                "effect_id": f"{case_ref}:1:1"}}
        assert lane.part(transaction)["held"] == "0"
    assert [key for key, _ in sent.sent("stop")] == [f"mediation:{case_ref}:1:effect:1"]
    assert lane.controls().cases(transaction).cases[0].state == "closed"


def test_a_failed_reversal_after_a_passed_stop_resumes_without_stopping_or_deriving_twice(
) -> None:
    lane, sent, transaction = _rate_lane(
        lambda call, key: (PaymentsAPIError(503, "ledger_unavailable")
                           if key.endswith(":1:effect:1:reverse") else None))
    controls = lane.controls()
    controls.install_rule(Rule.model_validate(RULE | {"ruling": _ruling(
        _stop(T0 + HOUR // 2), {"kind": "penalty", "amount": "1000"})}))

    case_ref = _file(lane, transaction)["case"]["case_ref"]
    assert controls.cases(transaction).cases[0].state == "applying"
    assert lane.events(transaction, "reverse") == []
    controls.resume_rule("payee-end")

    # Only the resent reversal, derived once, reached payments; the stop's reversal
    # took everything held, so the penalty after it reverses nothing.
    assert len(lane.events(transaction, "stop")) == 1
    assert [(key, event["amount"]) for key, event in sent.sent("reverse")] == [
        (f"mediation:{case_ref}:1:effect:1:reverse", RATE_PRICE)]
    assert [event["event"]["amount"] for event in lane.events(transaction, "reverse")] == [
        RATE_PRICE]
    assert controls.cases(transaction).cases[0].state == "closed"


def test_a_passed_stops_reversal_is_derived_once_and_resent_as_it_was() -> None:
    # Prorated, a stop now earns half the second hour, and one ten minutes into it a
    # sixth: the reversal is the difference. Payments takes it and the answer is lost.
    recording: list[Recording] = []

    def wrap(peer: Any) -> Any:
        recording.append(Recording(peer))
        return Failing(recording[0], lambda call, key: (
            PaymentsTransportError("payments service request failed")
            if key.endswith(":1:effect:1:reverse") else None), after_commit=True)

    lane = Lane(wrap)
    transaction = lane.approve_rate()
    controls = lane.controls()
    controls.set_time(RUNNING)
    controls.install_rule(Rule.model_validate(RULE | {"ruling": _ruling(
        {"kind": "stop", "part": 0, "at": T0 + HOUR + 600, "partialPeriod": "prorated"})}))
    case_ref = _file(lane, transaction)["case"]["case_ref"]
    assert controls.cases(transaction).cases[0].state == "applying"
    failing = lane.app.state.double.payments
    reads = failing.reads

    controls.resume_rule("payee-end")

    # Resumed, the kept reversal is resent as it was, and no holdings are read again.
    earned_now = int(RATE_PRICE) + int(RATE_PRICE) // 2
    earned_then = int(RATE_PRICE) + int(RATE_PRICE) * 600 // HOUR
    reversal = (f"mediation:{case_ref}:1:effect:1:reverse", str(earned_now - earned_then))
    assert [(key, event["amount"]) for key, event in recording[0].sent("reverse")] == [
        reversal, reversal]
    assert failing.reads == reads
    assert lane.part(transaction)["held"] == str(earned_then)
    assert controls.cases(transaction).cases[0].state == "closed"
