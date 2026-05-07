"""Minimal ERC-20 query helpers for role tests.

Balance checks are part of user-visible assertions ('my token balance
decreased by what I paid'), so they need real on-chain reads rather
than agent-DB reads.
"""

from __future__ import annotations

from web3 import Web3

# Minimal ERC-20 ABI — balanceOf + decimals are all we need for tests.
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function",
    },
]


def get_erc20_balance(w3: Web3, token_address: str, wallet_address: str) -> int:
    """Return the raw (non-decimal-adjusted) ERC-20 balance of wallet."""
    contract = w3.eth.contract(
        address=w3.to_checksum_address(token_address), abi=ERC20_ABI,
    )
    return int(contract.functions.balanceOf(
        w3.to_checksum_address(wallet_address)
    ).call())
