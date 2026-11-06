"""Bearer authentication maps a token to its account, and the fixture holds only usable tokens."""

from __future__ import annotations

import pytest

from market_arkhai_payments.errors import PaymentsAPIError

from payments_lane_double.accounts import FixtureError, parse_accounts
from payments_lane_double.app import PaymentsDouble

from conftest import committed_accounts


@pytest.fixture
def double() -> PaymentsDouble:
    return PaymentsDouble(parse_accounts(committed_accounts()), clock=lambda: 1_800_000_000)


@pytest.mark.parametrize("scheme", ["Bearer", "bearer", "BEARER"])
def test_the_scheme_name_is_case_insensitive(double: PaymentsDouble, scheme: str) -> None:
    buyer = double.directory.role("buyer")

    assert double.authenticate(f"{scheme} {buyer.token}") == buyer.account


@pytest.mark.parametrize("header", [None, "", "Basic abc", "Bearer", "Bearer unknown-token"])
def test_anything_but_a_known_bearer_token_is_unauthenticated(
        double: PaymentsDouble, header: str | None) -> None:
    with pytest.raises(PaymentsAPIError) as refused:
        double.authenticate(header)

    assert (refused.value.status_code, refused.value.code) == (401, "authentication_required")


def test_a_token_with_whitespace_is_refused_at_load() -> None:
    document = committed_accounts()
    # A public test value, never for a public network.
    document["accounts"]["seller"]["token"] = "two words"

    with pytest.raises(FixtureError, match="whitespace"):
        parse_accounts(document)
