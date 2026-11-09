"""The committed fixture file loads, with its accounts, policy and control values."""

from __future__ import annotations

import pytest

from market_identity import Ed25519Signer

from payments_lane_double.accounts import FixtureError, load_accounts, parse_accounts

from conftest import FIXTURES, committed_accounts

# The payments kit's FakePaymentsClient signs with this public development seed;
# never use it on a public network.
FAKE_CLIENT_SEED = bytes([7]) * 32


def test_the_account_fixture_loads_with_its_policy_and_a_funded_buyer() -> None:
    directory = load_accounts(FIXTURES / "accounts.toml")

    assert directory.asset == "USD/6" and directory.fee_bps == 250
    assert directory.signer().identity == directory.receipt_identity
    assert directory.role("buyer").funding > 0
    assert directory.role("buyer").token and directory.role("seller").token


def test_the_control_token_and_the_rotation_key_load_apart_from_the_accounts() -> None:
    directory = load_accounts(FIXTURES / "accounts.toml")

    assert directory.control_token
    assert directory.account_for_token(directory.control_token) is None
    assert directory.rotated_signer().identity != directory.receipt_identity


def test_a_control_token_that_is_also_an_accounts_token_is_refused() -> None:
    document = committed_accounts()
    document["control_token"] = document["accounts"]["buyer"]["token"]

    with pytest.raises(FixtureError, match="control_token"):
        parse_accounts(document)


def test_a_rotation_seed_equal_to_the_receipt_seed_is_refused() -> None:
    document = committed_accounts()
    document["rotation_seed"] = document["receipt_seed"]

    with pytest.raises(FixtureError, match="rotation_seed"):
        parse_accounts(document)


def test_the_receipt_key_is_not_the_in_process_fakes() -> None:
    directory = load_accounts(FIXTURES / "accounts.toml")

    assert directory.receipt_identity != Ed25519Signer(FAKE_CLIENT_SEED).identity


def test_the_dispute_authoritys_token_resolves_to_its_account_alone() -> None:
    directory = load_accounts(FIXTURES / "accounts.toml")
    authority = directory.role("dispute_authority")

    assert authority.token is not None
    assert directory.account_for_token(authority.token) == authority.account
    assert authority.token not in {entry.token for entry in directory.accounts
                                   if entry.account != authority.account}
