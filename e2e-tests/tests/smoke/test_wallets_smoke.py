"""
tests/test_wallets.py
---------------------
Test suite: validate buyer and seller wallet configuration.

Tests
-----
test_wallet_has_sufficient_eth
    The wallet balance must be > minimum_eth_balance (default 0.01 ETH).

test_private_key_matches_wallet_address
    Derive the public address from the configured private key and assert it
    equals the configured walletAddress.  This catches key/address
    mismatches before any live transaction is attempted.
"""

from __future__ import annotations

import logging
from decimal import Decimal

import pytest
from eth_account import Account
from web3 import Web3

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WEI_PER_ETH = Decimal("1e18")


def _wei_to_eth(wei: int) -> Decimal:
    return Decimal(wei) / _WEI_PER_ETH


def _derive_address_from_key(private_key: str) -> str:
    """Return the checksummed Ethereum address for a given private key hex string."""
    # Normalise: strip leading 0x if present
    key = private_key if not private_key.startswith("0x") else private_key
    acct = Account.from_key(key)
    return acct.address


# ---------------------------------------------------------------------------
# Parametrisation helpers
# ---------------------------------------------------------------------------

# We parametrize over buyer/seller so that each role gets its own test
# node in the report and failures are clearly attributed.

@pytest.fixture(
    params=["buyer", "seller"],
    ids=["buyer", "seller"],
    scope="module",
)
def actor_settings(request, buyer_settings, seller_settings):
    """Yield (role_label, settings_dict) for buyer and seller."""
    if request.param == "buyer":
        cfg = buyer_settings
    else:
        cfg = seller_settings

    role = request.param
    if not cfg.get("wallet_address"):
        pytest.fail(
            f"{role}.wallet_address is not configured. "
            f"Set it in config.yml or via ARKHAI_{role.upper()}__WALLET_ADDRESS."
        )
    if not cfg.get("private_key"):
        pytest.fail(
            f"{role}.private_key is not configured. "
            f"Set it in a secrets profile or via ARKHAI_{role.upper()}__PRIVATE_KEY."
        )

    return role, cfg


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.wallets
class TestWalletBalances:
    """Verify each actor has sufficient ETH for gas."""

    def test_wallet_has_sufficient_eth(
        self,
        w3: Web3,
        actor_settings: tuple[str, dict],
        min_eth_balance: Decimal,
    ) -> None:
        """
        The configured wallet must hold more than *minimum_eth_balance* ETH.
        A balance at or below the threshold means the wallet cannot reliably
        pay for gas and integration tests involving transactions will fail.
        """
        role, cfg = actor_settings
        address = w3.to_checksum_address(cfg["wallet_address"])

        balance_wei = w3.eth.get_balance(address)
        balance_eth = _wei_to_eth(balance_wei)

        log.info(
            "Balance of %s wallet %s: %.6f ETH (minimum required: %.4f ETH)",
            role,
            address,
            balance_eth,
            min_eth_balance,
        )

        assert balance_eth > min_eth_balance, (
            f"{role} wallet {address} has insufficient ETH.\n"
            f"  Balance  : {balance_eth:.6f} ETH\n"
            f"  Required : > {min_eth_balance} ETH\n"
            "Top up the wallet before running integration tests."
        )

        log.info("✓ %s wallet balance sufficient: %.6f ETH", role, balance_eth)


@pytest.mark.wallets
class TestWalletKeyPairs:
    """Verify that the provided private key corresponds to the wallet address."""

    def test_private_key_matches_wallet_address(
        self,
        w3: Web3,
        actor_settings: tuple[str, dict],
    ) -> None:
        """
        Derive the Ethereum address from the private key and compare it to
        the configured walletAddress.  A mismatch means the credentials are
        for different accounts and any signed transaction will be rejected.
        """
        role, cfg = actor_settings
        configured_address = w3.to_checksum_address(cfg["wallet_address"])
        private_key = cfg["private_key"]

        try:
            derived_address = _derive_address_from_key(private_key)
        except Exception as exc:
            pytest.fail(
                f"Could not derive address from {role} private key: {exc}\n"
                "Ensure the key is a valid 32-byte hex string (with or without 0x prefix)."
            )

        log.info(
            "Verifying %s key-pair: configured=%s, derived=%s",
            role,
            configured_address,
            derived_address,
        )

        assert derived_address == configured_address, (
            f"{role} private key does not correspond to the configured wallet address.\n"
            f"  Configured address : {configured_address}\n"
            f"  Derived address    : {derived_address}\n"
            "Check that the correct private key is set in your secrets configuration."
        )

        log.info("✓ %s private key matches wallet address %s", role, configured_address)
