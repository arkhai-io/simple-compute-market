"""Admission refuses a new approval with the first rule it breaks, in the service's order."""

from __future__ import annotations

from typing import Any

import pytest

from market_arkhai_payments.errors import PaymentsAPIError

from payments_lane_double.accounts import AccountDirectory, parse_accounts
from payments_lane_double.admission import admit

from conftest import committed_accounts

NOW = 1_800_000_000
# A well-formed account the directory does not hold; a public test value, never
# for a public network.
UNKNOWN = "99999999-9999-4999-8999-999999999999"


@pytest.fixture
def directory() -> AccountDirectory:
    return parse_accounts(committed_accounts())


def mandate(directory: AccountDirectory, **changes: Any) -> dict[str, Any]:
    terms: dict[str, Any] = {
        "from": directory.role("buyer").account, "to": directory.role("seller").account,
        "parts": [{"asset": "USD/6"}], "fee": {"bps": 250}, "expires": NOW + 60,
    }
    terms.update(changes)
    return terms


def refusal(directory: AccountDirectory, terms: dict[str, Any]) -> tuple[int, str]:
    with pytest.raises(PaymentsAPIError) as refused:
        admit(terms, now=NOW, directory=directory)
    return refused.value.status_code, refused.value.code


def test_a_mandate_breaking_no_rule_is_admitted(directory: AccountDirectory) -> None:
    admit(mandate(directory), now=NOW, directory=directory)


@pytest.mark.parametrize(("changes", "expected"), [
    ({"expires": NOW, "parts": [{"asset": "USD/2"}]}, (409, "mandate_expired")),
    ({"parts": [{"asset": "USD/6"}, {"asset": "USD/2"}], "fee": {"bps": 100}},
     (422, "unsupported_asset")),
    ({"fee": {"bps": 100}, "to": UNKNOWN}, (422, "fee_mismatch")),
    ({"to": UNKNOWN}, (404, "account_not_found")),
])
def test_the_first_broken_rule_decides_the_refusal(
        directory: AccountDirectory, changes: dict[str, Any], expected: tuple[int, str]) -> None:
    assert refusal(directory, mandate(directory, **changes)) == expected


def test_a_mandate_expiring_this_second_is_already_expired(directory: AccountDirectory) -> None:
    assert refusal(directory, mandate(directory, expires=NOW)) == (409, "mandate_expired")
