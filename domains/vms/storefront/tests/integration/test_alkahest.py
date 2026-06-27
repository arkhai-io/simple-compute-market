import asyncio
import uuid

import pytest
from alkahest_py import (
    AlkahestClient,
    ArbitrationMode,
    EnvTestManager,
    MockERC20,
    TrustedOracleArbiterDemandData,
)


MOCK_TOKEN_ADDR = "0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0"


_ENV_TEST_MANAGER_SETUP = """\
EnvTestManager could not start the local Alkahest test chain runtime.

This integration test requires host Node.js, Rust/Cargo, and Foundry/Anvil.
On Ubuntu, install the prerequisites with:

  sudo apt-get update
  sudo apt-get install -y nodejs npm curl build-essential pkg-config libssl-dev
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
  . "$HOME/.cargo/env"
  curl -L https://foundry.paradigm.xyz | bash
  export PATH="$HOME/.foundry/bin:$PATH"
  foundryup -i v1.5.1

Then rerun:

  cd domains/vms/storefront && make test-integration
"""


def env_test_manager():
    try:
        return EnvTestManager()
    except RuntimeError as exc:
        pytest.fail(f"{_ENV_TEST_MANAGER_SETUP}\nOriginal error: {exc}", pytrace=False)


async def approve_escrow(client):
    tx_hash = await client.erc20.util.approve(
        {"address": MOCK_TOKEN_ADDR, "value": 100},
        "escrow",
    )
    return tx_hash


async def create_escrow(client, arbiter, demand=b"", expiration=0):
    price = {"address": MOCK_TOKEN_ADDR, "value": 100}
    tx_hash = await client.erc20.escrow.default.permit_and_create(
        price, arbiter, expiration
    )
    return tx_hash


async def full_arbitration_flow(
    arbiter_address,
    seller_client,
    buyer_client,
    oracle_address,
):
    await approve_escrow(buyer_client)

    secret_code = f"{uuid.uuid4()}"
    inner_demand_data = f"test arbitration data {secret_code}".encode("utf-8")

    demand_data = TrustedOracleArbiterDemandData(oracle_address, inner_demand_data)
    arbiter = {
        "arbiter": arbiter_address,
        "demand": demand_data.encode_self(),
    }

    escrow_receipt = await create_escrow(
        buyer_client,
        arbiter=arbiter,
        expiration=0,
    )
    escrow_uid = escrow_receipt["log"]["uid"]
    assert escrow_uid is not None

    fulfillment_uid = await seller_client.string_obligation.do_obligation(
        secret_code, escrow_uid
    )

    await seller_client.oracle.request_arbitration(
        fulfillment_uid, oracle_address, inner_demand_data
    )

    def decision_function(attestation, demand):
        return True

    decisions = await buyer_client.oracle.arbitrate_many(
        decision_function, None, ArbitrationMode.PastUnarbitrated
    )
    assert len(decisions) > 0

    escrow_collection_uid = await seller_client.erc20.escrow.default.collect(
        escrow_uid, fulfillment_uid
    )

    assert escrow_uid is not None
    assert escrow_collection_uid is not None

    return escrow_collection_uid


def test_rust():
    env = env_test_manager()

    mock_erc20 = MockERC20(env.mock_addresses.erc20_a, env.god_wallet_provider)
    mock_erc20.transfer(env.alice, 90000000000)
    mock_erc20.transfer(env.bob, 90000000000)

    alice_client = AlkahestClient(
        private_key=env.alice_private_key,
        rpc_url=env.rpc_url,
        address_config=env.addresses,
    )
    bob_client = AlkahestClient(
        private_key=env.bob_private_key,
        rpc_url=env.rpc_url,
        address_config=env.addresses,
    )

    arbitration_flow = asyncio.run(full_arbitration_flow(
        arbiter_address=env.addresses.arbiters_addresses.trusted_oracle_arbiter,
        seller_client=alice_client,
        buyer_client=bob_client,
        oracle_address=env.bob,
    ))

    assert arbitration_flow is not None


def test_python():
    env = env_test_manager()

    mock_erc20 = MockERC20(env.mock_addresses.erc20_a, env.god_wallet_provider)
    mock_erc20.transfer(env.alice, 90000000000)
    mock_erc20.transfer(env.bob, 90000000000)

    # alkahest-py >= 0.4.0 generates fresh random wallets for env.alice /
    # env.bob per setup_test_environment call (so the suite can share one
    # anvil + contract deploy across tests via evm_revert). Use the
    # corresponding *_private_key fields instead of the legacy hardcoded
    # anvil-dev keys; those derive deterministic addresses that do not
    # match the random env.alice / env.bob the MOCK transfers funded.
    alice_py_client = AlkahestClient(
        private_key=env.alice_private_key,
        rpc_url=env.rpc_url,
        address_config=env.addresses,
    )

    bob_py_client = AlkahestClient(
        private_key=env.bob_private_key,
        rpc_url=env.rpc_url,
        address_config=env.addresses,
    )

    assert alice_py_client
    assert bob_py_client

    arbitration_flow = asyncio.run(full_arbitration_flow(
        arbiter_address=env.addresses.arbiters_addresses.trusted_oracle_arbiter,
        seller_client=alice_py_client,
        buyer_client=bob_py_client,
        oracle_address=env.bob,
    ))

    assert arbitration_flow is not None
