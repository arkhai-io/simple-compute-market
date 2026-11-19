"""The rule book: which rule a call meets, and the control refusals it gives."""

from __future__ import annotations

import pytest

from lane_double_controls import ControlError, Rule

from mediation_lane_double.rules import RuleBook

FILE = {"operation": "file", "filer": "payee", "kind": "delivery_end", "cause": "payee",
        "transaction": "a" * 64}


def _rule(rule_id: str, match: dict[str, str], **action: object) -> Rule:
    action = action or {"refusal": {"status": 503, "code": "temporarily_unavailable"}}
    return Rule.model_validate({"rule_id": rule_id, "match": match, **action})


def test_a_rule_matches_when_every_stated_property_equals_the_calls() -> None:
    book = RuleBook()
    book.install(_rule("payer", {"operation": "file", "filer": "payer"}))
    book.install(_rule("payee", {"operation": "file", "filer": "payee"}))

    entry = book.first(FILE)

    assert entry is not None and entry.rule.rule_id == "payee"
    assert book.first({"operation": "append", "filer": "payee"}) is None
    # A property the call does not have never equals a stated one.
    assert book.first({"operation": "file"}) is None


def test_the_first_rule_in_install_order_wins_after_any_unavailable_rule() -> None:
    book = RuleBook()
    book.install(_rule("first", {"operation": "file"}))
    book.install(_rule("second", {}))
    before = book.first(FILE)

    book.install(_rule("down", {}, unavailable=True))

    after = book.first(FILE)
    assert before is not None and before.rule.rule_id == "first"
    assert after is not None and after.rule.rule_id == "down"


def test_a_rule_an_operation_cannot_act_on_is_passed_over_for_it() -> None:
    book = RuleBook()
    book.install(_rule("rule-everything", {}, ruling={
        "basis": "operator", "delivery_end": False, "close": True, "effects": []}))
    book.install(_rule("refuse", {}))

    read = book.first({"operation": "record"})
    filing = book.first(FILE)

    assert read is not None and read.rule.rule_id == "refuse"
    assert filing is not None and filing.rule.rule_id == "rule-everything"


@pytest.mark.parametrize("match", [
    {"filer": "seller"}, {"kind": "refund"}, {"cause": "seller"}, {"transaction": "tx-1"},
], ids=["filer", "kind", "cause", "transaction"])
def test_a_match_value_no_call_can_have_is_refused(match: dict[str, str]) -> None:
    with pytest.raises(ControlError) as refused:
        RuleBook().install(_rule("a", match))

    assert (refused.value.status, refused.value.code) == (422, "invalid_request")


def test_install_refuses_an_existing_id_and_what_the_double_cannot_do() -> None:
    book = RuleBook()
    book.install(_rule("a", {}))

    with pytest.raises(ControlError) as existing:
        book.install(_rule("a", {}))
    with pytest.raises(ControlError) as payments_property:
        book.install(_rule("b", {"route": "events"}))
    with pytest.raises(ControlError) as unpublished:
        book.install(_rule("c", {}, refusal={"status": 409, "code": "no_such_code"}))
    with pytest.raises(ControlError) as award:
        book.install(_rule("d", {}, ruling={
            "basis": "operator", "delivery_end": False, "close": True,
            "effects": [{"kind": "award", "part": 0, "amount": "1"}]}))

    assert (existing.value.status, existing.value.code) == (409, "rule_exists")
    for refused in (payments_property, unpublished, award):
        assert (refused.value.status, refused.value.code) == (422, "invalid_request")
    assert [view.rule.rule_id for view in book.listing().rules] == ["a"]


@pytest.mark.parametrize("effect", [
    {"kind": "stop", "part": 0, "at": 1_800_000_000, "partialPeriod": "prorated"},
    {"kind": "penalty", "amount": "10"},
    {"kind": "award", "part": 0, "amount": "1"},
], ids=["stop", "penalty", "award"])
def test_a_ruling_with_an_effect_other_than_reverse_is_refused(effect: dict) -> None:
    book = RuleBook()

    with pytest.raises(ControlError) as refused:
        book.install(_rule("a", {}, ruling={"basis": "operator", "delivery_end": False,
                                            "close": True, "effects": [effect]}))

    assert (refused.value.status, refused.value.code) == (422, "invalid_request")
    assert book.listing().rules == []


def test_deleting_and_resuming_refuse_an_unknown_rule_and_resuming_one_not_waiting() -> None:
    book = RuleBook()
    book.install(_rule("a", {}))

    with pytest.raises(ControlError) as not_waiting:
        book.waiting("a")
    book.set_waiting("a", "case-1", True)
    waiting = book.waiting("a")
    book.delete("a")
    with pytest.raises(ControlError) as deleted:
        book.delete("a")
    with pytest.raises(ControlError) as unknown:
        book.waiting("a")
    # A case's rule deleted while it waited is left as it is.
    book.set_waiting("a", "case-1", False)

    assert (not_waiting.value.status, not_waiting.value.code) == (409, "rule_not_waiting")
    assert waiting == ["case-1"]
    assert (deleted.value.status, deleted.value.code) == (404, "rule_not_found")
    assert (unknown.value.status, unknown.value.code) == (404, "rule_not_found")


def test_the_listing_counts_matches_and_waiting_cases() -> None:
    book = RuleBook()
    book.install(_rule("a", {}))
    entry = book.first(FILE)
    assert entry is not None

    book.count(entry)
    book.count(entry)
    book.set_waiting("a", "case-1", True)
    book.set_waiting("a", "case-2", True)
    book.set_waiting("a", "case-1", False)

    [view] = book.listing().rules
    assert (view.matched, view.waiting) == (2, 1)
