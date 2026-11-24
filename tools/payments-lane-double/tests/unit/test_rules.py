"""The rule book: what a rule can match, which rule a call meets, and the refusals it gives."""

from __future__ import annotations

import json
from typing import Any

import pytest

from lane_double_controls.middleware import Fault, FaultRequest
from lane_double_controls.models import ControlError, Rule
from market_arkhai_payments.canonical import agreement_hash
from market_arkhai_payments.errors import PaymentsAPIError
from market_arkhai_payments.receipts import transaction_id

from payments_lane_double.accounts import parse_accounts
from payments_lane_double.rules import RuleBook

from conftest import committed_accounts

TRANSACTION = "a" * 64


@pytest.fixture
def book() -> RuleBook:
    return RuleBook(parse_accounts(committed_accounts()))


def _buyer() -> tuple[str, str]:
    buyer = committed_accounts()["accounts"]["buyer"]
    return buyer["account"], buyer["token"]


def call(method: str, path: str, body: Any = None, token: str | None = None) -> FaultRequest:
    headers = {"authorization": f"Bearer {token}"} if token else {}
    return FaultRequest(method=method, path=path, headers=headers,
                        body=b"" if body is None else json.dumps(body).encode())


def rule(rule_id: str, match: dict[str, str], **action: Any) -> Rule:
    return Rule.model_validate({"rule_id": rule_id, "match": match, **action})


def test_an_event_names_its_route_kind_transaction_and_caller(book: RuleBook) -> None:
    account, token = _buyer()

    found = book.properties(call("POST", f"/transactions/{TRANSACTION}/events",
                                 {"kind": "stop"}, token))

    assert found == {"route": "events", "event": "stop", "transaction": TRANSACTION,
                     "account": account}


def test_an_approval_names_the_transaction_its_mandate_will_have(book: RuleBook) -> None:
    account, token = _buyer()
    mandate = {"from": account, "to": committed_accounts()["accounts"]["seller"]["account"],
               "parts": [{"kind": "once", "asset": "USD/6", "amount": "1", "hold": {"for": "P1D"},
                          "authorities": {"stop": [], "reverse": [], "extend": []},
                          "maxHoldExtension": None}],
               "deal": agreement_hash({"listing": "x"}), "fee": {"bps": 250}, "nonce": "n",
               "expires": 1_900_000_000}

    found = book.properties(call("POST", "/transactions", {"mandate": mandate}, token))

    assert found["route"] == "transactions"
    assert found["transaction"] == transaction_id(mandate)


@pytest.mark.parametrize(("method", "path", "route"), [
    ("GET", f"/transactions/{TRANSACTION}", "snapshot"),
    ("GET", f"/transactions/{TRANSACTION}/mandate", "mandate"),
    ("POST", f"/transactions/{TRANSACTION}/attachments", "attachments"),
    ("GET", "/balances/acct", "balances"),
])
def test_each_route_has_its_name(book: RuleBook, method: str, path: str, route: str) -> None:
    assert book.properties(call(method, path))["route"] == route


def test_an_unknown_token_or_path_names_nothing(book: RuleBook) -> None:
    assert book.properties(call("DELETE", "/transactions", token="nobody")) == {}


def test_a_refusal_is_raised_and_counted_by_the_handler_alone(book: RuleBook) -> None:
    book.install(rule("refuse-stop", {"event": "stop"},
                      refusal={"status": 409, "code": "transaction_stopped"}))
    request = call("POST", f"/transactions/{TRANSACTION}/events", {"kind": "stop"})

    assert book.fault_for(request) is None
    with pytest.raises(PaymentsAPIError) as refused:
        book.refuse_if_programmed(request)

    assert (refused.value.status_code, refused.value.code) == (409, "transaction_stopped")
    assert [view.matched for view in book.listing().rules] == [1]


def test_a_fault_is_counted_by_the_middleware_alone(book: RuleBook) -> None:
    book.install(rule("drop-events", {"route": "events"}, drop_response_after_commit=True))
    request = call("POST", f"/transactions/{TRANSACTION}/events", {"kind": "reverse"})

    assert book.fault_for(request) is Fault.DROP_AFTER_COMMIT
    book.refuse_if_programmed(request)

    assert [view.matched for view in book.listing().rules] == [1]


def test_the_first_matching_rule_decides(book: RuleBook) -> None:
    book.install(rule("refuse-all", {}, refusal={"status": 409, "code": "insufficient_funds"}))
    book.install(rule("drop-events", {"route": "events"}, drop_response_after_commit=True))

    assert book.fault_for(call("POST", f"/transactions/{TRANSACTION}/events", {})) is None


def test_unavailable_covers_every_call_whatever_was_installed_first(book: RuleBook) -> None:
    book.install(rule("drop-events", {"route": "events"}, drop_response_after_commit=True))
    book.install(rule("down", {}, unavailable=True))

    assert book.fault_for(call("POST", f"/transactions/{TRANSACTION}/events", {})) is (
        Fault.UNAVAILABLE)
    assert book.fault_for(call("GET", "/nowhere")) is Fault.UNAVAILABLE
    assert [(view.rule.rule_id, view.matched) for view in book.listing().rules] == [
        ("drop-events", 0), ("down", 2)]


def test_a_refusal_must_be_a_published_code(book: RuleBook) -> None:
    with pytest.raises(ControlError) as refused:
        book.install(rule("odd", {}, refusal={"status": 409, "code": "not_a_payments_code"}))

    assert (refused.value.status, refused.value.code) == (422, "invalid_request")
    assert book.listing().rules == []


def test_a_rule_naming_a_mediation_property_is_refused(book: RuleBook) -> None:
    with pytest.raises(ControlError) as refused:
        book.install(rule("odd", {"filer": "payee"}, drop_response_after_commit=True))

    assert refused.value.code == "invalid_request"


def test_an_installed_rule_id_cannot_be_installed_again(book: RuleBook) -> None:
    book.install(rule("r1", {}, unavailable=True))

    with pytest.raises(ControlError) as refused:
        book.install(rule("r1", {"route": "events"}, drop_response_after_commit=True))

    assert (refused.value.status, refused.value.code) == (409, "rule_exists")


def test_a_matched_rule_is_deleted_and_an_unknown_one_is_not_found(book: RuleBook) -> None:
    book.install(rule("r1", {}, unavailable=True))
    book.fault_for(call("GET", "/balances/x"))

    book.delete("r1")

    assert book.listing().rules == []
    with pytest.raises(ControlError) as refused:
        book.delete("r1")
    assert (refused.value.status, refused.value.code) == (404, "rule_not_found")


def test_a_rule_left_behind_is_listed_with_its_counts(book: RuleBook) -> None:
    book.install(rule("left", {"route": "balances"}, drop_response_after_commit=True))
    book.fault_for(call("GET", "/balances/x"))

    [view] = book.listing().rules

    assert (view.rule.rule_id, view.matched, view.waiting) == ("left", 1, 0)
