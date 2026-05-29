"""External layer: the world an infra provider assumes already exists.

This is the EVM chain with Alkahest contracts and ERC-8004 registry
contracts deployed, and funded accounts. Nothing marketplace-specific
lives here — this is pure blockchain infrastructure.

These tests verify the external world is ready. Later stages depend on
the ``external_world`` fixture, which is only valid if these pass.
"""

from __future__ import annotations

import logging
from decimal import Decimal

import pytest
from web3 import Web3

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fixture: context describing the external world
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def external_world(w3: Web3, rpc_settings, registry_settings, buyer_settings, seller_settings) -> dict:
    """The external world: RPC connection + contract addresses + funded accounts.

    Consumed by all downstream stages. Represents what an infrastructure
    provider (marketplace deployer) assumes already exists before they set
    anything up.
    """
    return {
        "rpc_url": rpc_settings["url"],
        "chain_id": rpc_settings["chain_id"],
        "w3": w3,
        "identity_registry": w3.to_checksum_address(registry_settings["identity_address"]),
        "reputation_registry": w3.to_checksum_address(registry_settings["reputation_address"]),
        "validation_registry": w3.to_checksum_address(registry_settings["validation_address"]),
        "buyer": {
            "private_key": buyer_settings["private_key"],
            "wallet_address": w3.to_checksum_address(buyer_settings["wallet_address"]),
        },
        "seller": {
            "private_key": seller_settings["private_key"],
            "wallet_address": w3.to_checksum_address(seller_settings["wallet_address"]),
        },
    }


# ---------------------------------------------------------------------------
# Tests: verify the external world is real
# ---------------------------------------------------------------------------


@pytest.mark.roles_layer_external
class TestExternalWorld:
    """Verify the external layer exists before any marketplace logic runs."""

    @pytest.mark.contracts
    def test_rpc_reachable_with_expected_chain_id(self, external_world: dict):
        """Anvil (or whatever chain) is reachable and has the right chain ID."""
        w3 = external_world["w3"]
        assert w3.is_connected(), f"RPC {external_world['rpc_url']} is not reachable"
        assert w3.eth.chain_id == external_world["chain_id"], (
            f"Chain ID mismatch: expected {external_world['chain_id']}, "
            f"got {w3.eth.chain_id}"
        )

    @pytest.mark.contracts
    @pytest.mark.parametrize("label", ["identity_registry", "reputation_registry", "validation_registry"])
    def test_erc8004_contract_deployed(self, external_world: dict, label: str):
        """ERC-8004 registry contracts have deployed bytecode."""
        w3 = external_world["w3"]
        code = w3.eth.get_code(external_world[label])
        assert len(code) > 2, f"No contract deployed at {label} ({external_world[label]})"

    @pytest.mark.parametrize("role", ["buyer", "seller"])
    def test_account_has_funds(self, external_world: dict, min_eth_balance: Decimal, role: str):
        """Test accounts have enough ETH to transact."""
        w3 = external_world["w3"]
        addr = external_world[role]["wallet_address"]
        balance_wei = w3.eth.get_balance(addr)
        balance_eth = Decimal(balance_wei) / Decimal(10**18)
        assert balance_eth >= min_eth_balance, (
            f"{role} account {addr} has {balance_eth} ETH, "
            f"needs at least {min_eth_balance}"
        )
