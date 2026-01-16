from alkahest_py import (
    EnvTestManager,
    MockERC20,
    AlkahestClient,
    TrustedOracleArbiterDemandData,
    ArbitrationMode,
)
import pprint
import uuid
import asyncio

MOCK_TOKEN_ADDR = "0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0"

async def approve_escrow(client):
    hash = await client.erc20.util.approve(
        {"address": MOCK_TOKEN_ADDR, "value": 100},
        "escrow",
    )
    return hash

async def create_escrow(client, arbiter, demand=b"", expiration=0):
    price = {"address": MOCK_TOKEN_ADDR, "value": 100}
    hash = await client.erc20.escrow.non_tierable.permit_and_create(
        price, arbiter, expiration
    )
    return hash

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
    expiration = 0

    escrow_receipt = await create_escrow(
        buyer_client,
        arbiter=arbiter,
        expiration=expiration
    )
    escrow_uid = escrow_receipt['log']['uid']
    assert escrow_uid is not None

    fulfillment_uid = await seller_client.string_obligation.do_obligation(secret_code, escrow_uid)
    
    await seller_client.oracle.request_arbitration(fulfillment_uid, oracle_address, inner_demand_data)

    def decision_function(attestation, demand):
        # print("Arbitration requested with attestation:", attestation)
        # print("Demand data:", demand)
        return True

    decisions = await buyer_client.oracle.arbitrate_many(decision_function, None, ArbitrationMode.PastUnarbitrated)

    assert len(decisions) > 0
    
    escrow_collection_uid = await seller_client.erc20.escrow.non_tierable.collect(escrow_uid, fulfillment_uid)

    assert escrow_uid is not None
    assert escrow_collection_uid is not None

    return escrow_collection_uid

# def test_rust():
#     env = EnvTestManager()

#     mock_erc20 = MockERC20(env.mock_addresses.erc20_a, env.god_wallet_provider)
#     mock_erc20.transfer(env.alice, 90000000000)
#     mock_erc20.transfer(env.bob, 90000000000)

# def test_python():
#     env = EnvTestManager()

#     mock_erc20 = MockERC20(env.mock_addresses.erc20_a, env.god_wallet_provider)
#     mock_erc20.transfer(env.alice, 90000000000)
#     mock_erc20.transfer(env.bob, 90000000000)

def test_escrow_approval_and_creation():
    env = EnvTestManager()

    mock_erc20 = MockERC20(env.mock_addresses.erc20_a, env.god_wallet_provider)
    mock_erc20.transfer(env.alice, 90000000000)
    mock_erc20.transfer(env.bob, 90000000000)

    alice_rs_client = env.alice_client
    bob_rs_client = env.bob_client

    rs_escrow_approve = asyncio.run(approve_escrow(alice_rs_client))

    assert rs_escrow_approve

    alice_py_client = AlkahestClient(
        private_key="0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d",
        rpc_url=env.rpc_url,
        address_config=env.addresses,
    )

    bob_py_client = AlkahestClient(
        private_key="0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a",
        rpc_url=env.rpc_url,
        address_config=env.addresses,
    )

    assert alice_py_client
    assert bob_py_client

    arbitration_flow = asyncio.run(full_arbitration_flow(
        arbiter_address = env.addresses.arbiters_addresses.trusted_oracle_arbiter,
        seller_client = alice_py_client,
        buyer_client = bob_py_client,
        oracle_address = env.bob
    ))

    assert arbitration_flow is not None
