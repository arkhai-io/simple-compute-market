# End-to-End Runbook

This document describes how to validate, run, and evaluate a full-stack canary
without assuming that the runner is the original deployer or repository owner.
It assumes only that the runner can access the repo, the target environment,
and the required secrets for that environment.

This runbook covers the real deployed path:

- real ZeroTier networking
- real ERC-8004 registry
- real async provisioning API and worker
- real FRP routing
- real seller inventory
- no `mock` provisioning

See also:

- `docs/standup/overview.md`
- `docs/deployment-input-checklist.md`
- `docs/e2e-deployment-test-plan.md`
- `docs/production-canary.md`

## Required Access

The runner needs access to:

- a local repo checkout with `python`, `uv`, `curl`, and an SSH client
- the target deployment network and service URLs
- seller and buyer agent env bundles
- provisioning and registry env bundles
- seller and buyer canary wallet private keys
- seller and buyer on-chain agent IDs
- a tenant SSH private key if SSH verification is required
- at least one candidate VM host alias from `compute-provisioning-iac/ansible/inventory/hosts`
- optional FRP dashboard URL and password if proxy-registration verification is required

Use a dedicated deployment namespace for the first full-stack run. On GCP, that
means a dedicated GCP project rather than a shared project.

## Recommended Private File Layout

Keep deployment-specific bundles outside Git:

- seller agent env: `/etc/simple-market-service/seller-agent.env`
- buyer agent env: `/etc/simple-market-service/buyer-agent.env`
- provisioning env: `/etc/simple-market-service/provisioning.env`
- registry env: `/etc/simple-market-service/registry.env`
- canary runner env: `/etc/simple-market-service/prod-canary.env`
- provisioning secrets: `/etc/simple-market-service/management-vars.yaml`

## 1. Repo Readiness Gates

Run the repo-only gates first:

```bash
python scripts/run_deployment_gate_checks.py --skip-smoke-help
```

Before a live canary, run the env-backed gates as well:

```bash
python scripts/run_deployment_gate_checks.py \
  --environment <environment> \
  --seller-agent-env /path/to/<environment>/seller.env \
  --buyer-agent-env /path/to/<environment>/buyer.env \
  --provisioning-env /path/to/<environment>/provisioning.env \
  --registry-env /path/to/<environment>/registry.env \
  --seller-agent-url http://<seller-host>:<seller-port> \
  --buyer-agent-url http://<buyer-host>:<buyer-port> \
  --seller-agent-id eip155:<chain_id>:<identity_registry>:<seller_token_id> \
  --buyer-agent-id eip155:<chain_id>:<identity_registry>:<buyer_token_id> \
  --seller-private-key 0x<seller-private-key> \
  --buyer-private-key 0x<buyer-private-key> \
  --ssh-private-key-path ~/.ssh/id_ed25519
```

Do not start a live run from a repo state that fails these gates.

## 2. Deployment Bundle Validation

Validate the target env bundle before touching live orders:

```bash
python scripts/validate_deployment_bundle.py \
  --environment <environment> \
  --seller-agent-env /path/to/<environment>/seller.env \
  --buyer-agent-env /path/to/<environment>/buyer.env \
  --provisioning-env /path/to/<environment>/provisioning.env \
  --registry-env /path/to/<environment>/registry.env \
  --seller-agent-url http://<seller-host>:<seller-port> \
  --buyer-agent-url http://<buyer-host>:<buyer-port> \
  --seller-agent-id eip155:<chain_id>:<identity_registry>:<seller_token_id> \
  --buyer-agent-id eip155:<chain_id>:<identity_registry>:<buyer_token_id> \
  --seller-private-key 0x<seller-private-key> \
  --buyer-private-key 0x<buyer-private-key> \
  --ssh-private-key-path ~/.ssh/id_ed25519
```

The validator checks the deployed env contract, network alignment, inventory
aliases, agent identity inputs, and the dual-agent canary assumptions.

## 3. Live Service Verification

Before creating orders, verify that the deployed endpoints are reachable from
the machine that will run the canary:

```bash
curl http://<registry-host>:<registry-port>/health
curl http://<provisioning-host>:<provisioning-port>/health
curl http://<seller-host>:<seller-port>/.well-known/agent-card.json
curl http://<seller-host>:<seller-port>/.well-known/erc-8004-registration.json
curl http://<seller-host>:<seller-port>/resources/portfolio
curl http://<buyer-host>:<buyer-port>/.well-known/agent-card.json
curl http://<buyer-host>:<buyer-port>/.well-known/erc-8004-registration.json
```

Confirm all of the following before running the smoke test:

- registry `/health` returns healthy
- provisioning `/health` returns healthy
- seller and buyer agent cards resolve over the deployed URLs
- seller `/resources/portfolio` reports at least one available matching resource
- the chosen VM host aliases exist in the tracked provisioning inventory
- the buyer and seller wallets are funded for the target chain
- if the canary uses `WETH`, the buyer also has enough native gas for `approve + escrow.create`
- any host firewall allows inbound agent traffic over ZeroTier

## 4. Live Canary Execution

Source the runner env before the live smoke run:

```bash
set -a
. /etc/simple-market-service/prod-canary.env
set +a
```

Run the smoke test from the repo with the CLI environment:

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
  --vm-host <candidate-host-1> \
  --vm-host <candidate-host-2> \
  --ssh-private-key-path ~/.ssh/id_ed25519
```

Optional flags:

- `--frp-dashboard-url` and `--frp-dashboard-password` to verify FRP proxy registration before matching
- `--chain-rpc-url` to override the chain RPC used by the runner
- `--match-salt` to force a deterministic match salt for repeated experiments
- repeated `--vm-host` flags to preflight multiple candidate KVM hosts

The runner also accepts defaults from environment variables such as
`FRP_DASHBOARD_URL`, `CANARY_TOKEN_AMOUNT`, `CANARY_MATCH_SALT`, and
`CANARY_VM_HOSTS`.

Repeated `--vm-host` flags override `CANARY_VM_HOSTS` from the sourced runner
env file. `--frp-dashboard-url` and `--frp-dashboard-password` must be
provided together when FRP verification is enabled.

If `--ssh-private-key-path` is provided, the canary verifies tenant SSH access
after provisioning succeeds. If it is omitted, the canary still validates order
creation, registry transitions, provisioning completion, and returned tenant
credentials.

## 5. Success Criteria

Treat the run as successful only when all of the following are true:

- seller and buyer order creation both succeed
- the registry exposes the newly created buyer and seller orders
- a new provisioning job is created and reaches `succeeded`
- buyer credentials include a tenant credential
- SSH verification succeeds when an SSH private key is provided
- both canary orders transition to `closed`
- cleanup leaves no stuck VM and no stale open canary order

## 6. Failure Handling

If the run fails:

1. Preserve the exact runner output, provisioning job ID, and canary order IDs.
2. Follow the exact rollback procedure in `docs/production-canary.md#rollback`.
3. Verify that the provisioned guest is stopped and reclaimed before retrying.
4. Re-run the repo gates after any repo-side fix.

If a KVM host needs to be rebooted during cleanup, stop the guest domains first.
Libvirt can block shutdown while it waits for active guests to stop.

## 7. Test Progression

Use the same runbook for each environment, but raise the bar as the deployment
moves forward:

- `dev`: one clean canary trade
- `staging`: one clean canary trade, then three consecutive clean trades
- `production`: one isolated canary trade, then three consecutive clean trades only after the first isolated run passes

## Definition Of Done

The end-to-end deployment path is ready when all of the following are true:

1. Repo gates pass from the intended revision.
2. The target env bundle passes validation.
3. `dev` passes one clean canary trade.
4. `staging` passes three consecutive clean canary trades.
5. `production` passes the isolated canary and then three consecutive clean trades with no manual remediation.
