# Production Canary Runbook

This runbook is for the full-stack deployed flow:

- real ZeroTier network
- real registry
- real async provisioning service
- real worker / Ansible path
- no `mock` provisioning
- no `host.docker.internal`

See also:

- `docs/deployment-input-checklist.md`
- `docs/e2e-deployment-test-plan.md`

## Local config

Use local gitignored env files for deployed testing. The production samples are
templates, not the live canary bundle.

Recommended local files:

- seller agent env: `core/agent/.env.seller.local`
- buyer agent env: `core/agent/.env.buyer.local`
- provisioning env: `async-provisioning-service/.env.local`
- registry env: `erc-8004-registry-py/.env.local`
- provisioning host secrets: `compute-provisioning-iac/ansible/inventory/management-vars.yaml`

Keep private keys, DB URLs, Redis URLs, ZeroTier IDs, FRP credentials, and real
service URLs out of Git.

## Actor model

The canary runtime is organized into seven logical roles:

1. identity preflight validator
2. coordinator
3. seller actor
4. buyer actor
5. registry probe
6. provisioning probe
7. network probe

## Required config

Start from these templates:

- `core/agent/.env.production.sample`
- `async-provisioning-service/.env.production.sample`
- `erc-8004-registry-py/.env.production.sample`

Hard requirements:

- Agent `BASE_URL_OVERRIDE=http://{ZEROTIER_IP}:<port>/`
- Agent `PROVISIONING_MODE=http`
- Provisioning `ENABLE_AUTH=true`
- Provisioning `AUTH_FAIL_OPEN=false`
- Registry / provisioning URLs must point at deployed services, not localhost from another host

## Networking requirement

If the provisioning service must be reachable directly on the host ZeroTier IP, deploy it with host networking as described in `compute-provisioning-iac/README.md`.

## Deployment order

1. Deploy / verify the registry.
2. Deploy / verify Redis and the async provisioning API + worker.
3. Deploy / verify the seller agent.
4. Deploy / verify the buyer agent.
5. Authorize all nodes on the target ZeroTier network.
6. Confirm each service is reachable over its ZeroTier address.

## Preflight checks

- Buyer and seller use distinct local agent env files and distinct identities.
- The env bundle passes `scripts/validate_deployment_bundle.py`.
- The repo-side readiness gates pass via `scripts/run_deployment_gate_checks.py`.
- Registry health endpoint returns healthy.
- Provisioning health endpoint returns ok.
- Buyer and seller agent cards resolve over their deployed URLs.
- Seller inventory contains one quarantined canary resource.
- Buyer and seller wallets are funded for the target chain.

Run the repo-side gates with the dual-agent bundle before the live canary:

```bash
python scripts/run_deployment_gate_checks.py \
  --environment production \
  --seller-agent-env /path/to/production/seller.env \
  --buyer-agent-env /path/to/production/buyer.env \
  --provisioning-env /path/to/production/provisioning.env \
  --registry-env /path/to/production/registry.env
```

## Canary smoke run

Run the smoke script from the repo with the CLI environment so `eth-account` is available:

```bash
cd cli
uv --no-config run python ../scripts/prod_canary_smoke.py \
  --registry-url http://<registry-zerotier-ip>:8080 \
  --provisioning-url http://<provisioner-zerotier-ip>:8081 \
  --seller-agent-url http://<seller-zerotier-ip>:8001 \
  --buyer-agent-url http://<buyer-zerotier-ip>:8000 \
  --seller-agent-id eip155:<chain_id>:<identity_registry>:<seller_token_id> \
  --buyer-agent-id eip155:<chain_id>:<identity_registry>:<buyer_token_id> \
  --seller-private-key 0x... \
  --buyer-private-key 0x... \
  --gpu-model <gpu-model> \
  --region "<region>" \
  --token-symbol <token-symbol> \
  --token-amount 1.0 \
  --ssh-private-key-path ~/.ssh/id_ed25519
```

## Success criteria

- Both agent order-creation calls succeed.
- New buyer and seller registry orders are discovered.
- A new provisioning job appears for the seller agent and reaches `succeeded`.
- Buyer credentials for that job include a tenant credential.
- If `--ssh-private-key-path` is provided, the script successfully runs a remote command over SSH.
- Both registry orders transition to `closed` before timeout.

## Rollback

If the canary fails:

1. Cancel the new provisioning job.
2. Close or delete any canary orders that remained open.
3. Verify the VM was shut down or reclaimed.
4. Remove the quarantined canary resource from service if state is inconsistent.
5. Keep traffic pinned to the previous deployment until the failure is understood.
