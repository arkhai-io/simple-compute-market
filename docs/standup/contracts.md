# Contract Address Bootstrap

This document defines the canonical way to supply the shared ERC-8004 contract
bundle for the deployed canary path.

## Inputs

- an authenticated Base Sepolia RPC endpoint
- `erc-8004-contracts/README.md`
- a host-local shared contract bundle at `/etc/simple-market-service/contracts.env`

## Use Published Base Sepolia Registries

The deployed canary path in this repo assumes Base Sepolia (`CHAIN_ID=84532`).
For that network, use the published registry addresses from
`erc-8004-contracts/README.md` unless your environment already manages an
equivalent deployed ERC-8004 stack.

On the current branch, the published Base Sepolia addresses are:

- `IDENTITY_REGISTRY_ADDRESS=0x8004AA63c570c570eBF15376c0dB199918BFe9Fb`
- `REPUTATION_REGISTRY_ADDRESS=0x8004bd8daB57f14Ed299135749a5CB5c42d341BF`
- `VALIDATION_REGISTRY_ADDRESS=0x8004Cb1BF31DAf7788923b405b754f57acEB4272`

If you are not targeting Base Sepolia, stop here and replace the rest of this
document with the equivalent addresses for your environment before you continue
with the stand-up sequence.

## Record The Shared Contract Bundle

Keep the chain and registry addresses in one host-local bundle that the
registry, seller agent, and buyer agent all reference while you prepare their
service-specific env files:

```bash
sudo install -d -m 0755 /etc/simple-market-service
sudo tee /etc/simple-market-service/contracts.env >/dev/null <<'EOF'
CHAIN_ID=84532
RPC_URL=https://<rpc-provider>
IDENTITY_REGISTRY_ADDRESS=0x8004AA63c570c570eBF15376c0dB199918BFe9Fb
REPUTATION_REGISTRY_ADDRESS=0x8004bd8daB57f14Ed299135749a5CB5c42d341BF
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
