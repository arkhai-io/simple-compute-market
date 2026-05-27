# Full Validation Runbook

Goal: run the code-level unit/integration tests, bring up the local deployed
stack in mock mode, optionally repeat the same manual path on a clean Ubuntu VM,
then run a CLI-first GCP proof for real Ansible/KVM provisioning.

## Notes

- All commands assume the repo root unless a step explicitly changes
  directories.
- `make test-module MODULE=<marker>` in `integration-tests/` runs
  `pytest -m <marker>`.
- High `deselected` counts are expected for marker-specific runs. Pytest
  discovers the whole `integration-tests/tests/` tree, then runs only tests
  matching the requested marker.
- Keep `docker compose -f docker-compose.yml -f /tmp/scm-no-redis-port.yml`
  together for every compose command if the Redis port override is in use.
- Use `docker compose down -v` only when intentionally wiping named volumes.
  Fresh storefront volumes currently need the ownership workaround below.
- Keep issue evidence in `.scm-local/notes/issue-notes.md`; this runbook is
  for repeatable execution.
- The issue-discovery harness is intentionally separate. Use
  `docs/ISSUE_DISCOVERY.md` when the goal is issue candidate generation and
  filing.

## Local Mock Pass Criteria

- Code-level test commands finish with no failures.
- Smoke/e2e marker runs may report many deselected tests; this is expected.
  Treat `failed`, `error`, or unexpected `skipped`/`xfailed` results as the
  signal to investigate.
- Manual readiness checks should show:
  - Anvil chain id `0x7a69` / `31337`.
  - Registry `/health` returns `status: ok`.
  - Bob and Alice storefront `/health` return `status: ok`.
  - Bob `/api/v1/system/status` has `registry: ok`, `registry_auth: ok`,
    populated `agent_id`, `chain_id: 31337`, and `resource_count >= 1`.
  - Provisioning `/api/v1/system/status` has `storefront: ok`,
    `storefront_auth: ok`, and `lease_watchdog: running`.

## Optional Local Automation

If your local `.scm-local/` checkout contains the helper script, the manual
steps below are mirrored by:

```bash
.scm-local/scripts/validate-local-stack.sh
```

That script assumes host prerequisites already exist; it verifies them but does
not install Docker, ZeroTier, `uv`, or other tools.

Useful toggles:

```bash
KEEP_STACK=1 .scm-local/scripts/validate-local-stack.sh          # leave compose up
SKIP_BUILD=1 .scm-local/scripts/validate-local-stack.sh          # reuse existing images
RUN_CODE_TESTS=0 .scm-local/scripts/validate-local-stack.sh      # stack tests only
RUN_STACK_TESTS=0 .scm-local/scripts/validate-local-stack.sh     # code/build tests only
RUN_HELM_RENDER=1 .scm-local/scripts/validate-local-stack.sh     # require helm render check
RUN_IAC_VALIDATE=1 .scm-local/scripts/validate-local-stack.sh    # require Ansible IAC validation
FIX_STOREFRONT_VOLUME_OWNERSHIP=0 .scm-local/scripts/validate-local-stack.sh  # skip volume chown workaround
RUN_INTEGRATION_SWEEP=1 .scm-local/scripts/validate-local-stack.sh
```

Defaults:

- Build is enabled.
- Code-level tests are enabled.
- Compose smoke/e2e tests are enabled.
- Redis host-port publishing is disabled through `/tmp/scm-no-redis-port.yml`.
- `compute-provisioning-iac` contract tests run by default because they do not
  require a live KVM host or Ansible inventory.
- Bob/Alice storefront named volumes are pre-chowned to UID/GID `1000:1000`
  before stack startup to avoid the known SQLite volume ownership failure.
- A quiet `anvil_dumpState` check runs after Anvil is reachable.
- Helm render validation runs automatically when `helm` is available.
- Compute-provisioning IAC validation runs automatically when Ansible tooling
  and `compute-provisioning-iac/ansible/inventory/hosts` are available.
- The single-pass `integration-tests make test` sweep is off by default because
  it reruns stack-mutating e2e tests after the marker-specific runs.

## 1. Prerequisites

```bash
docker info
docker compose version
make --version
command -v uv || echo "uv missing"
command -v python3 || echo "python3 missing"
command -v jq || echo "jq missing"
command -v curl || echo "curl missing"
```

Verify ZeroTier:

```bash
command -v zerotier-cli
systemctl is-active zerotier-one
sudo zerotier-cli info
```

If ZeroTier is missing:

```bash
sudo apt-get update --allow-releaseinfo-change
sudo apt-get install -y zerotier-one
sudo systemctl enable --now zerotier-one
```

Make sure the provisioning SSH bind mount source exists:

```bash
test -f ~/.ssh/id_ed25519 || ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519
```

## 2. Clean Fixed Docker Names

Before a fresh rebuild:

```bash
docker rm -f \
  anvil \
  contracts-deploy \
  market-contracts-deploy \
  market-agent-sell \
  market-agent-buy \
  market-agent-alice \
  market-redis \
  market-provisioning \
  2>/dev/null || true
docker network rm anvil 2>/dev/null || true
```

## 3. Build Artifacts And Images

```bash
make build
```

Expected build products include `.dist/`, `shared-env/.env`,
`test-env/state/state.json`, and Docker images for the local stack.

## 4. Code-Level Tests

These are the architecture-defined unit and integration tests. They do not
require the compose stack to be running.

Root service suite:

```bash
make test
```

This runs unit + integration tests for:

- `provisioning-service`
- `registry-service`
- `storefront`

Shared service package:

```bash
cd service
make reinit
make test
cd ..
```

Policy package:

```bash
cd policy
uv sync --dev
uv run pytest tests/unit/ -v
cd ..
```

Buyer package:

```bash
cd buyer
uv sync --python 3.12 --extra test
uv run pytest tests/ -v
make smoke-test
cd ..
```

Storefront client package:

```bash
cd storefront-client
uv sync --dev
uv run pytest tests/ -v
cd ..
```

Compute provisioning IAC contract tests:

```bash
cd compute-provisioning-iac
python3 -m unittest discover -s tests -p 'test_*.py' -v
cd ..
```

Integration-test harness unit tests:

```bash
cd integration-tests
make reinit
.venv/bin/pytest tests/unit/ -v
cd ..
```

Current note:

- `registry-client/` currently has a `tests/` package but no `test_*.py`
  files, so there is no runnable registry-client test command at the moment.
- `infra/` currently has pytest dev dependencies but no `test_*.py` files, so
  there is no runnable infra package test command at the moment.

## 5. Optional Environment-Dependent Local Tests

Compute provisioning IAC inventory/playbook validation requires Ansible tooling
and `compute-provisioning-iac/ansible/inventory/hosts`:

```bash
cd compute-provisioning-iac
make validate
cd ..
```

Do not run acceptance validation unless a real KVM host is configured:

```bash
cd compute-provisioning-iac
make validate-acceptance KVM_HOST=<inventory-host>
cd ..
```

Helm render validation requires Helm, but not a live cluster:

```bash
cd helm
make test-render
cd ..
```

Policy training/RL dependencies are not part of the standard local validation.
The old `domain/compute/tests` integration suite was removed in the latest pull;
future training or RL validation should be documented separately when runnable
tests are added back.

## 6. Known Exclusions For Local Mock Validation

These are not covered by the standard local run above:

- `registry-client`: has a `tests/` package but currently no `test_*.py`
  files, so there is no runnable test suite to execute.
- `infra`: has pytest dev dependencies but currently no `test_*.py` files, so
  there is no runnable test suite to execute.
- `market-contract-deployer`: has a build target but no repo-native test
  target; coverage is indirect through `make build` and stack smoke/e2e tests.
- `roles_layer_buyer`: marker is registered but no current tests use it.
- `mock_provisioning`, `mock_provisioning_happy`, and
  `mock_provisioning_failure`: markers are still registered, but the old tests
  were retired with the buyer-storefront drop.
- Helm/Kubernetes test pods: `helm test` coverage requires a deployed Helm
  release and is separate from the local compose stack.
- `compute-provisioning-iac make validate-acceptance`: requires a real KVM host
  and `KVM_HOST` set to an inventory alias.
- Policy training/RL behavior: no current standard local test command covers
  the training stack or trained model inference.
- Production/non-mock provisioning: the local mock path uses
  `PROVISIONING_MODE=mock`; real Ansible/KVM coverage starts in sections
  17-26.
- External-chain deployments: the local mock path validates the local Anvil
  chain generated by `make build`, not Base Sepolia, mainnet, or another live
  RPC.
- Helm/Kubernetes deployment checks: local `cd helm && make test-render` is
  optional above, but actual `helm deploy` / `helm test` coverage requires a
  cluster and starts in sections 17-26.

## 7. Redis Override

Create this override for local runs. It is required when the host already has
Redis on port `6379`, and harmless unless you specifically need container Redis
published on the host:

```bash
cat >/tmp/scm-no-redis-port.yml <<'YAML'
services:
  redis:
    ports: !reset []
YAML
```

## 8. Bring Up Local Stack

```bash
PROVISIONING_MODE=mock docker compose \
  -f docker-compose.yml \
  -f /tmp/scm-no-redis-port.yml \
  up -d
```

If `bob-storefront` or `alice-storefront` exit with SQLite DB errors, fix volume
ownership:

```bash
docker run --rm --user 0:0 \
  -v simple-compute-market_bob-storefront-data:/bob \
  -v simple-compute-market_alice-storefront-data:/alice \
  alpine:3.20 sh -c 'chown -R 1000:1000 /bob /alice'

PROVISIONING_MODE=mock docker compose \
  -f docker-compose.yml \
  -f /tmp/scm-no-redis-port.yml \
  up -d bob-storefront alice-storefront
```

Watch startup:

```bash
docker compose -f docker-compose.yml -f /tmp/scm-no-redis-port.yml ps

docker compose -f docker-compose.yml -f /tmp/scm-no-redis-port.yml \
  logs -f anvil contracts-deploy registry bob-storefront alice-storefront provisioning
```

## 9. Manual Readiness Checks

Core health:

```bash
curl -sf http://localhost:8545 -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"eth_chainId","params":[],"id":1}' | jq

curl -sf http://localhost:8080/health | jq
curl -sf http://localhost:8001/health | jq
curl -sf http://localhost:8002/health | jq
curl -sf http://localhost:8081/health | jq
```

Richer status:

```bash
curl -sf -H 'X-Admin-Key: test-api-key' \
  http://localhost:8001/api/v1/system/status | jq

curl -sf http://localhost:8081/api/v1/system/status | jq
curl -sf http://localhost:8081/api/v1/hosts/ | jq
```

Registry agents:

```bash
curl -sf http://localhost:8080/agents | jq
```

Test-env state smoke, as a quieter equivalent of `cd test-env && make smoke`:

```bash
curl -sf http://localhost:8545 -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"anvil_dumpState","params":[],"id":1}' \
  | jq -e '.result | type == "string" and length > 0'
```

Register mock `kvm1` if provisioning returns `{"hosts":[]}`:

```bash
curl -sf -X POST http://localhost:8081/api/v1/hosts/ \
  -H 'Content-Type: application/json' \
  -d '{"name":"kvm1","kvm_host":"127.0.0.1","ssh_user":"appuser","ssh_key_type":"path","ssh_key_value":"/home/appuser/.ssh/id_ed25519","gpu_count":1,"enabled":true}' | jq
```

## 10. Failure Diagnostics

If compose startup fails, capture these before changing state:

```bash
docker compose -f docker-compose.yml -f /tmp/scm-no-redis-port.yml ps
docker compose -f docker-compose.yml -f /tmp/scm-no-redis-port.yml logs --tail=200
docker ps -a --filter name=anvil --filter name=market
docker volume ls | grep simple-compute-market
```

For Redis bind failures:

```bash
ss -ltnp '( sport = :6379 )' || true
systemctl status redis-server --no-pager || true
```

For storefront SQLite failures:

```bash
docker compose -f docker-compose.yml -f /tmp/scm-no-redis-port.yml logs --tail=200 bob-storefront alice-storefront
docker run --rm -v simple-compute-market_bob-storefront-data:/data alpine:3.20 ls -ldn /data
docker run --rm -v simple-compute-market_alice-storefront-data:/data alpine:3.20 ls -ldn /data
```

## 11. Deployment Smoke Tests

```bash
cd integration-tests

make test-module MODULE=contracts ACTIVE_PROFILES=local
make test-module MODULE=wallets ACTIVE_PROFILES=local
make test-module MODULE=registry ACTIVE_PROFILES=local
make test-module MODULE=storefront ACTIVE_PROFILES=local
make test-module MODULE=provisioning ACTIVE_PROFILES=local
```

## 12. System Integration / E2E Tests

Layer checks:

```bash
make test-module MODULE=roles_layer_external ACTIVE_PROFILES=local
make test-module MODULE=roles_layer_registry ACTIVE_PROFILES=local
make test-module MODULE=roles_layer_seller ACTIVE_PROFILES=local
```

Full-deal scenarios:

```bash
make test-module MODULE=e2e_deal ACTIVE_PROFILES=local
make test-module MODULE=e2e_deal_buyer_cli ACTIVE_PROFILES=local
make test-module MODULE=multi_registry ACTIVE_PROFILES=local
```

## 13. Optional Single-Pass Integration-Test Sweep

After running the marker-specific commands above, this can catch any unmarked
test in `integration-tests/tests/`. Run it before teardown and expect it to
rerun tests that mutate stack state:

```bash
make test ACTIVE_PROFILES=local
```

Prefer the marker-specific commands for diagnosis. They produce smaller,
clearer failures.

## 14. Teardown

```bash
cd ..
docker compose -f docker-compose.yml -f /tmp/scm-no-redis-port.yml down
```

Only wipe volumes intentionally:

```bash
docker compose -f docker-compose.yml -f /tmp/scm-no-redis-port.yml down -v
```

## 15. Clean Ubuntu Host Bootstrap

Use this on a fresh Ubuntu host when you want to prepare prerequisites and then
rerun the manual local validation from section 1. This section does not run the
issue-discovery harness.

Check an already-prepared host:

```bash
./scripts/bootstrap-clean-host-ubuntu.sh check
```

Install prerequisites without running validation:

```bash
sudo SCM_RUN_VALIDATION=0 ./scripts/bootstrap-clean-host-ubuntu.sh run
```

After bootstrap, start a new login session so Docker group membership is visible,
or use `sg docker` for the first Docker command:

```bash
docker info || sg docker -c 'docker info'
```

Then rerun the manual local validation from section 1 on that host.

## 16. Manual Multipass Clean Host

Use this when the local mock validation above needs to be repeated on a
disposable Ubuntu VM. This is a manual clean-machine recipe. Do not use
`scripts/clean-room/multipass-run.sh` for this runbook; that wrapper belongs to
the issue-discovery workflow.

Host prerequisites:

```bash
command -v multipass
multipass version
```

Create a VM:

```bash
export SCM_MP_NAME=scm-manual-local-$(date -u +%Y%m%d%H%M%S)

multipass launch 24.04 \
  --name "$SCM_MP_NAME" \
  --cpus 6 \
  --memory 12G \
  --disk 60G

multipass info "$SCM_MP_NAME"
```

Transfer the current working tree. This uses `tar` instead of a git bundle so
ignored local notes and uncommitted edits can be included deliberately. The
excludes avoid copying build outputs, virtualenvs, Docker data, and prior local
run artifacts.

```bash
tar \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='*/.venv' \
  --exclude='.dist' \
  --exclude='dist' \
  --exclude='build' \
  --exclude='node_modules' \
  --exclude='test-env/state' \
  --exclude='.scm-local/issue-discovery' \
  --exclude='.scm-local/clean-room-runs' \
  --exclude='scm-clean-room-transfer' \
  -czf /tmp/scm-manual-local.tgz .

multipass transfer /tmp/scm-manual-local.tgz "$SCM_MP_NAME:/home/ubuntu/scm.tgz"

multipass exec "$SCM_MP_NAME" -- bash -lc '
  set -euo pipefail
  rm -rf /home/ubuntu/simple-compute-market
  mkdir -p /home/ubuntu/simple-compute-market
  tar -xzf /home/ubuntu/scm.tgz -C /home/ubuntu/simple-compute-market
'
```

Install host prerequisites inside the VM without running any validation command:

```bash
multipass exec "$SCM_MP_NAME" -- bash -lc '
  cd /home/ubuntu/simple-compute-market
  sudo SCM_RUN_VALIDATION=0 ./scripts/bootstrap-clean-host-ubuntu.sh run
'
```

Open a shell in the VM and rerun the manual local validation from this runbook,
starting at section 1. Because Docker group membership may not be visible in the
current login session immediately after bootstrap, either open a fresh shell or
use `sg docker`.

```bash
multipass shell "$SCM_MP_NAME"

cd /home/ubuntu/simple-compute-market
./scripts/bootstrap-clean-host-ubuntu.sh check
docker info || sg docker -c 'docker info'
```

When finished, copy any notes or artifacts you want to keep back to the host:

```bash
mkdir -p ".scm-local/manual-multipass-runs/$SCM_MP_NAME"

multipass transfer --recursive \
  "$SCM_MP_NAME:/home/ubuntu/simple-compute-market/.scm-local" \
  ".scm-local/manual-multipass-runs/$SCM_MP_NAME/" || true
```

Tear down the VM:

```bash
multipass delete "$SCM_MP_NAME" --purge
rm -f /tmp/scm-manual-local.tgz
```

## 17. GCP Proof Overview And Preflight

This proves the current real provisioning path on GCP by using one manually
created GCE VM as a KVM host. It does not validate the future
`GCPComputeProvider` or resource-pool design.

Run the commands in one shell where possible. Later GCP sections reuse the
exported variables below.

Run from this repo first:

```bash
export APP_REPO="$(pwd)"
export OPS_REPO="$(cd ../compute-market-internal-infra && pwd)"

export ENV=dev
export GCP_PROJECT=compute-market-1-dev
export REGION=us-central1
export ZONE=us-central1-a

export RELEASE=arkhai-node-operator
export KVM_HOST_ALIAS=gce-kvm1
export KVM_VM_NAME=scm-kvm-host-1
export KVM_ADDRESS_NAME=scm-kvm-host-1-ip
export KVM_TAG=scm-kvm-host
export NETWORK=compute-market-1-dev-vpc
export SUBNET=compute-market-1-dev-gke-nodes
```

Sanity-check the branch and sibling repo:

```bash
git status --short --branch
test -d "$OPS_REPO"
git -C "$OPS_REPO" status --short --branch

for cmd in gcloud terraform helm kubectl docker jq curl openssl ssh ssh-keygen python3; do
  command -v "$cmd"
done

python3 - <<'PY'
import yaml
from cryptography.fernet import Fernet
PY
```

## 18. GCP Platform Bootstrap

This section creates or validates platform-level GCP and Kubernetes
infrastructure. Terraform owns these resources. Apply `api-gateway` here, but
do not run `scripts/validate/api-gateway.sh` until section 20; that validator
probes application routes that do not exist yet.

Authenticate first:

```bash
cd "$OPS_REPO"

make gcloud-login
gcloud config set project "$GCP_PROJECT"
gcloud auth application-default print-access-token >/dev/null
gcloud auth configure-docker "${REGION}-docker.pkg.dev"
```

Run these once per project. If the tfstate bucket already exists, skip the
create command and run the validator.

```bash
make bootstrap-apis ENV="$ENV"
make bootstrap-tfstate ENV="$ENV"
bash scripts/validate/tfstate.sh "$ENV"
```

Use component validators as you go. Do not use full `make validate-env` as an
early gate; it checks resources that do not exist until later in this sequence.

```bash
make tf-init  ENV="$ENV" COMPONENT=artifact-registry
make tf-apply ENV="$ENV" COMPONENT=artifact-registry
bash scripts/validate/artifact-registry.sh "$ENV"

make tf-init  ENV="$ENV" COMPONENT=networking
make tf-apply ENV="$ENV" COMPONENT=networking
bash scripts/validate/networking.sh "$ENV"

make tf-init  ENV="$ENV" COMPONENT=gke
make tf-apply ENV="$ENV" COMPONENT=gke
make get-credentials ENV="$ENV"
bash scripts/validate/gke.sh "$ENV"

make tf-init  ENV="$ENV" COMPONENT=secret-shells
make tf-apply ENV="$ENV" COMPONENT=secret-shells
bash scripts/validate/secrets.sh "$ENV"

make tf-init  ENV="$ENV" COMPONENT=api-gateway
make tf-apply ENV="$ENV" COMPONENT=api-gateway
```

## 19. Runtime Inputs

The secret shells must exist before these commands run. The initial
`HOSTS_INI=/dev/null` is intentional for the mock deployment; the real GCE KVM
host is registered through the provisioning API later.
Use explicit `gcloud secrets versions add` commands for the provisioning SSH key
until the ops repo helper target is corrected. Also render the storefront
Secret value directly from the application chart: the current app chart expects
`storefront.secrets.toml`, while the ops repo bootstrap helper still targets the
older monolithic `config.toml` shape.

```bash
make bootstrap-admin-api-key ENV="$ENV"

(
  TMPDIR="$(mktemp -d)"
  trap 'rm -rf "$TMPDIR"' EXIT

  ssh-keygen -t ed25519 \
    -f "$TMPDIR/id_ed25519" \
    -N "" \
    -C "simple-market-service-provisioning-${ENV}" \
    -q

  gcloud secrets versions add simple-market-service-provisioning-ssh-key \
    --data-file=- \
    --project="$GCP_PROJECT" < "$TMPDIR/id_ed25519"

  gcloud secrets versions add simple-market-service-provisioning-ssh-pub-key \
    --data-file=- \
    --project="$GCP_PROJECT" < "$TMPDIR/id_ed25519.pub"
)

make bootstrap-provisioning-secrets ENV="$ENV" HOSTS_INI=/dev/null

ADMIN_API_KEY="$(make --silent get-admin-api-key ENV="$ENV")"

(
  TMPDIR="$(mktemp -d)"
  trap 'rm -rf "$TMPDIR"' EXIT

  helm template "$RELEASE" "$APP_REPO/helm" \
    --show-only charts/storefront/templates/secrets.yaml \
    --values "$OPS_REPO/helm/argocd-apps/envs/dev/storefront-bootstrap-values.yaml" \
    --set "storefront.agents[0].secret.privKey=0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a" \
    --set "storefront.agents[0].secret.walletAddress=0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC" \
    --set "global.adminApiKey=${ADMIN_API_KEY}" \
    > "$TMPDIR/storefront-secret.yaml"

  python3 - "$TMPDIR/storefront-secret.yaml" > "$TMPDIR/storefront.secrets.toml" <<'PY'
import sys
import yaml

with open(sys.argv[1], encoding="utf-8") as fh:
    for doc in yaml.safe_load_all(fh):
        if not doc or doc.get("kind") != "Secret":
            continue
        value = (doc.get("stringData") or {}).get("storefront.secrets.toml")
        if value is not None:
            sys.stdout.write(value)
            break
    else:
        raise SystemExit("ERROR: storefront.secrets.toml not found in rendered Secret")
PY

  gcloud secrets versions add simple-market-service-storefront-arkhai \
    --data-file="$TMPDIR/storefront.secrets.toml" \
    --project="$GCP_PROJECT"
)
```

Build and push the runtime artifacts after Artifact Registry exists:

```bash
cd "$APP_REPO"

make build
make push-runtime-artifacts AR_PROJECT="$GCP_PROJECT"
```

## 20. Kubernetes App Bootstrap In Mock Mode

The `argocd-apps` chart owns the application-side Kubernetes resources that sit
on top of the platform: ExternalSecrets, the Kong `Gateway`, HTTPRoutes, and the
route ReferenceGrant. Patch the storefront ExternalSecret after install until
the ops repo template is updated to emit `storefront.secrets.toml`.

```bash
cd "$OPS_REPO"

INGRESS_IP="$(make --silent get-ingress-lb-ip ENV="$ENV")"

helm upgrade --install argocd-apps helm/argocd-apps \
  --values helm/argocd-apps/envs/dev/values.yaml \
  --set "gateway.ingressLbIp=${INGRESS_IP}" \
  --namespace default

kubectl patch externalsecret simple-market-service-storefront-arkhai \
  -n default \
  --type='json' \
  -p='[{"op":"replace","path":"/spec/data/0/secretKey","value":"storefront.secrets.toml"}]'

kubectl get externalsecrets -A

FORCE_SYNC="$(date +%s)"
for externalsecret in \
  simple-market-service-admin-api-key \
  simple-market-service-provisioning-ssh-key \
  simple-market-service-provisioning-secrets \
  simple-market-service-storefront-arkhai \
  simple-market-service-e2e-secret; do
  kubectl annotate "externalsecret/${externalsecret}" \
    -n default \
    "force-sync=${FORCE_SYNC}" \
    --overwrite
  kubectl wait --for=condition=Ready "externalsecret/${externalsecret}" \
    -n default \
    --timeout=5m
done

for secret in \
  simple-market-service-admin-api-key \
  simple-market-service-provisioning-ssh-key \
  simple-market-service-provisioning-secrets \
  simple-market-service-storefront-arkhai \
  arkhai-node-operator-e2e-tests-e2e-secret; do
  kubectl get secret "$secret" -n default
done

kubectl get secret simple-market-service-storefront-arkhai \
  -n default \
  -o jsonpath='{.data.storefront\.secrets\.toml}' | grep -q .
```

Deploy the current dev overlay as-is first. This proves images, Helm values,
secret mounts, and service wiring before real provisioning is enabled.
On a reused dev cluster, restart the application deployments in dependency
order so mutable image tags and startup-read config are actually reloaded. Do
not restart `test-env` here unless you intentionally want to reset the dev
Anvil chain state.

```bash
helm upgrade --install "$RELEASE" "$APP_REPO/helm" \
  --values "$APP_REPO/helm/values.yaml" \
  --values "$OPS_REPO/helm/argocd-apps/envs/dev/simple-market-service-values.yaml" \
  --namespace default \
  --wait \
  --timeout 10m

for deployment in \
  "${RELEASE}-registry" \
  "${RELEASE}-storefront-arkhai" \
  "${RELEASE}-provisioning"; do
  kubectl rollout restart "deploy/${deployment}" -n default
  kubectl rollout status "deploy/${deployment}" -n default --timeout=10m
done

kubectl get pods -n default
kubectl get pods -n kong

make forward ENV="$ENV"
curl -sf http://localhost:8081/health | jq
curl -sf http://localhost:8081/api/v1/system/status | jq
bash scripts/validate/api-gateway.sh "$ENV"
make unforward
```

## 21. Manual GCE KVM Host

Create a local operator key for the manual Ansible setup run. The provisioning
service has its own SSH key in Secret Manager; add both public keys to the GCE
VM so local Ansible and the in-cluster provisioning pod can both SSH as
`ubuntu`.

```bash
cd "$APP_REPO"
mkdir -p .scm-local/gcp

test -f .scm-local/gcp/scm-kvm-operator_ed25519 || \
  ssh-keygen -t ed25519 -N "" \
    -f .scm-local/gcp/scm-kvm-operator_ed25519 \
    -C "scm-gcp-kvm-operator"

PROVISIONING_PUBKEY="$(cd "$OPS_REPO" && make --silent get-provisioning-ssh-pubkey ENV="$ENV")"

cat >.scm-local/gcp/kvm-host-ssh-keys <<EOF
ubuntu:$(cat .scm-local/gcp/scm-kvm-operator_ed25519.pub)
ubuntu:${PROVISIONING_PUBKEY}
EOF
```

Reserve an external IP and create temporary firewall rules:

```bash
cd "$OPS_REPO"

gcloud compute addresses describe "$KVM_ADDRESS_NAME" \
  --project "$GCP_PROJECT" \
  --region "$REGION" >/dev/null 2>&1 || \
  gcloud compute addresses create "$KVM_ADDRESS_NAME" \
    --project "$GCP_PROJECT" \
    --region "$REGION"

KVM_EXTERNAL_IP="$(gcloud compute addresses describe "$KVM_ADDRESS_NAME" \
  --project "$GCP_PROJECT" \
  --region "$REGION" \
  --format='value(address)')"

NAT_IP="$(gcloud compute addresses describe "${GCP_PROJECT}-nat" \
  --project "$GCP_PROJECT" \
  --region "$REGION" \
  --format='value(address)')"

OPERATOR_IP="$(curl -fsS https://ifconfig.me/ip)"

if gcloud compute firewall-rules describe "${KVM_VM_NAME}-ssh" \
  --project "$GCP_PROJECT" >/dev/null 2>&1; then
  gcloud compute firewall-rules update "${KVM_VM_NAME}-ssh" \
    --project "$GCP_PROJECT" \
    --rules tcp:22 \
    --source-ranges "${OPERATOR_IP}/32,${NAT_IP}/32" \
    --target-tags "$KVM_TAG"
else
  gcloud compute firewall-rules create "${KVM_VM_NAME}-ssh" \
    --project "$GCP_PROJECT" \
    --network "$NETWORK" \
    --direction INGRESS \
    --action ALLOW \
    --rules tcp:22 \
    --source-ranges "${OPERATOR_IP}/32,${NAT_IP}/32" \
    --target-tags "$KVM_TAG"
fi

if gcloud compute firewall-rules describe "${KVM_VM_NAME}-buyer-dnat" \
  --project "$GCP_PROJECT" >/dev/null 2>&1; then
  gcloud compute firewall-rules update "${KVM_VM_NAME}-buyer-dnat" \
    --project "$GCP_PROJECT" \
    --rules tcp:10000-65000 \
    --source-ranges 0.0.0.0/0 \
    --target-tags "$KVM_TAG"
else
  gcloud compute firewall-rules create "${KVM_VM_NAME}-buyer-dnat" \
    --project "$GCP_PROJECT" \
    --network "$NETWORK" \
    --direction INGRESS \
    --action ALLOW \
    --rules tcp:10000-65000 \
    --source-ranges 0.0.0.0/0 \
    --target-tags "$KVM_TAG"
fi
```

Verify the Ubuntu image family, then create the VM:

```bash
gcloud compute images describe-from-family ubuntu-2404-lts-amd64 \
  --project ubuntu-os-cloud \
  --format='value(selfLink)'

if gcloud compute instances describe "$KVM_VM_NAME" \
  --project "$GCP_PROJECT" \
  --zone "$ZONE" >/dev/null 2>&1; then
  :
else
  gcloud compute instances create "$KVM_VM_NAME" \
    --project "$GCP_PROJECT" \
    --zone "$ZONE" \
    --machine-type n2-standard-8 \
    --network "$NETWORK" \
    --subnet "$SUBNET" \
    --address "$KVM_EXTERNAL_IP" \
    --tags "$KVM_TAG" \
    --boot-disk-size 100GB \
    --image-family ubuntu-2404-lts-amd64 \
    --image-project ubuntu-os-cloud \
    --enable-nested-virtualization \
    --metadata-from-file "ssh-keys=${APP_REPO}/.scm-local/gcp/kvm-host-ssh-keys"
fi

gcloud compute instances add-tags "$KVM_VM_NAME" \
  --project "$GCP_PROJECT" \
  --zone "$ZONE" \
  --tags "$KVM_TAG"

gcloud compute instances add-metadata "$KVM_VM_NAME" \
  --project "$GCP_PROJECT" \
  --zone "$ZONE" \
  --metadata-from-file "ssh-keys=${APP_REPO}/.scm-local/gcp/kvm-host-ssh-keys"
```

## 22. Local Ansible Proof Against The GCE Host

```bash
cd "$APP_REPO"

command -v ansible
command -v ansible-galaxy
command -v ansible-playbook

cat >.scm-local/gcp/kvm-hosts.ini <<EOF
[kvm_hosts]
${KVM_HOST_ALIAS} ansible_host=${KVM_EXTERNAL_IP} ansible_user=ubuntu ansible_ssh_private_key_file=${APP_REPO}/.scm-local/gcp/scm-kvm-operator_ed25519 gpus=0
EOF

ssh_ready=0
for attempt in $(seq 1 30); do
  if ssh \
    -i "$APP_REPO/.scm-local/gcp/scm-kvm-operator_ed25519" \
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    -o ConnectTimeout=10 \
    "ubuntu@${KVM_EXTERNAL_IP}" \
    'cloud-init status --wait >/dev/null'; then
    ssh_ready=1
    break
  fi
  sleep 10
done
test "$ssh_ready" -eq 1

cd compute-provisioning-iac

ANSIBLE_CONFIG=ansible/ansible.cfg \
  ansible-galaxy collection install -r ansible/requirements.yml

ANSIBLE_CONFIG=ansible/ansible.cfg \
  ansible -i "$APP_REPO/.scm-local/gcp/kvm-hosts.ini" \
  "$KVM_HOST_ALIAS" -m ping

ANSIBLE_CONFIG=ansible/ansible.cfg \
  ansible-playbook \
  -i "$APP_REPO/.scm-local/gcp/kvm-hosts.ini" \
  ansible/playbooks/host-kit/vm-setup.yaml \
  --limit "$KVM_HOST_ALIAS" \
  -e image_setup_type=scratch \
  -e "vm_ssh_authorized_key=${PROVISIONING_PUBKEY}" \
  -e vm_ssh_key_user=ubuntu

ANSIBLE_CONFIG=ansible/ansible.cfg \
  ./scripts/run_acceptance_validation.sh \
  --inventory "$APP_REPO/.scm-local/gcp/kvm-hosts.ini" \
  --kvm-host "$KVM_HOST_ALIAS" \
  --vm-image-type scratch
```

Do not continue until the acceptance run can create, check, destroy, and
undefine a nested VM on the GCE host.

## 23. Real Provisioning Cutover

This changes application runtime state from mock provisioning to real
provisioning. Leave the port-forward running after the readiness check; sections
24 and 25 use the same local provisioning API endpoint.

```bash
cd "$OPS_REPO"

helm upgrade --install "$RELEASE" "$APP_REPO/helm" \
  --values "$APP_REPO/helm/values.yaml" \
  --values "$OPS_REPO/helm/argocd-apps/envs/dev/simple-market-service-values.yaml" \
  --set provisioning.mockMode=false \
  --set storefront.agents[0].config.seller.provisioning.mode=real \
  --namespace default \
  --wait \
  --timeout 10m

for deployment in "${RELEASE}-provisioning" "${RELEASE}-storefront-arkhai"; do
  kubectl rollout restart "deploy/${deployment}" -n default
  kubectl rollout status "deploy/${deployment}" -n default --timeout=10m
done

ACTIVE_PROFILES="$(kubectl exec deploy/"${RELEASE}-provisioning" -n default -- printenv ACTIVE_PROFILES)"
printf '%s\n' "$ACTIVE_PROFILES"
case ",${ACTIVE_PROFILES}," in
  *,mock,*) echo "ERROR: provisioning is still in mock mode"; exit 1 ;;
esac

make forward ENV="$ENV"
curl -sf http://localhost:8081/api/v1/system/ansible/readiness \
  | tee /tmp/scm-ansible-readiness.json \
  | jq
jq -e '.ansible_mode == "real" and .playbook.exists == true' \
  /tmp/scm-ansible-readiness.json
```

## 24. Provisioning Host Registration And Capacity

This section assumes the `make forward` port-forward from section 23 is still
running.

```bash
curl -sf http://localhost:8081/health | jq

cat >/tmp/scm-gcp-host.json <<EOF
{
  "name":"${KVM_HOST_ALIAS}",
  "kvm_host":"${KVM_EXTERNAL_IP}",
  "ssh_user":"ubuntu",
  "ssh_key_type":"path",
  "ssh_key_value":"/home/appuser/.ssh/id_ed25519",
  "gpu_count":0,
  "enabled":true
}
EOF

register_status="$(curl -sS -o /tmp/scm-host-register.json -w '%{http_code}' \
  -X POST http://localhost:8081/api/v1/hosts/ \
  -H 'Content-Type: application/json' \
  --data @/tmp/scm-gcp-host.json)"

cat /tmp/scm-host-register.json | jq

if [ "$register_status" = "409" ]; then
  curl -sf -X PUT "http://localhost:8081/api/v1/hosts/${KVM_HOST_ALIAS}" \
    -H 'Content-Type: application/json' \
    -d "{
      \"kvm_host\":\"${KVM_EXTERNAL_IP}\",
      \"ssh_user\":\"ubuntu\",
      \"ssh_key_type\":\"path\",
      \"ssh_key_value\":\"/home/appuser/.ssh/id_ed25519\",
      \"gpu_count\":0
    }" | jq

  curl -sf -X POST "http://localhost:8081/api/v1/hosts/${KVM_HOST_ALIAS}/enable" | jq
elif [ "$register_status" != "201" ]; then
  exit 1
fi

curl -sf "http://localhost:8081/api/v1/hosts/${KVM_HOST_ALIAS}" | jq
curl -sf "http://localhost:8081/api/v1/hosts/${KVM_HOST_ALIAS}/connectivity" \
  | tee /tmp/scm-host-connectivity.json \
  | jq
jq -e '.reachable == true' /tmp/scm-host-connectivity.json
```

Submit a capacity check and poll the job:

```bash
CAPACITY_JOB_ID="$(curl -sf "http://localhost:8081/api/v1/hosts/${KVM_HOST_ALIAS}/capacity" | jq -r '.job_id')"

while true; do
  curl -sf "http://localhost:8081/api/v1/jobs/${CAPACITY_JOB_ID}" | tee /tmp/scm-capacity-job.json | jq
  status="$(jq -r '.status' /tmp/scm-capacity-job.json)"
  case "$status" in succeeded|failed|cancelled) break ;; esac
  sleep 5
done
test "$status" = succeeded

curl -sf "http://localhost:8081/api/v1/jobs/${CAPACITY_JOB_ID}/logs" | jq -r '.logs'
```

## 25. Provisioning VM Lifecycle Proof

This is the end-to-end provisioning API proof against the registered GCE KVM
host.

```bash
export SELLER_AGENT_ID=eip155:31337:0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC:1
export BUYER_AGENT_ID=eip155:31337:0x70997970C51812dc3A010C7d01b50e0d17dc79C8:2
export PROOF_VM_NAME=gcp-proof-vm-01

CREATE_JOB_ID="$(curl -sf -X POST "http://localhost:8081/api/v1/hosts/${KVM_HOST_ALIAS}/vms/" \
  -H 'Content-Type: application/json' \
  -H "X-Agent-ID: ${SELLER_AGENT_ID}" \
  -d "{
    \"vm_target\":\"${PROOF_VM_NAME}\",
    \"image_setup_type\":\"scratch\",
    \"vm_ram\":2048,
    \"vm_vcpus\":2,
    \"vm_disk_size\":\"20G\",
    \"buyer_agent_id\":\"${BUYER_AGENT_ID}\"
  }" | jq -r '.job_id')"

while true; do
  curl -sf "http://localhost:8081/api/v1/jobs/${CREATE_JOB_ID}" | tee /tmp/scm-create-job.json | jq
  status="$(jq -r '.status' /tmp/scm-create-job.json)"
  case "$status" in succeeded|failed|cancelled) break ;; esac
  sleep 10
done
test "$status" = succeeded

curl -sf "http://localhost:8081/api/v1/jobs/${CREATE_JOB_ID}/logs" | jq -r '.logs'
curl -sf "http://localhost:8081/api/v1/jobs/${CREATE_JOB_ID}/credentials" \
  -H "X-Agent-ID: ${SELLER_AGENT_ID}" | jq
curl -sf "http://localhost:8081/api/v1/jobs/${CREATE_JOB_ID}/credentials" \
  -H "X-Agent-ID: ${BUYER_AGENT_ID}" \
  | tee /tmp/scm-buyer-credentials.json \
  | jq
curl -sf "http://localhost:8081/api/v1/jobs/${CREATE_JOB_ID}" \
  | tee /tmp/scm-create-job-final.json \
  | jq '.result'
```

Use the returned SSH command or credentials to verify buyer access to the nested
VM. Then prove the lease-end cleanup path by scheduling expiry through the
provisioning API and watching the host-side cleanup remove the libvirt domain.

```bash
LEASE_END_UTC="$(date -u -d '+10 minutes' '+%Y-%m-%d %H:%M')"

EXPIRY_JOB_ID="$(curl -sf -X POST "http://localhost:8081/api/v1/hosts/${KVM_HOST_ALIAS}/vms/${PROOF_VM_NAME}/expiry" \
  -H 'Content-Type: application/json' \
  -H "X-Agent-ID: ${SELLER_AGENT_ID}" \
  -d "{
    \"vm_expiry_at\":\"${LEASE_END_UTC}\",
    \"buyer_agent_id\":\"${BUYER_AGENT_ID}\"
  }" | jq -r '.job_id')"

while true; do
  curl -sf "http://localhost:8081/api/v1/jobs/${EXPIRY_JOB_ID}" | tee /tmp/scm-expiry-job.json | jq
  status="$(jq -r '.status' /tmp/scm-expiry-job.json)"
  case "$status" in succeeded|failed|cancelled) break ;; esac
  sleep 5
done
test "$status" = succeeded

curl -sf "http://localhost:8081/api/v1/jobs/${EXPIRY_JOB_ID}/logs" | jq -r '.logs'

ssh -i "$APP_REPO/.scm-local/gcp/scm-kvm-operator_ed25519" \
  -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null \
  "ubuntu@${KVM_EXTERNAL_IP}" \
  "atq; sudo cat /var/log/vm-lease-end/${PROOF_VM_NAME}/scheduled_info.txt"

cleanup_done=0
for attempt in $(seq 1 30); do
  if ssh -i "$APP_REPO/.scm-local/gcp/scm-kvm-operator_ed25519" \
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    "ubuntu@${KVM_EXTERNAL_IP}" \
    "sudo virsh dominfo '${PROOF_VM_NAME}' >/dev/null 2>&1"; then
    sleep 30
  else
    cleanup_done=1
    break
  fi
done
test "$cleanup_done" -eq 1

ssh -i "$APP_REPO/.scm-local/gcp/scm-kvm-operator_ed25519" \
  -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null \
  "ubuntu@${KVM_EXTERNAL_IP}" \
  "sudo sh -c 'tail -n +1 /var/log/vm-lease-end/${PROOF_VM_NAME}/lease_end_*.log'"
```

## 26. Restore And Cleanup

Run this when the proof is complete. If you want to keep testing real
provisioning, leave this section for later.

```bash
cd "$OPS_REPO"

make forward ENV="$ENV"
curl -sf -X POST "http://localhost:8081/api/v1/hosts/${KVM_HOST_ALIAS}/disable" | jq || true
make unforward

helm upgrade --install "$RELEASE" "$APP_REPO/helm" \
  --values "$APP_REPO/helm/values.yaml" \
  --values "$OPS_REPO/helm/argocd-apps/envs/dev/simple-market-service-values.yaml" \
  --namespace default \
  --wait \
  --timeout 10m

for deployment in "${RELEASE}-provisioning" "${RELEASE}-storefront-arkhai"; do
  kubectl rollout restart "deploy/${deployment}" -n default
  kubectl rollout status "deploy/${deployment}" -n default --timeout=10m
done

kubectl exec deploy/"${RELEASE}-provisioning" -n default -- printenv ACTIVE_PROFILES

gcloud compute instances delete "$KVM_VM_NAME" \
  --project "$GCP_PROJECT" \
  --zone "$ZONE"

gcloud compute addresses delete "$KVM_ADDRESS_NAME" \
  --project "$GCP_PROJECT" \
  --region "$REGION"

gcloud compute firewall-rules delete "${KVM_VM_NAME}-ssh" \
  --project "$GCP_PROJECT"

gcloud compute firewall-rules delete "${KVM_VM_NAME}-buyer-dnat" \
  --project "$GCP_PROJECT"

rm -f "$APP_REPO/.scm-local/gcp/scm-kvm-operator_ed25519" \
      "$APP_REPO/.scm-local/gcp/scm-kvm-operator_ed25519.pub" \
      "$APP_REPO/.scm-local/gcp/kvm-host-ssh-keys" \
      "$APP_REPO/.scm-local/gcp/kvm-hosts.ini"
```
