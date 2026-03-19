# End-to-End Deployment Test Plan

This plan assumes the production-style path:

- real ZeroTier network
- real ERC-8004 registry
- real async provisioning API + worker
- real FRP routing
- real seller inventory
- no `mock` provisioning

## Local Config Strategy

Use local gitignored env files for deployed testing. Do not store real canary
secrets in the committed sample env files.

Minimum local bundle layout:

- seller agent env: `core/agent/.env.seller.local`
- buyer agent env: `core/agent/.env.buyer.local`
- provisioning env: `async-provisioning-service/.env.local`
- registry env: `erc-8004-registry-py/.env.local`
- provisioning secrets: `compute-provisioning-iac/ansible/inventory/management-vars.yaml`

The canary is built around seven logical roles:

1. identity preflight validator
2. coordinator
3. seller actor
4. buyer actor
5. registry probe
6. provisioning probe
7. network probe

## Gate 0: Repo Consistency Checks

Run these before touching deployed systems:

```bash
python scripts/run_deployment_gate_checks.py --skip-smoke-help
```

What these checks cover:

- the async provisioning production sample exposes the runtime env contract
- the default VM host values in the samples exist in the tracked provisioning inventory
- the provisioning inventory contains the expected `dev` / `staging` / `production` host aliases
- the canary runbook and smoke script CLI stay in sync
- the actor orchestration tests pass and keep the refactor honest
- the CLI package tests and smoke-harness tests pass
- Base Sepolia Alkahest addresses in this repo stay in sync with the sibling `alkahest` repo when it is present

If Gate 0 fails, fix the repo drift first. Do not start a canary from an inconsistent tree.

## Gate 1: Environment Bundle Preflight

Create non-committed env bundles for `dev`, `staging`, and `production`. The next test layer should load those bundles and fail if any required value is still missing or placeholder.

Preflight assertions:

- required env vars are present
- URLs are real and do not contain `<...>` placeholders
- `DEFAULT_VM_HOST` exists in `compute-provisioning-iac/ansible/inventory/hosts`
- `ENABLE_AUTH=true` and `AUTH_FAIL_OPEN=false` for provisioning
- chain RPC, chain ID, and ERC-8004 addresses all target the same network
- seller and buyer agent env bundles are distinct and do not reuse the same URL, private key, or agent ID
- seller and buyer agent IDs are canonical `eip155:` IDs after registration

Run the preflight validator from the repo root:

```bash
python scripts/validate_deployment_bundle.py \
  --environment dev \
  --seller-agent-env /path/to/dev/seller.env \
  --buyer-agent-env /path/to/dev/buyer.env \
  --provisioning-env /path/to/dev/provisioning.env \
  --registry-env /path/to/dev/registry.env \
  --seller-agent-url http://<seller-zerotier-ip>:8001 \
  --buyer-agent-url http://<buyer-zerotier-ip>:8000 \
  --seller-agent-id eip155:84532:0x<identity-registry>:<seller-token-id> \
  --buyer-agent-id eip155:84532:0x<identity-registry>:<buyer-token-id> \
  --seller-private-key 0x<seller-private-key> \
  --buyer-private-key 0x<buyer-private-key> \
  --ssh-private-key-path ~/.ssh/id_ed25519
```

## TDD Workflow

### Phase 1: Local Red

1. Write or extend a failing test that captures the next deployment assumption.
2. Keep the failure narrow: config drift, missing env, incorrect URL shape, wrong address, missing inventory alias, or broken canary CLI contract.
3. Only after the failure is reproducible, change code/docs/config.

### Phase 2: Local Green

1. Make the failing consistency or preflight test pass.
2. Re-run Gate 0 and the focused package tests affected by the change.
3. Update samples and docs in the same change so the repo remains self-consistent.

### Phase 3: Dev Canary Red

Use `dev` first. Treat the deployed canary as the next failing test.

Expected order:

1. identity preflight validates the two actor bundles
2. network probe checks registry and provisioning health
3. network probe fetches seller and buyer agent cards over ZeroTier
4. seller actor captures its registry baseline and creates a sell order
5. buyer actor captures its registry baseline and creates a buy order
6. provisioning probe waits for a new succeeded job
7. provisioning probe fetches buyer credentials
8. provisioning probe verifies SSH access if a tenant private key is provided
9. registry probe confirms both orders transition to `closed`

If any step fails:

1. capture the exact failure
2. add the smallest reproducible test possible
3. fix it
4. re-run Gate 0
5. re-run the `dev` canary

### Phase 4: Dev Green

Success criteria for `dev`:

- one clean buyer/seller trade closes without manual DB edits
- provisioning returns tenant credentials
- buyer can SSH to the provisioned machine
- seller reaches escrow collection
- cleanup leaves no stuck VM or stale open order

### Phase 5: Staging Red/Green

After `dev` is green:

1. apply the same env-bundle preflight to `staging`
2. run one canary trade
3. then run three consecutive canary trades

Do not move to `production` until staging passes all three without manual host intervention.

### Phase 6: Production Canary

Production should stay quarantined:

1. one seller canary only
2. one buyer canary only
3. one quarantined seller resource only
4. one short trade first
5. three consecutive trades only after the first passes

Rollback remains the same as `docs/production-canary.md`.

## Mandatory Test Commands Per Loop

At minimum, re-run:

```bash
python scripts/run_deployment_gate_checks.py \
  --environment dev \
  --seller-agent-env /path/to/dev/seller.env \
  --buyer-agent-env /path/to/dev/buyer.env \
  --provisioning-env /path/to/dev/provisioning.env \
  --registry-env /path/to/dev/registry.env
```

Then run the deployed canary:

```bash
cd ../cli
uv --no-config run python ../scripts/prod_canary_smoke.py --help
```

When real env values are loaded, replace `--help` with the actual canary invocation from `docs/production-canary.md`.

## Known High-Risk Areas

1. Alkahest address drift across repos.
2. Provisioning env contract drift between sample envs, Dockerfile, and IaC docs.
3. ZeroTier URL resolution and host reachability.
4. FRP dashboard credentials and DNS correctness.
5. Seller inventory state leaking between test runs.

## Definition Of Done

The deployment path is considered ready only when all of the following are true:

1. Gate 0 passes from a clean repo state.
2. The environment bundle preflight passes for the target environment.
3. `dev` passes one clean canary trade.
4. `staging` passes three consecutive canary trades.
5. `production` canary passes three consecutive trades with no manual remediation.
