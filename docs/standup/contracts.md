# Contract Address Bootstrap

This document defines the canonical way to supply the shared ERC-8004 contract
bundle for the deployed canary path.

## Inputs

- an authenticated Ethereum Sepolia RPC endpoint
- `erc-8004-contracts/README.md`
- a host-local shared contract bundle at `/etc/simple-market-service/contracts.env`

## Use Published Ethereum Sepolia Registries

The deployed canary path in this repo assumes Ethereum Sepolia
(`CHAIN_ID=11155111`). For that network, use the published registry addresses from
`erc-8004-contracts/README.md` unless your environment already manages an
equivalent deployed ERC-8004 stack.

On the current branch, the documented Ethereum Sepolia addresses are:

- `IDENTITY_REGISTRY_ADDRESS=0x8004A818BFB912233c491871b3d84c89A494BD9e`
- `REPUTATION_REGISTRY_ADDRESS=0x8004B663056A597Dffe9eCcC1965A193B7388713`
- `VALIDATION_REGISTRY_ADDRESS=0x8004Cb1BF31DAf7788923b405b754f57acEB4272`

If you are not targeting Ethereum Sepolia, stop here and replace the rest of this
document with the equivalent addresses for your environment before you continue
with the stand-up sequence.

Use `ETH_SEPOLIA_HTTP_RPC_URL` from your local shared secrets as the source for
the runtime `RPC_URL` value in the shared contract bundle.

## Record The Shared Contract Bundle

Keep the chain and registry addresses in one host-local bundle that the
registry, seller agent, and buyer agent all reference while you prepare their
service-specific env files:

```bash
sudo install -d -m 0755 /etc/simple-market-service
sudo tee /etc/simple-market-service/contracts.env >/dev/null <<'EOF'
CHAIN_ID=11155111
RPC_URL=https://<eth-sepolia-rpc-provider>
IDENTITY_REGISTRY_ADDRESS=0x8004A818BFB912233c491871b3d84c89A494BD9e
REPUTATION_REGISTRY_ADDRESS=0x8004B663056A597Dffe9eCcC1965A193B7388713
VALIDATION_REGISTRY_ADDRESS=0x8004Cb1BF31DAf7788923b405b754f57acEB4272
EOF
```

When you edit `/etc/simple-market-service/registry.env`,
`/etc/simple-market-service/seller-agent.env`, and
`/etc/simple-market-service/buyer-agent.env`, copy the same `CHAIN_ID`,
`RPC_URL`, and registry addresses from `/etc/simple-market-service/contracts.env`
into each service bundle.

## Verification

Source the shared bundle and confirm that each published address has code on the
target RPC endpoint:

```bash
set -a
. /etc/simple-market-service/contracts.env
set +a

curl -s "${RPC_URL}" \
  -H 'Content-Type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"${IDENTITY_REGISTRY_ADDRESS}\",\"latest\"]}"

curl -s "${RPC_URL}" \
  -H 'Content-Type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"${REPUTATION_REGISTRY_ADDRESS}\",\"latest\"]}"

curl -s "${RPC_URL}" \
  -H 'Content-Type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"${VALIDATION_REGISTRY_ADDRESS}\",\"latest\"]}"
```

Each response should return a non-`0x` `result`.

## Outputs

- `/etc/simple-market-service/contracts.env`
- one verified `CHAIN_ID`
- one verified `RPC_URL`
- verified `IDENTITY_REGISTRY_ADDRESS`
- verified `REPUTATION_REGISTRY_ADDRESS`
- verified `VALIDATION_REGISTRY_ADDRESS`
