#!/bin/bash
set -euo pipefail

mkdir -p /app/shared-env

# Anvil default account #0 — well-known test key, not a secret.
# deploy-vanity.ts --network anvil reads ANVIL_PRIVATE_KEY for the deployer.
export ANVIL_PRIVATE_KEY=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80

# Deterministic vanity addresses (CREATE2 with fixed salts, chain 31337).
# These are constants — same contracts SHA always produces the same addresses.
IDENTITY_ADDR=0x8004A818BFB912233c491871b3d84c89A494BD9e
REPUTATION_ADDR=0x8004B663056A597Dffe9eCcC1965A193B7388713
VALIDATION_ADDR=0x8004Cb1BF31DAf7788923b405b754f57acEB4272

# Check if the CREATE2 factory is already deployed (e.g. test-env pre-baked state).
# If it is, all ERC-8004 contracts are also already deployed — skip re-deployment.
FACTORY=0x914d7Fec6aaC8cd542e72Bca78B30650d45643d7
FACTORY_CODE=$(curl -sf -X POST -H 'Content-Type: application/json' \
  --data "{\"jsonrpc\":\"2.0\",\"method\":\"eth_getCode\",\"params\":[\"${FACTORY}\",\"latest\"],\"id\":1}" \
  "${RPC_URL}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('result','0x'))" 2>/dev/null || echo "0x")

if [ "${FACTORY_CODE}" != "0x" ] && [ -n "${FACTORY_CODE}" ]; then
  echo "Contracts already deployed (pre-baked state detected). Skipping deployment."
else
  echo "Fresh Anvil detected. Running full deployment..."

  # Step 1: Replay Alkahest deployment transactions
  python3 /app/deploy_alkahest.py

  # Step 2: Deploy CREATE2 factory (required for vanity address deployment).
  #          hardhat.config.ts maps both "localhost" and "anvil" to RPC_URL so
  #          deploy-create2-factory.ts's hardcoded connect("localhost") reaches Anvil.
  npx hardhat run scripts/deploy-create2-factory.ts

  # Step 3: Deploy ERC-8004 vanity contracts.
  #          --network anvil triggers the customChains["anvil"] path in deploy-vanity.ts
  #          which creates a direct viem client to RPC_URL, bypassing Hardhat's
  #          in-process EVM (which is what hre.network.connect() uses by default).
  npx hardhat run scripts/deploy-vanity.ts --network anvil
fi

# Step 3b: Upgrade all three ERC-8004 proxies from MinimalUUPS to full implementations.
#           Idempotent: skips already-upgraded proxies.
#           Uses anvil_impersonateAccount — no owner private key needed.
npx hardhat run scripts/upgrade-local.ts --network anvil

# Step 4: Export compiled ABIs to shared-env so downstream services use the
#          exact same interface as what was deployed — no manual ABI sync needed.
SHARED_ENV_DIR=$(dirname "${ENV_FILE}")
for CONTRACT in IdentityRegistryUpgradeable ReputationRegistryUpgradeable ValidationRegistryUpgradeable; do
  ARTIFACT="/app/artifacts/contracts/${CONTRACT}.sol/${CONTRACT}.json"
  if [ -f "${ARTIFACT}" ]; then
    python3 -c "import json,sys; print(json.dumps(json.load(open('${ARTIFACT}'))['abi'], indent=2))" \
      > "${SHARED_ENV_DIR}/${CONTRACT}.abi.json"
    echo "Exported ABI: ${SHARED_ENV_DIR}/${CONTRACT}.abi.json"
  fi
done

# Step 5: Write contract addresses to shared-env for downstream services
{
  echo "IDENTITY_REGISTRY_ADDRESS=${IDENTITY_ADDR}"
  echo "REPUTATION_REGISTRY_ADDRESS=${REPUTATION_ADDR}"
  echo "VALIDATION_REGISTRY_ADDRESS=${VALIDATION_ADDR}"
} > "${ENV_FILE}"
echo "Wrote contract addresses to ${ENV_FILE}"
cat "${ENV_FILE}"

# Step 6: Register a sentinel agent on-chain so the registry smoke test
# (test_at_least_one_agent_registered) passes against a fresh test-env.
# Uses Anvil account #3 — not used by any market agent (buyer/seller use
# accounts #1/#2, deployer uses #0).  The registry service discovers this
# agent automatically via sync_from_start() replaying the Registered event.
IDENTITY_REGISTRY_ADDRESS=${IDENTITY_ADDR} python3 /app/seed_agent.py
