# Canary Validation

Once the stack is live, continue with `docs/e2e-runbook.md` and
`docs/production-canary.md`. This page is the short stand-up handoff that
collects the deployed prerequisites before the live smoke run.

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
- a runner env file at `/etc/simple-market-service/prod-canary.env`

## Prerequisites

Keep the runner-only defaults outside Git in
`/etc/simple-market-service/prod-canary.env`. A practical place for optional
defaults is:

- `SELLER_AGENT_URL=http://<seller-host>:<seller-port>`
- `BUYER_AGENT_URL=http://<buyer-host>:<buyer-port>`
- `SELLER_AGENT_ID=eip155:<chain_id>:<identity_registry>:<seller_token_id>`
- `BUYER_AGENT_ID=eip155:<chain_id>:<identity_registry>:<buyer_token_id>`
- `SELLER_PRIVATE_KEY=0x<seller-private-key>`
- `BUYER_PRIVATE_KEY=0x<buyer-private-key>`
- `SSH_PRIVATE_KEY_PATH=~/.ssh/id_ed25519`
- `CANARY_VM_HOSTS=ww1`
- `FRP_DASHBOARD_URL=http://<frp-host>:7500`
- `FRP_DASHBOARD_PASSWORD=<password>`
- `CANARY_GPU_MODEL=<gpu-model>`
- `CANARY_REGION=<region>`
- `CANARY_TOKEN_SYMBOL=<token-symbol>`
- `CANARY_TOKEN_AMOUNT=<token-amount>`
- `CANARY_GPU_QUANTITY=1`
- `CANARY_DURATION_HOURS=1`
- `CANARY_MATCH_SALT=<fixed-integer-when-repeatability-matters>`

Before creating orders, confirm that:

- the seller inventory was seeded via `docs/standup/resource-seeding.md`
- the registry, provisioning service, seller, and buyer are reachable from the
  runner host
- the selected `--vm-host` aliases or `CANARY_VM_HOSTS` values exist in
  `compute-provisioning-iac/ansible/inventory/hosts`

## Gate Sequence

Source the runner env before executing the live checks and smoke run:

```bash
set -a
. /etc/simple-market-service/prod-canary.env
set +a
```

Run the repo-only readiness gates first:

```bash
python scripts/run_deployment_gate_checks.py --skip-smoke-help
```

Then validate the deployed bundle before a live run:

```bash
python scripts/validate_deployment_bundle.py \
  --environment <environment> \
  --seller-agent-env /etc/simple-market-service/seller-agent.env \
  --buyer-agent-env /etc/simple-market-service/buyer-agent.env \
  --provisioning-env /etc/simple-market-service/provisioning.env \
  --registry-env /etc/simple-market-service/registry.env \
  --seller-agent-url http://<seller-host>:<seller-port> \
  --buyer-agent-url http://<buyer-host>:<buyer-port> \
  --seller-agent-id eip155:<chain_id>:<identity_registry>:<seller_token_id> \
  --buyer-agent-id eip155:<chain_id>:<identity_registry>:<buyer_token_id> \
  --seller-private-key 0x<seller-private-key> \
  --buyer-private-key 0x<buyer-private-key> \
  --ssh-private-key-path ~/.ssh/id_ed25519
```

## Automated Runner

If a self-hosted GitHub runner already sits inside the isolated environment,
you can trigger `.github/workflows/deployed-canary.yml` with
`workflow_dispatch` instead of running the smoke commands manually.

That runner contract is intentionally narrow:

- it expects host-local env files such as `/etc/simple-market-service/prod-canary.env`
- it refuses shared production style targets and requires an explicit isolated environment acknowledgement
- it runs `scripts/run_deployment_gate_checks.py` before the live smoke path when enabled
- it runs `scripts/prod_canary_smoke.py` from the repo checkout
- it runs `scripts/run_release_gate_checks.py` after the canary succeeds, using the captured `prod-canary.log` as proof
- if the canary fails, it attempts `scripts/prod_canary_rollback.py` against the captured canary log before surfacing the failure

Use that workflow only for an isolated environment with the same host-local env
bundle contract documented in this runbook.

## Live Verification

Verify the deployed services from the same machine that will run the canary:

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

Run the live smoke test from the repo with the CLI environment:

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
  --quantity <quantity> \
  --duration-hours <duration-hours> \
  --match-salt <match-salt> \
  --vm-host <candidate-host> \
  --ssh-private-key-path ~/.ssh/id_ed25519
```

If `/etc/simple-market-service/prod-canary.env` sets `CANARY_VM_HOSTS`, the
runner can preflight multiple candidate hosts before orders are created.
Repeated `--vm-host` flags override `CANARY_VM_HOSTS` from the sourced runner env file. `--frp-dashboard-url` and `--frp-dashboard-password` must be provided together when FRP proxy-registration verification is enabled.

## Success Criteria

- buyer and seller orders are created
- provisioning succeeds
- tenant credentials are returned
- SSH verification succeeds when requested
- both orders close

## Failure Handling

If the canary fails:

1. preserve the exact runner output, provisioning job ID, and canary order IDs
2. follow the exact rollback procedure in [Production Canary Rollback](../production-canary.md#rollback)
3. fix the repo or environment issue
4. re-run the repo gates before retrying
