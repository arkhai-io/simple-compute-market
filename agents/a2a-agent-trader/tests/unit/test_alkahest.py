from alkahest_py import EnvTestManager, MockERC20, AlkahestClient
import pprint
import asyncio

async def approve_escrow(client):
    hash = await client.erc20.util.approve(
        {"address": "0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0", "value": 100},
        "escrow",
    )
    return hash

async def create_escrow(client, arbiter):
    price = {"address": "0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0", "value": 100}
    
    arbiter = {
        "arbiter": arbiter,
        "demand": b""
    }
    
    expiration = 0
    hash = await client.erc20.escrow.non_tierable.permit_and_create(
        price, arbiter, expiration
    )
    return hash

def test_escrow_approval_and_creation():
    env = EnvTestManager()

    mock_erc20 = MockERC20(env.mock_addresses.erc20_a, env.god_wallet_provider)
    mock_erc20.transfer(env.alice, 90000000000)
    mock_erc20.transfer(env.bob, 90000000000)

    alice_rs_client = env.alice_client
    bob_rs_client = env.bob_client

    rs_escrow_approve = asyncio.run(approve_escrow(alice_rs_client))
    rs_escrow_create = asyncio.run(create_escrow(
        alice_rs_client,
        env.addresses.arbiters_addresses.trusted_oracle_arbiter
        ))
    
    assert rs_escrow_approve
    assert rs_escrow_create

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

    py_escrow_approve = asyncio.run(approve_escrow(alice_py_client))
    py_escrow_create = asyncio.run(create_escrow(
        alice_py_client,
        env.addresses.arbiters_addresses.trusted_oracle_arbiter
        ))

    assert py_escrow_approve
    assert py_escrow_create