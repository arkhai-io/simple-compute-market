from alkahest_py import EnvTestManager, MockERC20, AlkahestClient
import pprint
import asyncio

def main() -> None:
    env = EnvTestManager()
    pp = pprint.PrettyPrinter()

    mock_erc20 = MockERC20(env.mock_addresses.erc20_a, env.god_wallet_provider)
    mock_erc20.transfer(env.alice, 90000000000)
    mock_erc20.transfer(env.bob, 90000000000)

    port = int(env.rpc_url.split(":")[2].split("/")[0])
    
    print("rpc_url:", env.rpc_url)
    print(f"rpc_port: {port}")
    print("For local development, deploy contracts with:")
    print(f"  ANVIL_RPC_URL=http://localhost:{port} npm run deploy:anvil")

    print("\nEnvTestManager running. Press Enter to shut down...")
    input()


if __name__ == "__main__":
    main()
