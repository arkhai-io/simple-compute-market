from __future__ import annotations

from pathlib import Path
import sys

from alkahest_py import EnvTestManager, MockERC20


ROOT = Path(__file__).resolve().parents[4]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from bootstrap_contract import ALKAHEST_ADDRESS_CONFIG_PATH  # type: ignore[import-not-found]
from bootstrap_local_dev import format_local_deploy_command  # type: ignore[import-not-found]

def main() -> None:
    env = EnvTestManager()

    mock_erc20 = MockERC20(env.mock_addresses.erc20_a, env.god_wallet_provider)
    mock_erc20.transfer(env.alice, 90000000000)
    mock_erc20.transfer(env.bob, 90000000000)
    print("rpc_url:", env.rpc_url)
    print("For local development, deploy contracts with:")
    print(f"  {format_local_deploy_command(env.rpc_url)}")
    print("Or using the CLI:")
    print(f"  market dev deploy-contracts --rpc-url {env.rpc_url}")
    print("For the local agent config, set:")
    print(f"  ALKAHEST_ADDRESS_CONFIG_PATH={ROOT / ALKAHEST_ADDRESS_CONFIG_PATH}")

    print("\nEnvTestManager running. Press Enter to shut down...")
    input()


if __name__ == "__main__":
    main()
