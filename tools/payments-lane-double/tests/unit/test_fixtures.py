"""The committed fixture files load, and the pinned dispute authority is inert."""

from __future__ import annotations

from market_deal_lifecycle.configuration import DisputeEntry
from market_identity import Ed25519Signer, Identity

from payments_lane_double.accounts import load_accounts

from conftest import FIXTURES, committed_dispute_authority

# The payments kit's FakePaymentsClient signs with this public development seed;
# never use it on a public network.
FAKE_CLIENT_SEED = bytes([7]) * 32


def test_the_account_fixture_loads_with_its_policy_and_a_funded_buyer() -> None:
    directory = load_accounts(FIXTURES / "accounts.toml")

    assert directory.asset == "USD/6" and directory.fee_bps == 250
    assert directory.signer().identity == directory.receipt_identity
    assert directory.role("buyer").funding > 0
    assert directory.role("buyer").token and directory.role("seller").token


def test_the_receipt_key_is_not_the_in_process_fakes() -> None:
    directory = load_accounts(FIXTURES / "accounts.toml")

    assert directory.receipt_identity != Ed25519Signer(FAKE_CLIENT_SEED).identity


def test_the_dispute_authority_is_a_registry_recommendation_at_an_unresolvable_origin() -> None:
    document = committed_dispute_authority()
    entry = DisputeEntry.model_validate(document)
    scheme, identifier = entry.record_key.split(":", 1)

    assert entry.interface == "arkhai.mediation.v1"
    assert entry.origin == "https://dispute.invalid"
    assert Identity(scheme=scheme, identifier=identifier).scheme.value == "ed25519"
    assert "arkhai.payments.v1" in entry.advertisement.mechanisms


def test_the_dispute_authority_account_is_in_the_directory_without_a_token() -> None:
    directory = load_accounts(FIXTURES / "accounts.toml")
    authority = directory.role("dispute_authority")

    assert authority.account == committed_dispute_authority()["account"]
    assert authority.token is None
    assert all(directory.account_for_token(entry.token) != authority.account
               for entry in directory.accounts if entry.token is not None)
