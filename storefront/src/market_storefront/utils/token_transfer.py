"""Direct ERC-20 token transfers.

Used by the provider refund endpoint (`POST /orders/refund`). Separate
from `service.clients.alkahest` because refunds bypass the escrow
lifecycle entirely: the provider sends tokens straight from their own
wallet to the buyer to make them whole.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


_ERC20_TRANSFER_ABI: list[dict[str, Any]] = [
    {
        "inputs": [{"type": "address"}, {"type": "uint256"}],
        "name": "transfer",
        "outputs": [{"type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"type": "address"}],
        "name": "balanceOf",
        "outputs": [{"type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]


def _transfer_sync(
    *,
    private_key: str,
    rpc_url: str,
    token_address: str,
    to_address: str,
    amount_raw: int,
    gas: int = 120_000,
    wait_timeout: int = 120,
) -> dict[str, Any]:
    """Sign and submit an ERC-20 transfer; return a result dict.

    Raises RuntimeError on any failure (RPC, signing, reversion). The
    caller is responsible for surfacing a structured HTTP error.
    """
    from web3 import Web3
    from web3.providers import HTTPProvider

    w3 = Web3(HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))
    if not w3.is_connected():
        raise RuntimeError(f"RPC not reachable at {rpc_url}")

    account = w3.eth.account.from_key(private_key)
    token = w3.eth.contract(
        address=Web3.to_checksum_address(token_address),
        abi=_ERC20_TRANSFER_ABI,
    )

    recipient = Web3.to_checksum_address(to_address)
    sender = account.address

    balance = token.functions.balanceOf(sender).call()
    if balance < amount_raw:
        raise RuntimeError(
            f"Insufficient balance: wallet {sender} has {balance} raw units, "
            f"refund needs {amount_raw}"
        )

    tx = token.functions.transfer(recipient, int(amount_raw)).build_transaction({
        "from": sender,
        "nonce": w3.eth.get_transaction_count(sender),
        "gas": gas,
        "gasPrice": w3.eth.gas_price,
        "chainId": w3.eth.chain_id,
    })

    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    tx_hash_hex = tx_hash.hex() if hasattr(tx_hash, "hex") else str(tx_hash)

    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=wait_timeout)
    if receipt.status != 1:
        raise RuntimeError(f"Transfer tx reverted: {tx_hash_hex}")

    return {
        "tx_hash": tx_hash_hex if tx_hash_hex.startswith("0x") else f"0x{tx_hash_hex}",
        "from_address": sender,
        "to_address": recipient,
        "token_address": Web3.to_checksum_address(token_address),
        "amount_raw": int(amount_raw),
        "block_number": int(receipt.blockNumber),
    }


async def transfer_erc20(
    *,
    private_key: str,
    rpc_url: str,
    token_address: str,
    to_address: str,
    amount_raw: int,
) -> dict[str, Any]:
    """Async wrapper around the web3 sync calls (no async web3 needed)."""
    return await asyncio.to_thread(
        _transfer_sync,
        private_key=private_key,
        rpc_url=rpc_url,
        token_address=token_address,
        to_address=to_address,
        amount_raw=amount_raw,
    )
