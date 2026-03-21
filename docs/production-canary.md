# Production Canary Runbook

This runbook is for the full-stack deployed flow:

- real ZeroTier network
- real registry
- real async provisioning service
- real worker / Ansible path
- no `mock` provisioning
- no `host.docker.internal`

Use a dedicated deployment namespace for the canary environment. On GCP, that
means a dedicated GCP project rather than a shared project.

See also:

- `docs/standup/overview.md`
- `docs/e2e-runbook.md`
- `docs/deployment-input-checklist.md`
- `docs/e2e-deployment-test-plan.md`

Use `docs/standup/overview.md` for the full stand-up sequence and
`docs/e2e-runbook.md` for the operator-neutral validation flow. This document
focuses on the live canary execution step once the environment already exists.

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

The canary runner env at `/etc/simple-market-service/prod-canary.env` should
carry the live actor and runner defaults, for example:

```bash
SELLER_AGENT_URL=http://<seller-zerotier-ip>:8000
BUYER_AGENT_URL=http://<buyer-zerotier-ip>:8000
SELLER_AGENT_ID=eip155:<chain_id>:<identity_registry>:<seller_token_id>
BUYER_AGENT_ID=eip155:<chain_id>:<identity_registry>:<buyer_token_id>
SELLER_PRIVATE_KEY=0x<seller-private-key>
BUYER_PRIVATE_KEY=0x<buyer-private-key>
SSH_PRIVATE_KEY_PATH=~/.ssh/id_ed25519
CANARY_VM_HOSTS=ww1,piknik1
CANARY_GPU_QUANTITY=1
CANARY_DURATION_HOURS=1
CANARY_MATCH_SALT=<fixed-integer-when-repeatability-matters>
```

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

1. Deploy / verify the registry via `docs/standup/registry.md`.
2. Deploy / verify Redis and the async provisioning API + worker via `docs/standup/provisioning.md`.
3. Deploy / verify the seller agent via `docs/standup/agent-seller.md`.
4. Deploy / verify the buyer agent via `docs/standup/agent-buyer.md`.
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
  --registry-env /path/to/production/registry.env \
  --seller-agent-url http://<seller-zerotier-ip>:8000 \
  --buyer-agent-url http://<buyer-zerotier-ip>:8000 \
  --seller-agent-id eip155:<chain_id>:<identity_registry>:<seller_token_id> \
  --buyer-agent-id eip155:<chain_id>:<identity_registry>:<buyer_token_id> \
  --seller-private-key 0x<seller-private-key> \
  --buyer-private-key 0x<buyer-private-key> \
  --ssh-private-key-path ~/.ssh/id_ed25519
```

## Canary smoke run

Source the runner env before the live smoke run:

```bash
set -a
. /etc/simple-market-service/prod-canary.env
set +a
```

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
  --quantity <quantity> \
  --duration-hours <duration-hours> \
  --match-salt <match-salt> \
  --vm-host <kvm-host-alias> \
  --ssh-private-key-path ~/.ssh/id_ed25519 \
  | tee /tmp/prod-canary.log
```

The runner also accepts `CANARY_VM_HOSTS=ww1,piknik1,...` in
`/etc/simple-market-service/prod-canary.env`. If configured, the canary will
submit provisioning `check` jobs up front and fail early when the selected host
cannot satisfy the requested GPU quantity.

Repeated `--vm-host` flags override `CANARY_VM_HOSTS`. If you enable FRP
dashboard verification, `--frp-dashboard-url` and `--frp-dashboard-password`
must be provided together.

After the run, preserve the emitted IDs before cleanup:

Look for `[order] seller order:`, `[order] buyer order:`, and
`[provisioning] succeeded job:` in the captured log.

```bash
grep '^\[order\] seller order:' /tmp/prod-canary.log
grep '^\[order\] buyer order:' /tmp/prod-canary.log
grep '^\[provisioning\] succeeded job:' /tmp/prod-canary.log
```

Keep `prod-canary.log` as release-signoff proof. A successful isolated run can
be captured from `.github/workflows/deployed-canary.yml` artifacts or passed
directly to:

```bash
python scripts/run_release_gate_checks.py \
  --deployed-canary-log /tmp/prod-canary.log \
  --environment <environment> \
  --seller-agent-env /etc/simple-market-service/seller-agent.env \
  --buyer-agent-env /etc/simple-market-service/buyer-agent.env \
  --provisioning-env /etc/simple-market-service/provisioning.env \
  --registry-env /etc/simple-market-service/registry.env \
  --inventory-path compute-provisioning-iac/ansible/inventory/hosts \
  --skip-smoke-help
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

1. Preserve the exact runner output, provisioning job ID, and canary order IDs.
2. Re-source the runner env and export the emitted IDs from the captured log:

```bash
set -a
. /etc/simple-market-service/prod-canary.env
set +a

export SELLER_ORDER_ID="$(grep '^\[order\] seller order:' /tmp/prod-canary.log | tail -n1 | awk '{print $4}')"
export BUYER_ORDER_ID="$(grep '^\[order\] buyer order:' /tmp/prod-canary.log | tail -n1 | awk '{print $4}')"
export CANARY_JOB_ID="$(grep '^\[provisioning\] succeeded job:' /tmp/prod-canary.log | tail -n1 | awk '{print $4}')"
```

3. Inspect the provisioning job directly and recover the VM coordinates needed
   for cleanup:

```bash
curl -s \
  -H "Accept: application/json" \
  -H "X-Agent-ID: ${SELLER_AGENT_ID}" \
  "${PROVISIONING_SERVICE_URL}/api/v1/jobs/${CANARY_JOB_ID}"

eval "$(python - <<'PY'
import json
import os
import urllib.request

base = os.environ["PROVISIONING_SERVICE_URL"].rstrip("/")
job_id = os.environ["CANARY_JOB_ID"]
request = urllib.request.Request(
    f"{base}/api/v1/jobs/{job_id}",
    headers={
        "Accept": "application/json",
        "X-Agent-ID": os.environ["SELLER_AGENT_ID"],
    },
)
with urllib.request.urlopen(request, timeout=60) as response:
    job = json.load(response)
vm_host = job["params"]["vm_host"]
vm_name = job.get("result", {}).get("vm_name") or job["params"].get("vm_target", "")
print(f"export CANARY_VM_HOST={json.dumps(vm_host)}")
print(f"export CANARY_VM_NAME={json.dumps(vm_name)}")
PY
)"
```

4. Cancel the live provisioning job if it is still queued or running:

```bash
curl -s -X POST \
  -H "Accept: application/json" \
  -H "X-Agent-ID: ${SELLER_AGENT_ID}" \
  "${PROVISIONING_SERVICE_URL}/api/v1/jobs/${CANARY_JOB_ID}/cancel"
```

5. If the job already succeeded or the cancel response says it cannot be
   cancelled, reclaim the guest explicitly with `destroy` then `undefine`:

```bash
curl -s -X POST \
  -H "Content-Type: application/json" \
  -H "X-Agent-ID: ${SELLER_AGENT_ID}" \
  "${PROVISIONING_SERVICE_URL}/api/v1/jobs" \
  -d "{\"vm_host\":\"${CANARY_VM_HOST}\",\"vm_target\":\"${CANARY_VM_NAME}\",\"vm_action\":\"destroy\"}"

curl -s -X POST \
  -H "Content-Type: application/json" \
  -H "X-Agent-ID: ${SELLER_AGENT_ID}" \
  "${PROVISIONING_SERVICE_URL}/api/v1/jobs" \
  -d "{\"vm_host\":\"${CANARY_VM_HOST}\",\"vm_target\":\"${CANARY_VM_NAME}\",\"vm_action\":\"undefine\"}"
```

6. Close any canary orders that remained open. Use the matching maker keys to
   sign `update_order` operations:

```bash
cd cli
uv --no-config run python - <<'PY'
import json
import os
import time
import urllib.request

from eth_account import Account
from eth_account.messages import encode_defunct


def close_order(*, order_id: str, signer_agent_id: str, private_key: str) -> None:
    timestamp = int(time.time())
    message = f"update_order:{order_id}:{timestamp}"
    signature = Account.sign_message(
        encode_defunct(text=message),
        private_key,
    ).signature.hex()
    body = json.dumps(
        {
            "status": "closed",
            "signer_agent_id": signer_agent_id,
            "signature": signature,
            "timestamp": timestamp,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{os.environ['REGISTRY_URL'].rstrip('/')}/orders/{order_id}",
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="PUT",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        print(response.read().decode("utf-8"))


close_order(
    order_id=os.environ["SELLER_ORDER_ID"],
    signer_agent_id=os.environ["SELLER_AGENT_ID"],
    private_key=os.environ["SELLER_PRIVATE_KEY"],
)
close_order(
    order_id=os.environ["BUYER_ORDER_ID"],
    signer_agent_id=os.environ["BUYER_AGENT_ID"],
    private_key=os.environ["BUYER_PRIVATE_KEY"],
)
PY
```

7. Verify that the provisioned guest is stopped and reclaimed before retrying.
8. Remove the quarantined canary resource from service if state is inconsistent.
9. Keep traffic pinned to the previous deployment until the failure is understood.
10. Re-run the repo gates after any repo-side fix.

If a KVM host needs to be rebooted during cleanup, stop the guest domains first.
libvirt can block shutdown while it waits for active guests to stop.
