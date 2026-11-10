"""The control models refuse what the control semantics refuse, before anything is installed."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from lane_double_controls.models import (
    ClockAdvance,
    ControlError,
    FilingAnswer,
    Funding,
    Rule,
    Ruling,
)

_REVERSE = {"kind": "reverse", "part": 0, "amount": "500"}


def _rule(**fields: Any) -> Rule:
    return Rule.model_validate({"rule_id": "r1", **fields})


def test_a_rule_without_match_is_refused() -> None:
    with pytest.raises(ValidationError, match="match"):
        _rule(unavailable=True)


def test_an_empty_match_is_a_stated_scope() -> None:
    rule = _rule(match={}, refusal={"status": 409, "code": "insufficient_funds"})

    assert rule.match == {}


def test_an_unavailable_rule_with_a_non_empty_match_is_refused() -> None:
    with pytest.raises(ValidationError, match="match is {}"):
        _rule(match={"route": "events"}, unavailable=True)


def test_an_unavailable_rule_covering_every_route_is_accepted() -> None:
    assert _rule(match={}, unavailable=True).actions() == ["unavailable"]


@pytest.mark.parametrize("actions", [
    {},
    {"unavailable": True, "drop_response_after_commit": True},
    {"refusal": {"status": 409, "code": "x"}, "ruling": {
        "basis": "operator", "delivery_end": False, "effects": [], "close": True}},
])
def test_a_rule_takes_exactly_one_action(actions: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="exactly one action"):
        _rule(match={}, **actions)


def test_only_a_ruling_pauses_before_its_effects() -> None:
    with pytest.raises(ValidationError, match="pause"):
        _rule(match={}, drop_response_after_commit=True, pause_before_effects=True)


@pytest.mark.parametrize("rule_id", ["", "a/b", "x" * 129, "has space"])
def test_a_rule_id_fits_in_a_path_segment(rule_id: str) -> None:
    with pytest.raises(ValidationError):
        Rule.model_validate({"rule_id": rule_id, "match": {}, "unavailable": True})


def test_a_refusal_is_an_error_status() -> None:
    with pytest.raises(ValidationError):
        _rule(match={}, refusal={"status": 200, "code": "ok"})


def test_an_unknown_field_is_refused() -> None:
    with pytest.raises(ValidationError):
        _rule(match={}, unavailable=True, delay_seconds=3)


def test_an_empty_effect_list_is_a_ruling_that_moves_no_money() -> None:
    ruling = Ruling(basis="operator", delivery_end=True, effects=[], close=True)

    assert ruling.effects == []


def test_a_contract_effect_is_accepted() -> None:
    ruling = Ruling(basis="payee_filed", delivery_end=True, effects=[_REVERSE], close=True)

    assert ruling.effects == [_REVERSE]


@pytest.mark.parametrize("effect", [
    {"kind": "reverse", "part": 0},
    {"kind": "reverse", "part": 64, "amount": "1"},
    {"kind": "refund", "part": 0, "amount": "1"},
    {"kind": "reverse", "part": 0, "amount": "1", "extra": True},
])
def test_a_malformed_effect_is_refused(effect: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="not a contract Effect"):
        Ruling(basis="operator", delivery_end=False, effects=[effect], close=False)


def test_a_delivery_end_is_stated_only_by_the_flag() -> None:
    with pytest.raises(ValidationError, match="delivery_end"):
        Ruling(basis="operator", delivery_end=False,
               effects=[{"kind": "end_delivery", "at": 1_800_000_000}], close=True)


def test_a_basis_outside_the_contract_is_refused() -> None:
    with pytest.raises(ValidationError, match="not a contract RulingBasis"):
        Ruling.model_validate({"basis": "mechanical", "delivery_end": True, "effects": [],
                               "close": True})


@pytest.mark.parametrize("answer", [
    {"status": "pending"},
    {"status": "error", "code": "protection_incomplete"},
    {"status": "rejected", "reason": "filer_not_party"},
])
def test_a_filing_answer_the_contract_allows_is_accepted(answer: dict[str, str]) -> None:
    assert FilingAnswer.model_validate(answer).status == answer["status"]


@pytest.mark.parametrize("answer", [
    {"status": "pending", "code": "protection_incomplete"},
    {"status": "error"},
    {"status": "error", "code": "ledger_unavailable"},
    {"status": "rejected", "reason": "mapping_mismatch"},
    {"status": "rejected", "code": "invalid_request"},
    {"status": "accepted"},
])
def test_a_filing_answer_outside_the_contract_is_refused(answer: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        FilingAnswer.model_validate(answer)


def test_a_payments_rule_cannot_match_on_mediation_properties() -> None:
    rule = _rule(match={"filer": "payee"}, refusal={"status": 409, "code": "x"})

    with pytest.raises(ControlError) as refused:
        rule.check_supported("payments")
    assert (refused.value.status, refused.value.code) == (422, "invalid_request")
    rule.check_supported("mediation")


def test_a_payments_rule_cannot_rule() -> None:
    rule = _rule(match={}, ruling={"basis": "operator", "delivery_end": False,
                                   "effects": [], "close": True})

    with pytest.raises(ControlError) as refused:
        rule.check_supported("payments")
    assert refused.value.code == "invalid_request"


@pytest.mark.parametrize("seconds", [0, -1])
def test_the_clock_advances_only_forward(seconds: int) -> None:
    with pytest.raises(ValidationError):
        ClockAdvance(seconds=seconds)


@pytest.mark.parametrize("amount", ["0", "-5", "1.5", "", "01"])
def test_funding_is_a_positive_count_of_minor_units(amount: str) -> None:
    with pytest.raises(ValidationError):
        Funding(account="00000000-0000-4000-8000-0000000000b1", amount=amount)


def test_a_control_error_carries_one_body() -> None:
    error = ControlError(404, "rule_not_found", "no rule r9 is installed")

    assert error.body() == {"code": "rule_not_found", "message": "no rule r9 is installed"}
