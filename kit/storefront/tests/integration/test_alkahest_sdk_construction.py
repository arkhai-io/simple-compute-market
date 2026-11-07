"""What constructing the Alkahest SDK client does with its RPC.

The client constructor's docstring states it, and the chain probe's rebuilding
of a missing client depends on it: a client over an HTTP ``rpc_url`` is built
without contacting the RPC, so an unreachable chain still has a client, while a
websocket ``rpc_url`` is connected at construction, so its client cannot be
built until the chain answers. Port 9 on the loopback interface refuses every
connection. The key is Anvil account 0's published development key, never for
a public network.
"""

from __future__ import annotations

import pytest
from alkahest_py import AlkahestClient
from market_alkahest.alkahest import resolve_alkahest_address_config
from market_alkahest.dev_chain import anvil_address_book_path

DEV_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
REFUSED = "127.0.0.1:9"


def _address_config():
    return resolve_alkahest_address_config(
        "anvil", config_path=str(anvil_address_book_path())
    )


def test_an_http_client_is_built_without_contacting_its_rpc() -> None:
    AlkahestClient(
        private_key=DEV_KEY,
        rpc_url=f"http://{REFUSED}",
        address_config=_address_config(),
    )


def test_a_websocket_client_connects_at_construction() -> None:
    with pytest.raises(RuntimeError, match="Connection refused"):
        AlkahestClient(
            private_key=DEV_KEY,
            rpc_url=f"ws://{REFUSED}",
            address_config=_address_config(),
        )
