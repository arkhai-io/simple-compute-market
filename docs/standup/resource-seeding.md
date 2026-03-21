# Resource Seeding

This document covers seller inventory preparation for the deployed canary.

## Inputs

- a deployed seller agent
- a CSV describing one quarantined canary resource
- the deployed seller env file at `/etc/simple-market-service/seller-agent.env`
- the deployed seller DB path at `/var/lib/market/agent.db`

## Procedure

Use the agent import script or Make target against the deployed seller data path.
The simplest path is to target the same host-local env file the seller container
uses:

```bash
cd core/agent
make import-resources \
  CSV=app/data/resources.sample.csv \
  ENV_FILE=/etc/simple-market-service/seller-agent.env
```

To import a real canary inventory file instead of the bundled sample, point the
same command at your seller CSV:

```bash
cd core/agent
make import-resources \
  CSV=/path/to/quarantined-canary-resource.csv \
  ENV_FILE=/etc/simple-market-service/seller-agent.env
```

Or use the CLI import helper against the same deployed env file:

```bash
market portfolio import-csv \
  /path/to/quarantined-canary-resource.csv \
  --env /etc/simple-market-service/seller-agent.env
```

The imported resource must match the canary request for:

- `gpu_model`
- `region`
- `quantity`
- any host-specific attributes required by the seller policy

## Verification

Resolve the deployed seller URL from the persisted env file, then verify the
seller portfolio:

```bash
grep '^BASE_URL_OVERRIDE=' /etc/simple-market-service/seller-agent.env
curl http://<seller-host>:<seller-port>/resources/portfolio
```

Do not start the canary until the seller reports at least one matching
available resource.

Once the seller portfolio is correct, continue with `docs/standup/canary.md`.
