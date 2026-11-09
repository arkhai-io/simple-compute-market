"""The double's controls through the typed control client, against the app in process.

The client sends exactly the requests a scenario sends, and the kit's real
``MediationClient`` shows what each control does to the API (``support``).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable

import pytest

from lane_double_controls import ControlError, Rule, Ruling
from market_arkhai_mediation.client import MediationAPIError
from market_arkhai_mediation.contract import resource_bytes, wire
from market_arkhai_mediation.models import ReadAfter
from market_arkhai_payments.canonical import agreement_hash

from support import AGREEMENT, DAY, T0, Lane, filing, run


def _file(lane: Lane, transaction: str, key: str = "filing-1") -> dict:
    async def file() -> dict:
        async with lane.client("seller") as client:
            return wire(await client.file(filing(transaction), idempotency_key=key))
    return run(file())


def _refused(call: Callable[..., object], *args: object) -> tuple[int, str]:
    with pytest.raises(ControlError) as refused:
        call(*args)
    return refused.value.status, refused.value.code


def test_rules_install_list_and_delete_with_their_refusals() -> None:
    lane = Lane()
    controls = lane.controls()
    rule = Rule.model_validate({"rule_id": "refuse", "match": {"operation": "file"},
                                "refusal": {"status": 503, "code": "temporarily_unavailable"}})

    installed = controls.install_rule(rule)

    assert (installed.matched, installed.waiting) == (0, 0)
    assert _refused(controls.install_rule, rule) == (409, "rule_exists")
    assert _refused(controls.resume_rule, "refuse") == (409, "rule_not_waiting")
    controls.delete_rule("refuse")
    assert controls.rules().rules == []
    assert _refused(controls.delete_rule, "refuse") == (404, "rule_not_found")
    assert _refused(controls.resume_rule, "refuse") == (404, "rule_not_found")


def test_a_rule_the_double_cannot_apply_is_refused() -> None:
    controls = Lane().controls()
    unpublished = Rule.model_validate({"rule_id": "a", "match": {},
                                       "refusal": {"status": 409, "code": "no_such_code"}})
    penalty = Rule.model_validate({"rule_id": "b", "match": {}, "ruling": {
        "basis": "operator", "delivery_end": False, "close": True,
        "effects": [{"kind": "penalty", "amount": "10"}]}})
    payments_match = Rule.model_validate({"rule_id": "c", "match": {"route": "events"},
                                          "unavailable": None, "refusal": {
                                              "status": 503, "code": "temporarily_unavailable"}})

    assert _refused(controls.install_rule, unpublished) == (422, "invalid_request")
    assert _refused(controls.install_rule, penalty) == (422, "invalid_request")
    assert _refused(controls.install_rule, payments_match) == (422, "invalid_request")
    assert controls.rules().rules == []


def test_a_refusal_rule_is_answered_to_the_kit_client_and_counted() -> None:
    lane = Lane()
    transaction = lane.approve()
    controls = lane.controls()
    controls.install_rule(Rule.model_validate({
        "rule_id": "refuse", "match": {"operation": "file", "transaction": transaction},
        "refusal": {"status": 503, "code": "temporarily_unavailable"}}))

    with pytest.raises(MediationAPIError) as refused:
        _file(lane, transaction)

    assert (refused.value.status, refused.value.code) == (503, "temporarily_unavailable")
    assert controls.rules().rules[0].matched == 1
    assert controls.cases(transaction).cases == []


def test_a_pending_override_is_followed_by_the_same_case_once_removed() -> None:
    lane = Lane()
    transaction = lane.approve()
    controls = lane.controls()
    controls.install_rule(Rule.model_validate({
        "rule_id": "pending", "match": {"operation": "file"},
        "filing_answer": {"status": "pending"}}))

    pending = _file(lane, transaction)
    controls.delete_rule("pending")
    filed = _file(lane, transaction)

    assert pending["status"] == "pending"
    assert filed["status"] == "accepted"
    assert filed["case"]["case_ref"] == pending["case_ref"]
    assert len(controls.cases(transaction).cases) == 1


@pytest.mark.parametrize(("answer", "expected"), [
    ({"status": "error", "code": "temporarily_unavailable"},
     {"status": "error", "code": "temporarily_unavailable"}),
    ({"status": "rejected", "reason": "storefront_not_approved"},
     {"status": "rejected", "reason": "storefront_not_approved"}),
], ids=["error", "rejected"])
def test_a_programmed_filing_answer_is_given_in_place_of_filing(answer: dict,
                                                                expected: dict) -> None:
    lane = Lane()
    transaction = lane.approve()
    lane.controls().install_rule(Rule.model_validate({
        "rule_id": "answer", "match": {"operation": "file"}, "filing_answer": answer}))

    given = _file(lane, transaction)

    assert {key: given[key] for key in expected} == expected
    assert lane.controls().cases(transaction).cases == []
    assert lane.events(transaction, "extend") == []


def test_an_operator_decision_reverses_part_and_leaves_the_case_open() -> None:
    lane = Lane()
    transaction = lane.approve()
    case_ref = _file(lane, transaction)["case"]["case_ref"]
    controls = lane.controls()

    decided = controls.decide(case_ref, Ruling.model_validate({
        "basis": "operator", "delivery_end": False, "close": False,
        "effects": [{"kind": "reverse", "part": 0, "amount": "250"}]}))

    assert decided.state == "open"
    assert lane.part(transaction)["reversed"] == "250"


def test_close_without_ruling_and_the_case_refusals() -> None:
    lane = Lane()
    transaction = lane.approve()
    case_ref = _file(lane, transaction)["case"]["case_ref"]
    controls = lane.controls()
    ruling = Ruling.model_validate({"basis": "operator", "delivery_end": False,
                                    "close": True, "effects": []})

    closed = controls.close_case(case_ref)

    assert closed.state == "closed"
    assert lane.part(transaction)["extensions"] == []

    async def read() -> list[dict]:
        async with lane.client("buyer") as client:
            page = await client.read_record(ReadAfter.model_validate(
                {"agreement": agreement_hash(AGREEMENT), "after": 0}), transaction=transaction)
            return [entry["entry"] for entry in wire(page)["entries"]]

    last = run(read())[-1]
    assert (last["kind"], last["reason"], last["basis"], last["outcome"]) == (
        "closed", "dismissed", "operator", [])
    assert _refused(controls.close_case, case_ref) == (409, "case_closed")
    assert _refused(controls.decide, case_ref, ruling) == (409, "case_closed")
    assert _refused(controls.close_case, "case-404") == (404, "case_not_found")
    assert _refused(controls.decide, "case-404", ruling) == (404, "case_not_found")


def test_the_case_listing_is_by_transaction() -> None:
    lane = Lane()
    transaction = lane.approve()
    case_ref = _file(lane, transaction)["case"]["case_ref"]
    controls = lane.controls()

    [case] = controls.cases(transaction).cases

    assert (case.case_ref, case.state, case.filer, case.kind, case.cause) == (
        case_ref, "open", "payee", "delivery_end", "payee")
    assert controls.cases("0" * 64).cases == []


def test_the_clock_and_status() -> None:
    lane = Lane()
    controls = lane.controls()

    advanced = controls.advance_clock(DAY)
    status = controls.status()
    reset = controls.reset_clock()

    assert (advanced.perceived_now, advanced.offset_seconds) == (T0 + DAY, DAY)
    assert (status.perceived_now, status.offset_seconds) == (T0 + DAY, DAY)
    assert (reset.perceived_now, reset.offset_seconds) == (T0, 0)
    assert status.contracts == {
        f"contract_data/{name}": hashlib.sha256(resource_bytes(name)).hexdigest()
        for name in ("mediation.schema.json", "mediation.vectors.json", "publication.json")}


def test_records_are_dated_by_the_perceived_clock() -> None:
    lane = Lane()
    transaction = lane.approve()
    lane.controls().advance_clock(3_600)

    _file(lane, transaction)

    async def read() -> list[dict]:
        async with lane.client("buyer") as client:
            page = await client.read_record(ReadAfter.model_validate(
                {"agreement": agreement_hash(AGREEMENT), "after": 0}), transaction=transaction)
            return [entry["entry"] for entry in wire(page)["entries"]]

    assert [entry["at"] for entry in run(read())] == [T0 + 3_600]


@pytest.mark.parametrize("token", ["wrong-token", "seller"])
def test_a_control_call_with_another_token_is_refused(token: str) -> None:
    lane = Lane()
    controls = lane.controls(token=lane.token(token) if token == "seller" else token)

    assert _refused(controls.status) == (401, "authentication_required")


def test_a_control_call_with_no_authorization_is_refused() -> None:
    # A rejection-path test: the typed client always sends its token, so the
    # request without one is made by hand, and only its status is asserted.
    assert Lane().http.get("/test/status").status_code == 401


def test_closing_while_payments_does_not_lift_answers_payments_unavailable() -> None:
    lane = Lane()
    transaction = lane.approve()
    case_ref = _file(lane, transaction)["case"]["case_ref"]
    lane.payments.unavailable = True

    assert _refused(lane.controls().close_case, case_ref) == (502, "payments_unavailable")
    lane.payments.unavailable = False
    assert lane.controls().cases(transaction).cases[0].state == "open"


def test_a_refusal_rule_on_a_read_is_answered() -> None:
    lane = Lane()
    transaction = lane.approve()
    _file(lane, transaction)
    lane.controls().install_rule(Rule.model_validate({
        "rule_id": "no-reads", "match": {"operation": "record"},
        "refusal": {"status": 503, "code": "temporarily_unavailable"}}))

    async def read() -> None:
        async with lane.client("buyer") as client:
            await client.read_record(ReadAfter.model_validate(
                {"agreement": agreement_hash(AGREEMENT), "after": 0}), transaction=transaction)

    with pytest.raises(MediationAPIError) as refused:
        run(read())
    assert (refused.value.status, refused.value.code) == (503, "temporarily_unavailable")


@pytest.mark.parametrize("rule", [
    {"match": {"operation": "append"}, "filing_answer": {"status": "pending"}},
    {"match": {"operation": "case"}, "ruling": {
        "basis": "operator", "delivery_end": False, "close": True, "effects": []}},
    {"match": {"operation": "record", "transaction": "a" * 64},
     "refusal": {"status": 503, "code": "temporarily_unavailable"}},
    {"match": {"operation": "settle"},
     "refusal": {"status": 503, "code": "temporarily_unavailable"}},
], ids=["filing answer on append", "ruling on a read", "scoped record read", "no such operation"])
def test_a_rule_that_could_never_act_is_refused(rule: dict) -> None:
    controls = Lane().controls()

    assert _refused(controls.install_rule, Rule.model_validate({"rule_id": "r", **rule})) == (
        422, "invalid_request")
