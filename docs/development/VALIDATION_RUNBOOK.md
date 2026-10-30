# Full Validation Runbook

Goal: run the code-level unit/integration tests, bring up the local deployed
stack in mock mode, optionally repeat the same manual path on a clean Ubuntu VM,
deploy to GCP, then prove real VM provisioning against an operator-provided KVM
host.

## Notes

- All commands assume the repo root unless a step explicitly changes
  directories.
- `make test-module MODULE=<marker>` in `e2e-tests/` runs
  `pytest -m <marker>`.
- High `deselected` counts are expected for marker-specific runs. Pytest
  discovers the whole `e2e-tests/tests/` tree, then runs only tests
  matching the requested marker.
- Run every compose command for the local stack through `$SCM_COMPOSE`
  (section 8): every one, `ps`, `logs`, and `down` included, needs the
  generated environment file and both market overlays, and the Redis port
  override when it is in use.
- Use `$SCM_COMPOSE down -v` only when intentionally wiping named volumes.
  Fresh storefront volumes currently need the ownership workaround below.
- Keep issue evidence in `.scm-local/notes/issue-notes.md`; this runbook is
  for repeatable execution.
- The issue-discovery harness is intentionally separate. Use
  `docs/development/ISSUE_DISCOVERY.md` when the goal is issue candidate generation and
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
    populated `agent_id`, `chain_id: 31337`, and every configured site's
    `site_projections` families `loaded`.
  - Provisioning `/api/v1/system/status` has `storefront: ok`,
    `storefront_auth: ok`, and `lease_watchdog: running`. Its
    `fulfillment_recovery` object reports sweep/claim/provider-failure counters,
    live and expired claims, retry age, and non-terminal lifecycle age. It must
    not contain credentials, provider metadata, or owner principals.

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
- `domains/vms/provisioning/iac` contract tests run by default because they do not
  require a live KVM host or Ansible inventory.
- Bob/Alice storefront named volumes are pre-chowned to UID/GID `1000:1000`
  before stack startup to avoid the known SQLite volume ownership failure.
- A quiet `anvil_dumpState` check runs after Anvil is reachable.
- Helm render validation runs automatically when `helm` is available.
- Compute-provisioning IAC validation runs automatically when Ansible tooling
  and the inventory directory `domains/vms/provisioning/iac/ansible/inventory/`
  (`hosts` and `provisioning-hosts.ini`) are available.
- The single-pass `e2e-tests make test` sweep is off by default because
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
make build-dev
```

Expected build products include `.dist/`, `shared-env/.env`,
`dev-env/state/state.json`, runtime Docker images, and dev/test Docker images
for the local stack.

## 4. Code-Level Tests

These are the architecture-defined unit and integration tests. They do not
require the compose stack to be running.

Root service suite:

```bash
make test
```

This runs unit + integration tests for:

- `provisioning/compute/service`
- `core/registry`
- `storefront`

Policy package:

```bash
cd kit/policy
uv sync --dev
uv run pytest tests/unit/ -v
cd ..
```

Buyer package:

```bash
cd domains/vms/buyer
make reinit
uv run pytest tests/ -v
make smoke-test
cd ../../..
```

Storefront client package:

```bash
cd core/storefront-client
uv sync --dev
uv run pytest tests/ -v
cd ../..
```

Compute provisioning IAC contract tests:

```bash
cd domains/vms/provisioning/iac
python3 -m unittest discover -s tests -p 'test_*.py' -v
cd ..
```

Integration-test harness unit tests:

```bash
cd e2e-tests
make reinit
.venv/bin/pytest tests/unit/ -v
cd ..
```

Current note:

- `core/registry-client/` currently has a `tests/` package but no `test_*.py`
  files, so there is no runnable registry-client test command at the moment.
- `infra/` currently has pytest dev dependencies but no `test_*.py` files, so
  there is no runnable infra package test command at the moment.

## 5. Optional Environment-Dependent Local Tests

Compute provisioning IAC inventory/playbook validation requires Ansible tooling
and the inventory directory `domains/vms/provisioning/iac/ansible/inventory/`:

```bash
cd domains/vms/provisioning/iac
make validate
cd ..
```

Do not run acceptance validation unless a real KVM host is configured:

```bash
cd domains/vms/provisioning/iac
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
The old `domains/vms/tests` integration suite was removed in the latest pull;
future training or RL validation should be documented separately when runnable
tests are added back.

## 6. Known Exclusions For Local Mock Validation

These are not covered by the standard local run above:

- `core/registry-client`: has a `tests/` package but currently no `test_*.py`
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
- `domains/vms/provisioning/iac make validate-acceptance`: requires a real KVM host
  and `KVM_HOST` set to an inventory alias.
- Policy training/RL behavior: no current standard local test command covers
  the training stack or trained model inference.
- Production/non-mock provisioning: the local mock path runs the provisioning
  services' mock profile, which `make e2e-dev-identities-env` selects by default
  (`PROVISIONING_MODE=mock`); real Ansible/KVM coverage starts in sections
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

The full stack needs its development bindings: the environment file the root
`Makefile` generates, which also selects the provisioning services' mock
profile, and both market overlays.

```bash
make -s --no-print-directory e2e-dev-identities-env > .e2e-identities.env
SCM_COMPOSE="docker compose --env-file .e2e-identities.env \
  -f docker-compose.yml -f compose.vms-local.yml -f compose.apicredits-local.yml \
  -f /tmp/scm-no-redis-port.yml"
$SCM_COMPOSE up -d
```

If `bob-storefront` or `alice-storefront` exit with SQLite DB errors, fix volume
ownership:

```bash
docker run --rm --user 0:0 \
  -v simple-compute-market_bob-storefront-data:/bob \
  -v simple-compute-market_alice-storefront-data:/alice \
  alpine:3.20 sh -c 'chown -R 1000:1000 /bob /alice'

$SCM_COMPOSE up -d bob-storefront alice-storefront
```

Watch startup:

```bash
$SCM_COMPOSE ps

$SCM_COMPOSE logs -f anvil registry bob-storefront alice-storefront provisioning
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

Dev-env state smoke, as a quieter equivalent of `cd dev-env && make smoke`:

```bash
curl -sf http://localhost:8545 -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"anvil_dumpState","params":[],"id":1}' \
  | jq -e '.result | type == "string" and length > 0'
```

Register mock `kvm1` if provisioning returns `{"hosts":[]}`:

```bash
curl -sf -X POST http://localhost:8081/api/v1/hosts/ \
  -H 'Content-Type: application/json' \
  -d '{"host_id":"kvm1","connection":{"kind":"ssh","version":2,"public":{"ssh_host":"127.0.0.1","ssh_user":"appuser","key_path":"/home/appuser/.ssh/id_ed25519"}},"enabled":true}' | jq
```

## 10. Failure Diagnostics

If compose startup fails, capture these before changing state:

```bash
$SCM_COMPOSE ps
$SCM_COMPOSE logs --tail=200
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
$SCM_COMPOSE logs --tail=200 bob-storefront alice-storefront
docker run --rm -v simple-compute-market_bob-storefront-data:/data alpine:3.20 ls -ldn /data
docker run --rm -v simple-compute-market_alice-storefront-data:/data alpine:3.20 ls -ldn /data
```

## 11. Deployment Smoke Tests

```bash
cd e2e-tests

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
test in `e2e-tests/tests/`. Run it before teardown and expect it to
rerun tests that mutate stack state:

```bash
make test ACTIVE_PROFILES=local
```

Prefer the marker-specific commands for diagnosis. They produce smaller,
clearer failures.

## 14. Teardown

```bash
cd ..
$SCM_COMPOSE down
```

Only wipe volumes intentionally:

```bash
$SCM_COMPOSE down -v
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
  --exclude='dev-env/state' \
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

Sections 17 to 20 deploy the stack to GCP in mock mode. Sections 21 to 26 then
prove real VM provisioning against one KVM host an operator provides, such as a
GCE VM created with nested virtualization; they need nothing GCP-specific.

Run the commands in one shell where possible. Later GCP sections reuse the
exported variables below.

Run from this repo first. Every value below is the operator's own: the
operations repository that holds the environment's Terraform, Makefile targets,
and values, the GCP project and region, the Helm release, and the values files
that repository keeps for the application-resources chart and for this
repository's chart. Each command stops, naming the variable, while one is unset.

```bash
export APP_REPO="$(pwd)"
export OPS_REPO="$(cd "${OPS_REPO:?set OPS_REPO to your operations repository checkout}" && pwd)"

export ENV="${ENV:-dev}"
export GCP_PROJECT="${GCP_PROJECT:?set GCP_PROJECT to your GCP project ID}"
export REGION="${REGION:?set REGION to your GCP region}"

export RELEASE="${RELEASE:?set RELEASE to your Helm release name}"
export OPS_APPS_CHART="${OPS_APPS_CHART:?set OPS_APPS_CHART to the operations repository's application-resources chart}"
export OPS_APPS_VALUES="${OPS_APPS_VALUES:?set OPS_APPS_VALUES to that chart's values for this environment}"
export OPS_APP_VALUES="${OPS_APP_VALUES:?set OPS_APP_VALUES to this environment's values for the application chart}"
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
`HOSTS_INI=/dev/null` is intentional: the real-provisioning scenario registers
its KVM host itself (section 25).
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
```

The storefront's Secret overlay is a `storefront.secrets.toml` written directly;
the chart renders no Secret of its own. Only the private key belongs there; the
public wallet address goes in the storefront agent's `config.Wallet.address`
values, which the chart renders into its public `storefront.json`.

```bash
(
  TMPDIR="$(mktemp -d)"
  trap 'rm -rf "$TMPDIR"' EXIT

  # A well-known Anvil development key, for the dev chain alone; never use it
  # on a public network.
  cat > "$TMPDIR/storefront.secrets.toml" <<'TOML'
[wallet]
private_key = "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"
TOML

  gcloud secrets versions add simple-market-service-storefront-arkhai \
    --data-file="$TMPDIR/storefront.secrets.toml" \
    --project="$GCP_PROJECT"
)
```

Build and push the runtime artifacts after Artifact Registry exists:

```bash
cd "$APP_REPO"

make build-dev
make push-runtime-artifacts AR_PROJECT="$GCP_PROJECT"
make push-dev-images AR_PROJECT="$GCP_PROJECT"
```

## 20. Kubernetes App Bootstrap In Mock Mode

The operations repository's application-resources chart (`$OPS_APPS_CHART`) owns
the application-side Kubernetes resources that sit on top of the platform:
ExternalSecrets, the Kong `Gateway`, HTTPRoutes, and the route ReferenceGrant. Patch the storefront ExternalSecret after install until
the ops repo template is updated to emit `storefront.secrets.toml`.

```bash
cd "$OPS_REPO"

INGRESS_IP="$(make --silent get-ingress-lb-ip ENV="$ENV")"

helm upgrade --install argocd-apps "$OPS_APPS_CHART" \
  --values "$OPS_APPS_VALUES" \
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
  "${RELEASE}-e2e-tests-e2e-secret"; do
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
not restart `dev-env` here unless you intentionally want to reset the dev
Anvil chain state.

```bash
helm upgrade --install "$RELEASE" "$APP_REPO/helm" \
  --values "$APP_REPO/helm/values.yaml" \
  --values "$OPS_APP_VALUES" \
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

### Settlement by introduction on a Helm release

`helm/fixtures/contact-exchange-values.yaml` overlays the default release so Bob's
storefront offers contact exchange, delivers each revealed buyer contact by SMTP,
and the `dev-env` chart runs Mailpit to receive it. It states only what differs
from Bob's default agent, since agents are keyed by name and Helm merges an
overlay into an agent key by key; layer your environment's values first if it
already redefines Bob. The fixture advertises Bob at the host port-forward URL
and gives capacity-backed test pools a contact-exchange settlement clause. Use
it only for a local Helm test release with the deterministic development
identities and existing chart Secrets.

```bash
make build-dev
make -C e2e-tests reinit
make -C helm template VALUES=fixtures/contact-exchange-values.yaml \
  > /tmp/arkhai-contact-exchange-rendered.yaml
make -C helm deploy VALUES=fixtures/contact-exchange-values.yaml NAMESPACE=default

# Confirm the Service names this release rendered before forwarding.
kubectl get svc -n default | grep -E "storefront-bob|registry|provisioning|mailpit"

kubectl port-forward -n default "svc/${RELEASE}-dev-env" 8545:8545 &
kubectl port-forward -n default "svc/${RELEASE}-storefront-bob" 8001:8001 &
kubectl port-forward -n default "svc/${RELEASE}-registry" 8080:8080 &
kubectl port-forward -n default "svc/${RELEASE}-provisioning" 8081:8081 &
kubectl port-forward -n default "svc/${RELEASE}-dev-env-mailpit" 8025:8025 &

make -C e2e-tests test-module MODULE=e2e_vm_introduction ACTIVE_PROFILES=local
```

The `local` profile addresses each service on `localhost` at those ports, and
reads Mailpit's API at `http://localhost:8025`. The scenario holds the
storefront's loops while it runs and resumes them when it finishes.

## 21. Provide A KVM Host

Sections 21 to 26 are the operator procedure around the real-provisioning
scenario, `e2e_vm_real_provisioning`, which is the proof itself: from the
operator's machine it registers the host and its capacity through the
provisioning service's signed admin API, runs the canonical compute deal to an
active lease, reaches the delivered VM over SSH, expires the lease, and confirms
the VM is gone from the host and its access has ended.
[`TESTING.md`](TESTING.md#the-real-provisioning-lane) says what it proves and
what it does not.

The host needs:

- hardware virtualization its operating system can see: the CPU flags include
  `vmx` or `svm`. Create a cloud instance with nested virtualization enabled.
  Host preparation refuses a host without it before changing anything;
- an x86-64 Ubuntu 24.04 install, the platform the scenario has run against,
  with outbound network access, which scratch-image VM creation uses to fetch
  its cloud image;
- no GPU. A host with an NVIDIA or AMD GPU is given passthrough boot
  configuration (section 22), and the scenario deals a GPU-less shape either
  way;
- SSH as one user with sudo, from the operator's machine to prepare it and from
  the provisioning service with the key the service holds;
- inbound TCP from the operator's machine to ports 10000–65000, where VM
  creation forwards each guest's SSH. The scenario connects to the guest
  through that port.

Decide what the host sells: its vCPUs, memory in GiB, and disk in GiB, less
what is kept for the host itself. The scenario deals all of it as one VM.

## 22. Prepare The Host

Prepare the host from the operator's machine with the host kit's
`vm-setup.yaml`, naming no image or passthrough option: preparation defaults to
the scratch image market fulfillment creates VMs from, and configures GPU
passthrough only where a GPU is present. The inventory is local to the
operator's machine and never committed. Start from this repository's root;
after sections 17 to 20 the shell is in the ops repo, and `cd "$APP_REPO"`
returns to it.

```bash
cd domains/vms/provisioning/iac

cat >/tmp/kvm-hosts.ini <<'EOF'
[kvm_hosts]
kvm-real-1 ansible_host=<host-address> ansible_user=<ssh-user> ansible_ssh_private_key_file=<operator-private-key>
EOF

ANSIBLE_CONFIG=ansible/ansible.cfg \
  ansible-galaxy collection install -r ansible/requirements.yml

ANSIBLE_CONFIG=ansible/ansible.cfg \
  ansible -i /tmp/kvm-hosts.ini kvm-real-1 -m ping

ANSIBLE_CONFIG=ansible/ansible.cfg \
  ansible-playbook \
  -i /tmp/kvm-hosts.ini \
  ansible/playbooks/host-kit/vm-setup.yaml \
  --limit kvm-real-1 \
  -e "vm_ssh_authorized_key=<provisioning-service-public-key>"

cd ../../../..
```

`vm_ssh_authorized_key` authorizes the provisioning service's key for the
connection user. Preparation reboots the host once. Then check that:

- the play recap shows `failed=0` and `ignored=0`;
- the play reports `GPU present: False` and `gpu_passthrough: auto`, and that
  passthrough boot configuration and binding were skipped, so the kernel
  command line is the one the host booted with;
- after the reboot `/dev/kvm` exists, and nested virtualization is on
  (`/sys/module/kvm_intel/parameters/nested`, or `kvm_amd`'s).

A host whose CPU exposes neither `vmx` nor `svm` fails at the start, before
anything on it changes, and one with no `/dev/kvm` once the KVM modules load
fails too. `gpu_passthrough=enabled` or `disabled` overrides the presence
decision, and `image_setup_type=golden` prepares the golden image; neither is
needed here. [The host kit's README](../../domains/vms/provisioning/iac/README.md#2-setup-kvm-host-infrastructure)
documents both.

## 23. Run Provisioning For Real

Deploy, or redeploy, the stack the scenario runs against with its provisioning
service outside the mock profile: on a Helm release, `provisioning.mockMode=false`,
which the umbrella chart's values set to `true`. The stack must also:

- give the provisioning service the private key whose public half section 22
  authorized, at a path in the service's filesystem; that path is the target's
  `ssh_key_path`;
- let the provisioning service reach the host's SSH;
- run the dev chain and trust the `local` profile's principals
  (`e2e-tests/config/config-local.yml`), which the scenario signs as. They are
  well-known development identities: never deploy them on a public network.

Mock delivery is never reported as real: the scenario's first check reads the
provisioning service's executors and requires its VM executor reported real,
failing with the executors it found before anything is held or registered.

## 24. Describe The Target

```bash
cp e2e-tests/config/config-real-vm-target.yml.example \
  e2e-tests/config/config-real-vm-target.yml
```

Fill in the copy's `REAL_VM_TARGET` section:

- `host_id`: the identifier the scenario registers the host under;
- `ssh_host`, `ssh_user`, `ssh_port`: where the provisioning service connects
  to the host;
- `ssh_key_path`: section 23's path;
- `public_host`: the host's address as the operator's machine reaches its
  forwarded guest ports;
- `capacity`: what section 21 decided the host sells, as `vcpu_count`,
  `ram_gb`, and `disk_gb`.

The scenario registers the host with an `ssh` connection at version 2, the only
version the provisioning service serves, naming `ssh_key_path` as its `key_path`
and `public_host` as the buyer-facing address. A run replaces the connection an
earlier registration left, so a host stored at an older version is moved forward;
the key itself stays in the service's filesystem and never enters the target.

`access.mode` stays `direct`, the only mode version 1 admits. Git ignores the
file; never commit it. The model in `e2e-tests/src/e2e_harness/real_vm_target.py`
documents every field, and the scenario refuses a missing, misspelled, or
unknown one, naming it, before anything else runs.

## 25. Run The Real-Provisioning Scenario

Forward the stack's chain, registry, storefront, and provisioning service to the
ports the `local` profile names (8545, 8080, 8001, and 8081), then, from the
repository root:

```bash
make -C e2e-tests test-module MODULE=e2e_vm_real_provisioning ACTIVE_PROFILES=local,real-vm-target
```

A run takes as long as a real create and teardown; each job is polled for up to
30 minutes. On a host that meets section 21 every stage passes and none skips,
and the log records:

- the provisioning service's VM executor reported real;
- the create and teardown jobs, each `succeeded` on the target host, and the
  guest's name;
- the delivered endpoint, the guest's host-key fingerprint, and the probed
  vCPUs, memory, and root disk beside the capacity sold (memory may read up to
  5% short);
- the unrelated key refused with `Permission denied`;
- a VM list on the host without the guest, and the delivered access no longer
  connecting.

A second run against the same stack passes too: it reconciles the host's
registration and adopts, paused, the listing the first run left, rather than
creating another. A listing on the scenario's resource that it cannot adopt —
several, a closed one, or one of another shape, as after the target's capacity
changes — fails the run naming them; rerun with the target they were made for,
or against a fresh stack.

A run that fails after its settlement was accepted expires its own deal's lease
so the provisioning service tears the VM down. Where it cannot confirm the VM
gone, it fails naming the escrow, negotiation, fulfillment, reservation, jobs,
VM, and host; recover that VM by hand from those names.

## 26. Restore And Cleanup

The scenario leaves its pool, host, capacity declaration, and listing in place,
and the next run reconciles them; nothing is deleted from the provisioning
service. Return the stack to mock provisioning by redeploying it with its
default values (`provisioning.mockMode=true`). Once the host is no longer
needed, delete the local files and release the host, and the network openings
section 21 made, wherever it was provided:

```bash
rm -f /tmp/kvm-hosts.ini
rm -f e2e-tests/config/config-real-vm-target.yml
```

