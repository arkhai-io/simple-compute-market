from alkahest_py import EnvTestManager, MockERC20, AlkahestClient
import pprint
import asyncio

async def test_approval(client):
    hash = await client.erc20.util.approve(
        {"address": "0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0", "value": 100},
        "escrow",
    )
    return hash

async def test_escrow_creation(client, arbiter):
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

def main() -> None:
    env = EnvTestManager()
    pp = pprint.PrettyPrinter()
    run_tests = False

    mock_erc20 = MockERC20(env.mock_addresses.erc20_a, env.god_wallet_provider)
    mock_erc20.transfer(env.alice, 90000000000)
    mock_erc20.transfer(env.bob, 90000000000)

    port = int(env.rpc_url.split(":")[2].split("/")[0])
    
    print("rpc_url:", env.rpc_url)
    print(f"rpc_port: {port}")
    print("For local development, deploy contracts with:")
    print(f"  ANVIL_RPC_URL=http://localhost:{port} npm run deploy:anvil")

    print("alice:", env.alice)
    print("bob:", env.bob)

    if run_tests:
        print("addresses:")
        pp.pprint(env.addresses)
        print("mock_addresses:")
        pp.pprint(env.mock_addresses)
        pp.pprint(f"Trusted Oracle Arbiter: {env.addresses.arbiters_addresses.trusted_oracle_arbiter}")
        pp.pprint(f"Mock ERC20: {env.mock_addresses.erc20_a}")

        pp.pprint("Testing...")

        pp.pprint(f"bob_client:")
        pp.pprint(f"  escrow approve: {asyncio.run(test_approval(env.bob_client))}")
        pp.pprint(f"  escrow create: {asyncio.run(test_escrow_creation(
            env.bob_client,
            env.addresses.arbiters_addresses.trusted_oracle_arbiter
            ))}")

        client = AlkahestClient(
            private_key="0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d",
            rpc_url=env.rpc_url,
            address_config=env.addresses,
        )
        pp.pprint(f"new_client:")
        pp.pprint(f"  escrow approve: {asyncio.run(test_approval(client))}")
        pp.pprint(f"  escrow create: {asyncio.run(test_escrow_creation(
            client,
            env.addresses.arbiters_addresses.trusted_oracle_arbiter
            ))}")

    print("\nEnvTestManager running. Press Enter to shut down...")
    input()


if __name__ == "__main__":
    main()
