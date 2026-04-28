"""
Test suite: validate on-chain contract state.

Tests
-----
For each registry address (identity, reputation, validation) verify that:
	1. There is deployed bytecode at the address (i.e. it IS a contract).
	2. The contract exposes an owner() function whose return value equals
		the configured ownerAddress.
"""

from __future__ import annotations

import logging

import pytest
from web3 import Web3

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_bytecode(w3: Web3, address: str) -> bytes:
    """Return the deployed bytecode at *address* (empty bytes if EOA)."""
    checksummed = w3.to_checksum_address(address)
    return w3.eth.get_code(checksummed)


def _has_contract(w3: Web3, address: str) -> bool:
    """Return True iff there is non-trivial bytecode at *address*."""
    code = _get_bytecode(w3, address)
    # `0x` or empty bytes → EOA / non-existent
    return len(code) > 2


def _get_owner(ownable_contract_factory, address: str) -> str:
    """Call owner() on an Ownable contract and return the result address."""
    contract = ownable_contract_factory(address)
    return contract.functions.owner().call()


# ---------------------------------------------------------------------------
# Fixtures scoped to this module
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def registry(registry_settings):
    """Validated registry config dict."""
    reg = registry_settings
    for key in ("identity_address", "reputation_address", "validation_address", "owner_address"):
        if not reg.get(key):
            pytest.fail(
                f"registry.{key} is not configured. "
                "Set it in config.yml, a profile file, or via ARKHAI_REGISTRY__{key.upper()}."
            )
    return reg


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.contracts
class TestRegistryContracts:
    """Verify each registry contract is deployed and has the expected owner."""

    @pytest.mark.parametrize(
        "contract_label, address_key",
        [
            ("identity",   "identity_address"),
            ("reputation", "reputation_address"),
            ("validation", "validation_address"),
        ],
    )
    def test_contract_exists(
        self,
        w3: Web3,
        registry: dict,
        contract_label: str,
        address_key: str,
    ) -> None:
        """
        Verify that bytecode exists at the configured registry address.
        A zero-length code response indicates an EOA (not a contract) or that
        nothing has been deployed to that address.
        """
        address = registry[address_key]
        checksummed = w3.to_checksum_address(address)

        log.info("Checking bytecode at %s contract: %s", contract_label, checksummed)

        assert _has_contract(w3, address), (
            f"No contract deployed at registry.{contract_label} address {checksummed}. "
            "The address is either an EOA, empty, or the wrong network."
        )

        log.info("✓ Contract exists at %s (%s)", contract_label, checksummed)

    @pytest.mark.parametrize(
        "contract_label, address_key",
        [
            ("identity",   "identity_address"),
            ("reputation", "reputation_address"),
            ("validation", "validation_address"),
        ],
    )
    def test_contract_owner(
        self,
        w3: Web3,
        registry: dict,
        ownable_contract,
        contract_label: str,
        address_key: str,
    ) -> None:
        """
        Verify that owner() on each registry contract returns ownerAddress.

        Requires the contract to implement the ERC-173 / Ownable interface.
        If the contract does not expose owner(), web3 will raise a
        ContractLogicError — which will surface as a test failure with a
        clear message.
        """
        contract_address = registry[address_key]
        expected_owner = w3.to_checksum_address(registry["owner_address"])

        log.info(
            "Checking owner of %s contract (%s) == %s",
            contract_label,
            contract_address,
            expected_owner,
        )

        try:
            actual_owner = _get_owner(ownable_contract, contract_address)
        except Exception as exc:
            pytest.fail(
                f"Failed to call owner() on {contract_label} contract at "
                f"{contract_address}: {exc}"
            )

        actual_owner_checksummed = w3.to_checksum_address(actual_owner)

        assert actual_owner_checksummed == expected_owner, (
            f"Owner mismatch for {contract_label} contract at {contract_address}.\n"
            f"  Expected : {expected_owner}\n"
            f"  Actual   : {actual_owner_checksummed}"
        )

        log.info(
            "✓ %s contract owner is correct: %s", contract_label, actual_owner_checksummed
        )
