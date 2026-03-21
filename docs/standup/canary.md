# Canary Validation

Once the stack is live, continue with:

- [End-to-End Runbook](../e2e-runbook.md)
- [Production Canary Runbook](../production-canary.md)

For the full operator workflow, treat `docs/e2e-runbook.md` as the detailed
execution guide and `docs/production-canary.md` as the live-canary reference.

Use a dedicated deployment namespace for the canary environment. On GCP, that
means a dedicated GCP project or a fresh GCP project for isolated validation.

## Required Inputs

- `/etc/simple-market-service/prod-canary.env`
- `REGISTRY_URL`
- `PROVISIONING_SERVICE_URL`
- seller and buyer agent URLs
- canonical seller and buyer `eip155:` agent IDs
- seller and buyer wallet private keys
- one or more candidate `--vm-host` aliases
- optional tenant SSH private key
- optional FRP dashboard URL and password

## Prerequisites

Before the live run, prepare `/etc/simple-market-service/prod-canary.env` with
the environment-specific defaults you want the runner to use. A typical private
runner bundle includes `CANARY_VM_HOSTS`, optional FRP credentials, and the
target token / region defaults.

Do not start a live canary until the stack already satisfies the deployment
sequence from `docs/standup/overview.md`, including seller resource seeding.

## Gate Sequence

1. `python scripts/run_deployment_gate_checks.py --skip-smoke-help`
2. `python scripts/validate_deployment_bundle.py ...`
3. live service verification
4. `uv --no-config run python ../scripts/prod_canary_smoke.py ...`

## Live Verification

Before any order creation, verify the deployed endpoints from the machine that
will run the canary:

```bash
curl http://<registry-host>:<registry-port>/health
curl http://<provisioning-host>:<provisioning-port>/health
curl http://<seller-host>:<seller-port>/.well-known/agent-card.json
curl http://<seller-host>:<seller-port>/.well-known/erc-8004-registration.json
curl http://<seller-host>:<seller-port>/resources/portfolio
curl http://<buyer-host>:<buyer-port>/.well-known/agent-card.json
curl http://<buyer-host>:<buyer-port>/.well-known/erc-8004-registration.json
```

## Smoke Run

Run the smoke script from the repo with explicit host selection. Use one or more
`--vm-host` flags directly, or set `CANARY_VM_HOSTS` in
`/etc/simple-market-service/prod-canary.env` before launch.

```bash
cd cli
uv --no-config run python ../scripts/prod_canary_smoke.py \
  --registry-url http://<registry-host>:<registry-port> \
  --provisioning-url http://<provisioning-host>:<provisioning-port> \
  --seller-agent-url http://<seller-host>:<seller-port> \
  --buyer-agent-url http://<buyer-host>:<buyer-port> \
  --seller-agent-id eip155:<chain_id>:<identity_registry>:<seller_token_id> \
  --buyer-agent-id eip155:<chain_id>:<identity_registry>:<buyer_token_id> \
  --seller-private-key 0x<seller-private-key> \
  --buyer-private-key 0x<buyer-private-key> \
  --gpu-model <gpu-model> \
  --region "<region>" \
  --token-symbol <token-symbol> \
  --token-amount <token-amount> \
  --vm-host <candidate-host-1> \
  --vm-host <candidate-host-2> \
  --ssh-private-key-path ~/.ssh/id_ed25519
```

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
