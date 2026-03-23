# market-contract-deployer

One-shot Docker container that deploys **both Alkahest infrastructure and ERC-8004 contracts**
to a local Anvil chain and writes the resulting contract addresses to a shared-env file
for downstream services to consume.

## What it does

1. **Alkahest replay** — replays 59 pre-signed transactions to deploy the Alkahest
   infrastructure (ERC-20 mock + escrow contracts)
2. **CREATE2 factory** — deploys the SAFE singleton factory at
   `0x914d7Fec6aaC8cd542e72Bca78B30650d45643d7` (required for deterministic addresses)
3. **ERC-8004 vanity contracts** — deploys IdentityRegistry, ReputationRegistry, and
   ValidationRegistry at their `0x8004…` vanity addresses via CREATE2
4. **Upgrades proxies** — upgrades all three proxies from `MinimalUUPS` placeholder to
   full implementations via `anvil_impersonateAccount` (no owner private key needed)
5. **Writes** `$ENV_FILE` with the three contract addresses and exports compiled ABIs

## Usage

### As part of docker compose

`contracts-deploy` is a one-shot init container in `docker-compose.yml`. It runs,
writes `./shared-env/.env`, and exits. The `registry` service waits for it to complete
before starting.

```bash
docker compose up
```

### Standalone (used by build-test-env)

```bash
make build-test-env   # from the feat/local-docker root
```

This spins up a temporary Anvil, runs the deployer against it, dumps the Anvil state
to `test-env/state/state.json`, and builds `arkhai:test-env` from that snapshot.

### Build the image

```bash
make build
# produces: arkhai:contract-deployer
```

## Environment variables

| Variable   | Default               | Description                          |
|------------|-----------------------|--------------------------------------|
| `RPC_URL`  | `http://anvil:8545`   | JSON-RPC endpoint of the Anvil node  |
| `CHAIN_ID` | `31337`               | EVM chain ID                         |
| `ENV_FILE` | (required)            | Path to write the output `.env` file |

## Output (`$ENV_FILE`)

```
IDENTITY_REGISTRY_ADDRESS=0x8004A818BFB912233c491871b3d84c89A494BD9e
REPUTATION_REGISTRY_ADDRESS=0x8004B663056A597Dffe9eCcC1965A193B7388713
VALIDATION_REGISTRY_ADDRESS=0x8004Cb1BF31DAf7788923b405b754f57acEB4272
```

All three addresses are deterministic vanity addresses (CREATE2 with fixed salts on
chain 31337). They are hardcoded in `deploy-local.sh` and will be the same on any
fresh Anvil with the same contracts SHA.

## Files

| File | Description |
|------|-------------|
| `Dockerfile` | Downloads official contracts at pinned SHA, pre-compiles Solidity, overlays local tooling |
| `deploy-local.sh` | Entrypoint: replays Alkahest, deploys CREATE2 factory, deploys vanity contracts, upgrades proxies, exports ABIs, writes ENV_FILE |
| `scripts/upgrade-local.ts` | Upgrades all three ERC-8004 proxies from MinimalUUPS to full implementations via Anvil impersonation |
| `hardhat.config.ts` | Replaces official config; maps `localhost` and `anvil` networks to `$RPC_URL` |
| `custom-chains.ts` | Overlays `scripts/custom-chains.ts`; adds `anvil` chain so `deploy-vanity.ts --network anvil` uses a direct viem HTTP client |
| `deploy_alkahest.py` | Alkahest transaction replay script |
| `alkahest-transactions.json` | Pre-generated Alkahest transaction artifact |
| `Makefile` | `make build` target |

## Updating the upstream contracts

The Dockerfile pins a specific commit of `erc-8004/erc-8004-contracts`:

```dockerfile
ARG ERC_8004_CONTRACTS_SHA=c7ce292f405b692374f8c5ff3febfaececec3a8b
```

To upgrade: verify the new commit, update the `ARG` line, and rebuild.
The `--legacy-peer-deps` flag is needed due to a peer conflict in `@okxweb3/hardhat-explorer-verify`
(block explorer verification plugin — not used locally).

## Compatibility with erc-8004-registry-py

`erc-8004-registry-py` decodes on-chain events using **hardcoded ABIs** in
`src/contracts/abis.py` (comment says "Based on ww-jermaine/erc-8004-contracts").
There is no automated lock — if the deployed contracts change, the ABIs must be
updated manually.

**How to keep them in sync:**

1. When bumping `ERC_8004_CONTRACTS_SHA` in the Dockerfile, check whether any
   event or function signatures in `IdentityRegistryABI`, `ReputationRegistryABI`,
   or `ValidationRegistryABI` changed in the new commit.
2. If they did, update `erc-8004-registry-py/src/contracts/abis.py` to match.
3. The deployed vanity addresses (`0x8004…`) are deterministic and won't change
   unless the CREATE2 salt changes — address compatibility is not a concern.

The registry only uses `IDENTITY_REGISTRY_ADDRESS` at runtime; reputation and
validation addresses are static and match the hardcoded values in the output `.env`.

---

## Why two config overlays?

Hardhat 3's `hre.network.connect()` (no args) uses the **in-process Hardhat EVM**,
not the `defaultNetwork` from config. The two upstream deploy scripts handle networks
differently:

- `deploy-create2-factory.ts` — hardcodes `hre.network.connect("localhost")`
- `deploy-vanity.ts` — checks `customChains[networkName]` first, falls back to
  `hre.network.connect()` if the name isn't found

`hardhat.config.ts` maps `localhost` → `$RPC_URL` so the factory script reaches Anvil.
`custom-chains.ts` adds an `anvil` entry so `deploy-vanity.ts --network anvil` creates
a direct viem HTTP client to Anvil — bypassing Hardhat's in-process EVM entirely.
