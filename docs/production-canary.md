# Production Canary Runbook

This runbook is for the full-stack deployed flow:

- real ZeroTier network
- real registry
- real async provisioning service
- real worker / Ansible path
- no `mock` provisioning
- no `host.docker.internal`

Use a dedicated GCP project for the canary environment. Do not reuse a shared
deployment project for the first full-stack production-style run.

See also:

- `docs/deployment-input-checklist.md`
- `docs/e2e-deployment-test-plan.md`

## Local config

Use host-local env files for deployed testing. The production samples are
templates, not the live canary bundle.

Recommended private files:

- seller agent env: `/etc/simple-market-service/seller-agent.env`
- buyer agent env: `/etc/simple-market-service/buyer-agent.env`
- provisioning env: `/etc/simple-market-service/provisioning.env`
- registry env: `/etc/simple-market-service/registry.env`
- canary runner env: `/etc/simple-market-service/prod-canary.env`
- provisioning host secrets: `/etc/simple-market-service/management-vars.yaml`

Keep private keys, DB URLs, Redis URLs, ZeroTier IDs, FRP credentials, and real
service URLs out of Git.

The buyer and seller agent env files must stay writable if `AUTO_REGISTER=true`,
because agent startup persists `ZEROTIER_IP`, the resolved `BASE_URL_OVERRIDE`,
and `ONCHAIN_AGENT_ID` back into `ENV_FILE`.

If buyer and seller agents pull images directly from GCP Artifact Registry on the
remote agent hosts, authenticate Docker on each remote agent host before the
first pull. For Compute Engine hosts using the attached service account, a
working pattern is:

```bash
gcloud auth print-access-token \
  | sudo docker login -u oauth2accesstoken --password-stdin https://<region>-docker.pkg.dev
```

If the deployed agents use Vertex AI mode, the buyer and seller agent hosts
also need the attached service account to have `roles/storage.admin` on the
canary project and the VM access scope `cloud-platform`. Without those, the
agent startup path cannot create or manage the GCS bucket used for agent logs
and startup will fail before the agent card is served.

If buyer or seller hosts run a host firewall such as `ufw`, allow inbound
`8000/tcp` on the ZeroTier interface before running the canary. A healthy agent
container is not enough; the runner, registry, and counterparties still need to
fetch `/.well-known/agent-card.json` and `/.well-known/erc-8004-registration.json`
over ZeroTier.

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
- Agent `CHAIN_RPC_URL` must be an authenticated `ws://` or `wss://` endpoint for the Alkahest escrow client
- Agent `TOKEN_REGISTRY_PATH` must point at a real in-image registry file such as `/app/core/agent/app/data/token_registry_base_sepolia.json`
- Agent `PROVISIONING_MODE=http`
- Agent `ENABLE_EVENT_QUEUE=false` so deployed canaries use inline order processing instead of the queued worker path
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
- Buyer and seller hosts allow inbound `8000/tcp` over ZeroTier, including any
  `ufw` or equivalent host firewall rules.
- Seller inventory contains one quarantined canary resource.
- The seller agent reports that resource as currently available via
  `/resources/portfolio`, with matching `gpu_model`, `region`, and sufficient
  quantity for the canary request.
- Buyer and seller wallets are funded for the target chain.
- If the buyer canary uses `WETH`, the buyer wallet must also retain enough
  native gas for the on-chain `approve + escrow.create` path, even when the
  buyer already holds enough wrapped balance for the order principal.
- The canary runner is configured with `CANARY_VM_HOSTS` or `--vm-host` so the
  provisioning probe can submit `vm_action=check` jobs before any orders are
  created.
- Each candidate KVM host reported by that preflight has enough total and
  available GPUs for the requested canary quantity.

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
  --seller-agent-url http://<seller-zerotier-ip>:8000 \
  --buyer-agent-url http://<buyer-zerotier-ip>:8000 \
  --seller-agent-id eip155:<chain_id>:<identity_registry>:<seller_token_id> \
  --buyer-agent-id eip155:<chain_id>:<identity_registry>:<buyer_token_id> \
  --seller-private-key 0x... \
  --buyer-private-key 0x... \
  --gpu-model <gpu-model> \
  --region "<region>" \
  --token-symbol <token-symbol> \
  --token-amount 1.0 \
  --vm-host <kvm-host-alias> \
  --ssh-private-key-path ~/.ssh/id_ed25519
```

The runner also accepts `CANARY_VM_HOSTS=ww1,piknik1,...` in
`/etc/simple-market-service/prod-canary.env`. If configured, the canary will
submit provisioning `check` jobs up front and fail early when the selected host
cannot satisfy the requested GPU quantity.

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
