# Registry Deployment

This document covers deployment of the ERC-8004 registry for the production
canary path.

## Inputs

- `erc-8004-registry-py/.env.production.sample`
- a PostgreSQL database for the registry
- an authenticated `RPC_URL`
- verified ERC-8004 contract addresses for the target network
- ZeroTier network settings if the service must join the overlay directly

## Runtime Contract

Use `.env.production.sample` as the source template, not `.env.sample`.

The registry process initializes tables at startup via `init_db()`. The Makefile
still exposes `make migrate` for development and schema maintenance, but the
deployed canary path should treat the runtime env contract as the primary
requirement.

## Deployment Path

For the deployed canary path, use the container deployment documented in
`compute-provisioning-iac/README.md`, not the bare `uvicorn` example in the
service README.

The required env bundle must include at least:

- `DATABASE_URL`
- `CHAIN_ID`
- `RPC_URL`
- `IDENTITY_REGISTRY_ADDRESS`
- `REPUTATION_REGISTRY_ADDRESS`
- `VALIDATION_REGISTRY_ADDRESS`
- `HOST`
- `PORT`
- `ZEROTIER_NETWORK` when joining the overlay directly

## Verification

After deployment, verify:

```bash
curl http://<registry-host>:8080/health
```

and confirm that the URL is reachable from the canary runner over the intended
network path.

Output from this phase:

- `REGISTRY_URL`
