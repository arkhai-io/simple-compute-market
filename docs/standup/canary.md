# Canary Validation

Once the stack is live, continue with:

- [End-to-End Runbook](../e2e-runbook.md)
- [Production Canary Runbook](../production-canary.md)

Use a dedicated deployment namespace for the canary environment. On GCP, that
means a dedicated GCP project or a fresh GCP project for isolated validation.

## Required Inputs

- `REGISTRY_URL`
- `PROVISIONING_SERVICE_URL`
- seller and buyer agent URLs
- canonical seller and buyer `eip155:` agent IDs
- seller and buyer wallet private keys
- one or more candidate `--vm-host` aliases
- optional tenant SSH private key
- optional FRP dashboard URL and password

## Gate Sequence

1. `python scripts/run_deployment_gate_checks.py --skip-smoke-help`
2. `python scripts/validate_deployment_bundle.py ...`
3. live service verification
4. `uv --no-config run python ../scripts/prod_canary_smoke.py ...`

## Success Criteria

- buyer and seller orders are created
- provisioning succeeds
- tenant credentials are returned
- SSH verification succeeds when requested
- both orders close

## Failure Handling

If the canary fails:

1. cancel or clean up the provisioning job
2. close any remaining canary orders
3. reclaim the VM
4. fix the repo or environment issue
5. re-run the repo gates before retrying
