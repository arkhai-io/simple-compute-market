# Buyer Agent Deployment

This document covers the deployed buyer agent path for the production canary.

## Inputs

- `core/agent/.env.production.sample`
- a dedicated buyer env file outside Git
- a buyer wallet private key and address
- a ZeroTier-capable runtime host
- access to the registry and provisioning URLs
- an SSH public key for tenant access

## Writable Env Requirement

The deployed buyer runtime has the same writable `ENV_FILE` requirement as the
seller path. If `AUTO_REGISTER=true`, startup writes `ZEROTIER_IP`,
`BASE_URL_OVERRIDE`, and `ONCHAIN_AGENT_ID` back into the configured env file.

## Required Env Fields

At minimum, the buyer env file must set:

- `BASE_URL_OVERRIDE=http://{ZEROTIER_IP}:8000/`
- `REGISTRY_URL`
- `CHAIN_RPC_URL`
- `CHAIN_NAME=base_sepolia`
- `AGENT_PRIV_KEY`
- `AGENT_WALLET_ADDRESS`
- `SSH_PUBLIC_KEY`
- `ZEROTIER_NETWORK`
- `PROVISIONING_MODE=http`
- `PROVISIONING_SERVICE_URL`
- `TOKEN_REGISTRY_PATH=/app/core/agent/app/data/token_registry_base_sepolia.json`
- `ENABLE_EVENT_QUEUE=false`

The buyer and seller env files must not reuse the same URL, wallet, or
`ONCHAIN_AGENT_ID`.

## Deployment Notes

- authenticate Docker on the remote host before the first pull if the image is
  stored in Artifact Registry
- allow inbound `8000/tcp` on the ZeroTier interface
- keep enough native gas for `approve + escrow.create` if the canary uses `WETH`

## Verification

After the container is healthy, verify:

```bash
curl http://<buyer-host>:8000/.well-known/agent-card.json
curl http://<buyer-host>:8000/.well-known/erc-8004-registration.json
```

The buyer is ready for canary use only after the canonical `eip155:` agent ID
has been captured for the canary runner.
