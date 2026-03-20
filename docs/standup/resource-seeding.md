# Resource Seeding

This document covers seller inventory preparation for the deployed canary.

## Inputs

- a deployed seller agent
- a CSV describing one quarantined canary resource
- the seller agent env file or DB path

## Procedure

Use the agent import script or Make target against the deployed seller data path:

```bash
cd core/agent
make import-resources CSV=app/data/resources.sample.csv ENV_FILE=/path/to/seller.env
```

Or use the CLI import helper:

```bash
market portfolio import-csv /path/to/resources.csv --env /path/to/seller.env
```

The imported resource must match the canary request for:

- `gpu_model`
- `region`
- `quantity`
- any host-specific attributes required by the seller policy

## Verification

Check:

```bash
curl http://<seller-host>:8000/resources/portfolio
```

Do not start the canary until the seller reports at least one matching
available resource.
