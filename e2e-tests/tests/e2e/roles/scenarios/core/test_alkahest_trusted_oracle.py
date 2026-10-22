"""Settle an Alkahest escrow through a trusted oracle against compose Anvil.

The oracle-gated release model rests on these SDK calls: an ERC-20 escrow
released by the trusted-oracle arbiter, a fulfillment, a request for
arbitration, the oracle's decision, and collection. No storefront runs here;
the scenario needs only the chain and its baked deployments.
"""
from __future__ import annotations

import time
import uuid

import pytest
from alkahest_py import (
    AlkahestClient,
    ArbitrationMode,
    TrustedOracleArbiterDemandData,
)
from eth_account import Account
from market_alkahest.alkahest import (
    get_alkahest_network,
    resolve_alkahest_address_config,
)
from market_alkahest.dev_chain import anvil_address_book_path

from e2e_harness.settings import settings

pytestmark = pytest.mark.e2e_alkahest_trusted_oracle

_CHAIN_NAME = "anvil"
_ALKAHEST_ADDRESSES_PATH = str(anvil_address_book_path())

# The mock ERC-20 the baked Anvil state deploys (dev-env/generate_state.py) and
# funds the buyer with.
_MOCK_ERC20_A = "0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0"

# Standard Anvil account #0, the oracle here: a deterministic development key
# with ETH in the baked state, never used on any public network. No other
# scenario names it as an oracle, so its arbitration reaches only this deal.
_ANVIL_ORACLE_PRIVATE_KEY = (
    "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
)


def _client(private_key: str) -> AlkahestClient:
    return AlkahestClient(
        private_key=private_key,
        rpc_url=str(settings.BUYER.CHAIN_RPC_URL),
        address_config=resolve_alkahest_address_config(
            get_alkahest_network(_CHAIN_NAME), config_path=_ALKAHEST_ADDRESSES_PATH
        ),
    )


async def test_an_escrow_released_by_a_trusted_oracle_is_collected() -> None:
    buyer = _client(str(settings.BUYER.PRIVATE_KEY))
    seller = _client(str(settings.SELLER.PRIVATE_KEY))
    oracle = _client(_ANVIL_ORACLE_PRIVATE_KEY)
    oracle_address = Account.from_key(_ANVIL_ORACLE_PRIVATE_KEY).address
    address_config = resolve_alkahest_address_config(
        get_alkahest_network(_CHAIN_NAME), config_path=_ALKAHEST_ADDRESSES_PATH
    )

    price = {"address": _MOCK_ERC20_A, "value": 100}
    await buyer.erc20.util.approve(price, "escrow")
    inner_demand = f"trusted oracle scenario {uuid.uuid4()}".encode("utf-8")
    arbiter = {
        "arbiter": address_config.arbiters_addresses.trusted_oracle_arbiter,
        "demand": TrustedOracleArbiterDemandData(
            oracle_address, inner_demand
        ).encode_self(),
    }
    escrow = await buyer.erc20.escrow.default.permit_and_create(
        price, arbiter, int(time.time()) + 3600
    )
    escrow_uid = escrow["log"]["uid"]
    assert escrow_uid

    secret = str(uuid.uuid4())
    fulfillment_uid = await seller.string_obligation.do_obligation(secret, escrow_uid)
    await seller.oracle.request_arbitration(fulfillment_uid, oracle_address, inner_demand)

    decisions = await oracle.oracle.arbitrate_many(
        lambda attestation, demand: True, None, ArbitrationMode.PastUnarbitrated
    )
    assert decisions

    collection_uid = await seller.erc20.escrow.default.collect(
        escrow_uid, fulfillment_uid
    )
    assert collection_uid
