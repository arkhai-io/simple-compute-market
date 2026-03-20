# Seller Agent Deployment

This document covers the deployed seller agent path for the production canary.

## Inputs

- `core/agent/.env.production.sample`
- a dedicated seller env file outside Git
- a seller wallet private key and address
- a ZeroTier-capable runtime host
- access to the registry and provisioning URLs
- an SSH public key for tenant access

## Writable Env Requirement

The deployed agent runtime writes `ZEROTIER_IP`, `BASE_URL_OVERRIDE`, and
`ONCHAIN_AGENT_ID` back into `ENV_FILE` during startup. Do not deploy the seller
with a read-only env mount if `AUTO_REGISTER=true`.

This is a real runtime requirement enforced by `core/entrypoint.sh`.

## Required Env Fields

At minimum, the seller env file must set:

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
- `DEFAULT_VM_HOST`
- `TOKEN_REGISTRY_PATH=/app/core/agent/app/data/token_registry_base_sepolia.json`
- `ENABLE_EVENT_QUEUE=false`

## Deployment Notes

- authenticate Docker on the remote host before the first pull if the image is
  stored in Artifact Registry
- allow inbound `8000/tcp` on the ZeroTier interface
- mount or otherwise persist the writable env file on the host

## Verification

After the container is healthy, verify:

```bash
curl http://<seller-host>:8000/.well-known/agent-card.json
curl http://<seller-host>:8000/.well-known/erc-8004-registration.json
curl http://<seller-host>:8000/resources/portfolio
```

The seller is ready for canary use only after resource seeding is complete and
`/resources/portfolio` reports a matching available resource.
