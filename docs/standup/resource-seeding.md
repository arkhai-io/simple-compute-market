# Resource Seeding

This document covers seller inventory preparation for the deployed canary.

## Inputs

- a deployed seller agent
- a CSV describing one quarantined canary resource
- the seller env file at `/etc/simple-market-service/seller-agent.env`
- access to the persisted seller DB path at `/var/lib/market/agent.db`

## Procedure

Run the import from the same host that manages the seller deployment, or from a
context that can read the mounted seller DB path. A working repo-driven path is:

```bash
cd core/agent
make import-resources \
  CSV=app/data/resources.sample.csv \
  ENV_FILE=/etc/simple-market-service/seller-agent.env
```

You can also use the CLI helper against the same deployed seller env file:

```bash
market portfolio import-csv core/agent/app/data/resources.sample.csv \
  --env /etc/simple-market-service/seller-agent.env
```

The imported row must represent one quarantined canary resource and must match
the planned canary request for:

- `gpu_model`
- `region`
- `quantity`
- any seller-policy attributes required for the chosen VM host

## Verification

First resolve the seller's deployed ZeroTier URL from the persisted env file:

```bash
grep '^BASE_URL_OVERRIDE=' /etc/simple-market-service/seller-agent.env
```

Then verify the live portfolio endpoint:

```bash
curl http://<seller-host>:8000/resources/portfolio
```

Do not continue until the seller reports at least one matching available
resource from `/resources/portfolio`.

Once the portfolio is correct, continue with `docs/standup/canary.md`.
