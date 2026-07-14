"""Unit tests for the ERC-20 direct-transfer helper.

The helper is a thin wrapper around web3.py — we mock the chain client and
verify the wire shape: balance check, nonce/gas/chainId fields on the built
tx, signing, broadcast, and receipt status handling.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from market_storefront.utils.token_transfer import _transfer_sync


_PRIV_KEY = "0x" + "11" * 32
_RPC = "http://rpc.invalid"
_TOKEN = "0xaAaaAaAaAaAaAaaAaAAAAaAaAaaaAAaAaaAaAaAa"
_RECIP = "0xbBbBbbBBbBBbbBBbbbbBbbBBBBbbBBbbBBBbBbBb"


def _fake_web3_modules(*, balance: int, status: int, tx_hash_bytes: bytes = b"\xab" * 32):
    """Return patches for web3.Web3 and web3.providers.HTTPProvider."""
    account_obj = MagicMock()
    account_obj.address = "0x" + "cc" * 20
    signed_tx = MagicMock()
    signed_tx.raw_transaction = b"\x99" * 10
    account_obj.sign_transaction.return_value = signed_tx

    w3 = MagicMock()
    w3.is_connected.return_value = True
    w3.eth.account.from_key.return_value = account_obj
    w3.eth.get_transaction_count.return_value = 7
    w3.eth.gas_price = 1_000_000_000
    w3.eth.chain_id = 31337
    w3.eth.send_raw_transaction.return_value = tx_hash_bytes

    receipt = MagicMock()
    receipt.status = status
    receipt.blockNumber = 123
    w3.eth.wait_for_transaction_receipt.return_value = receipt

    contract = MagicMock()
    w3.eth.contract.return_value = contract

    balance_call = MagicMock()
    balance_call.call.return_value = balance
    contract.functions.balanceOf.return_value = balance_call

    transfer_call = MagicMock()
    transfer_call.build_transaction.return_value = {"stub": "tx"}
    contract.functions.transfer.return_value = transfer_call

    w3_class = MagicMock()
    w3_class.return_value = w3
    w3_class.to_checksum_address = lambda addr: addr

    return w3_class, contract, account_obj, balance_call, transfer_call


def test_transfer_success_returns_tx_hash():
    w3_class, contract, account_obj, balance_call, transfer_call = _fake_web3_modules(
        balance=10**20, status=1,
    )
    with patch("web3.Web3", w3_class), patch("web3.providers.HTTPProvider", MagicMock()):
        result = _transfer_sync(
            private_key=_PRIV_KEY,
            rpc_url=_RPC,
            token_address=_TOKEN,
            to_address=_RECIP,
            amount_raw=10**18,
        )

    # Balance was checked
    balance_call.call.assert_called_once()
    # Transfer was built with the right recipient + amount
    contract.functions.transfer.assert_called_once_with(_RECIP, 10**18)
    # Tx hash normalized to hex with 0x prefix
    assert result["tx_hash"].startswith("0x")
    assert result["to_address"] == _RECIP
    assert result["amount_raw"] == 10**18
    assert result["block_number"] == 123


def test_transfer_insufficient_balance_raises():
    w3_class, *_ = _fake_web3_modules(balance=10, status=1)
    with patch("web3.Web3", w3_class), patch("web3.providers.HTTPProvider", MagicMock()):
        with pytest.raises(RuntimeError, match="Insufficient balance"):
            _transfer_sync(
                private_key=_PRIV_KEY,
                rpc_url=_RPC,
                token_address=_TOKEN,
                to_address=_RECIP,
                amount_raw=10**18,
            )


def test_transfer_reverted_status_raises():
    w3_class, *_ = _fake_web3_modules(balance=10**20, status=0)
    with patch("web3.Web3", w3_class), patch("web3.providers.HTTPProvider", MagicMock()):
        with pytest.raises(RuntimeError, match="reverted"):
            _transfer_sync(
                private_key=_PRIV_KEY,
                rpc_url=_RPC,
                token_address=_TOKEN,
                to_address=_RECIP,
                amount_raw=10**18,
            )


def test_transfer_rpc_unreachable_raises():
    w3 = MagicMock()
    w3.is_connected.return_value = False
    w3_class = MagicMock(return_value=w3)
    with patch("web3.Web3", w3_class), patch("web3.providers.HTTPProvider", MagicMock()):
        with pytest.raises(RuntimeError, match="RPC not reachable"):
            _transfer_sync(
                private_key=_PRIV_KEY,
                rpc_url=_RPC,
                token_address=_TOKEN,
                to_address=_RECIP,
                amount_raw=10**18,
            )
