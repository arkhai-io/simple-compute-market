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

## Running The Local Pass

No script in this repository runs the local pass: sections 1 to 14 are the
procedure, run by hand and in order. Section 5's Ansible validation and Helm
render are optional and need their tools; section 8's volume ownership fix
applies only when a storefront exits with a SQLite error; and section 13's
single-pass sweep is optional, since it reruns stack-mutating tests after the
marker-specific runs.

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
and values, and the directory there holding its component validators, which
this repository does not ship; the GCP project and region, the Helm release,
and the values files that repository keeps for the application-resources chart
and for this repository's chart. Each command stops, naming the variable, while
one is unset. The braced group resolves the two directories to absolute paths
and stops as a whole, naming the variable, while either is unset or is not a
directory, so neither is exported empty.

```bash
export APP_REPO="$(pwd)"
{
  : "${OPS_REPO:?set OPS_REPO to your operations repository checkout}"
  : "${OPS_VALIDATORS:?set OPS_VALIDATORS to the component-validator directory of the operations repository}"
  OPS_REPO="$(cd "$OPS_REPO" && pwd)"
  export OPS_REPO="${OPS_REPO:?set OPS_REPO to an existing directory}"
  OPS_VALIDATORS="$(cd "$OPS_VALIDATORS" && pwd)"
  export OPS_VALIDATORS="${OPS_VALIDATORS:?set OPS_VALIDATORS to an existing directory}"
}

export ENV="${ENV:-dev}"
export GCP_PROJECT="${GCP_PROJECT:?set GCP_PROJECT to your GCP project ID}"
export REGION="${REGION:?set REGION to your GCP region}"

export RELEASE="${RELEASE:?set RELEASE to your Helm release name}"
export OPS_APPS_CHART="${OPS_APPS_CHART:?set OPS_APPS_CHART to the application-resources chart of the operations repository}"
export OPS_APPS_VALUES="${OPS_APPS_VALUES:?set OPS_APPS_VALUES to the values of that chart for this environment}"
export OPS_APP_VALUES="${OPS_APP_VALUES:?set OPS_APP_VALUES to the application chart values for this environment}"
```

Keep apostrophes out of those messages: bash reads a quote inside `${...}` as
opening a quoted string even within double quotes. Keep each check outside a
command substitution, too: a failure inside `$(...)` does not stop the shell,
and `export` reports success whatever the substitution returned.

Sanity-check the branch and sibling repo. The validator loop only reports, on
standard error, each validator missing from `$OPS_VALIDATORS`; it stops nothing:

```bash
git status --short --branch
test -d "$OPS_REPO"
git -C "$OPS_REPO" status --short --branch

for validator in tfstate artifact-registry networking gke secrets api-gateway; do
  test -f "$OPS_VALIDATORS/$validator.sh" || echo "missing: $OPS_VALIDATORS/$validator.sh" >&2
done

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
do not run the `api-gateway` validator until section 20; that validator
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
bash "$OPS_VALIDATORS/tfstate.sh" "$ENV"
```

Use component validators as you go. Do not use full `make validate-env` as an
early gate; it checks resources that do not exist until later in this sequence.

```bash
make tf-init  ENV="$ENV" COMPONENT=artifact-registry
make tf-apply ENV="$ENV" COMPONENT=artifact-registry
bash "$OPS_VALIDATORS/artifact-registry.sh" "$ENV"

make tf-init  ENV="$ENV" COMPONENT=networking
make tf-apply ENV="$ENV" COMPONENT=networking
bash "$OPS_VALIDATORS/networking.sh" "$ENV"

make tf-init  ENV="$ENV" COMPONENT=gke
make tf-apply ENV="$ENV" COMPONENT=gke
make get-credentials ENV="$ENV"
bash "$OPS_VALIDATORS/gke.sh" "$ENV"

make tf-init  ENV="$ENV" COMPONENT=secret-shells
make tf-apply ENV="$ENV" COMPONENT=secret-shells
bash "$OPS_VALIDATORS/secrets.sh" "$ENV"

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
bash "$OPS_VALIDATORS/api-gateway.sh" "$ENV"
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

<a id="21-provide-a-kvm-host"></a>

## 21. Provide Real Compute Hosts

Sections 21 to 26 are the operator procedure around the real-provisioning
scenarios, `e2e_vm_real_provisioning` and
`e2e_bare_metal_real_provisioning`. From the operator's machine the VM lane
registers the host and its capacity through the
provisioning service's signed admin API, runs the canonical compute deal to an
active lease, reaches the delivered VM over SSH, expires the lease, and confirms
the VM is gone from the host and its access has ended.
[`TESTING.md`](TESTING.md#the-real-provisioning-lane) says what it proves and
what it does not.

A VM host needs:

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
- buyer reachability either through direct forwarded guest SSH ports, or
  through the registered buyer relay's allocation window. Management SSH stays
  separate from the buyer endpoint.

Decide what the host sells: its vCPUs, memory in GiB, and disk in GiB, less
what is kept for the host itself. The VM listing shape must fit twice within
that capacity for the two-guest
coexistence check. A bare-metal target instead offers the whole declared machine,
needs no KVM, and must provide an operator-verified SSH host public key. Prepare
it using the [bare-metal seller guide](../bare-metal-seller-quickstart.md#define-the-selected-site).
Before either relayed lane, complete the deployed admission check in section 28.

For a bounded bare-metal working-data policy, prepare its state and cleanup
roots on the selected host before installing policy. Run the operator-only
`bare-metal-working-data` host-preparation role with its explicit initialization
setting once, then preserve the ledger across service restore and image redeploy.
Do not initialize during grant or reclaim. A known or suspected older-ledger
restore requires host quarantine until history is verified or the host is
decommissioned; the helper cannot detect valid structural rollback.

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
- run the controlled Anvil settlement chain and trust the selected fixture
  marketplace principals. External profiles may use Ed25519 marketplace signing
  independently of their Anvil wallet. Configure role credentials and matching
  trust pins explicitly; see [marketplace and EVM fixture inputs](../../e2e-tests/README.md#marketplace-signing-and-controlled-evm-settlement).
  The `local` profile contains well-known development identities; never expose
  them on a public network.

Mock delivery is never reported as real: the scenario's first check reads the
provisioning service's executors and requires the selected lane's executor reported real,
failing with the executors it found before anything is held or registered.

## 24. Describe The Target

```bash
(
  cd e2e-tests/config || exit 1
  example=config-real-provisioning-target.yml.example
  cp "$example" "${example%.example}"
)
```

The copy is the committed example's name without `.example`,
`config-real-provisioning-target.yml`, which the `real-provisioning-target` profile loads from the
e2e config directory. Set `REAL_PROVISIONING_TARGET.version: 2` and add a
VM entry under `hosts`:

- `domain: vm` and `host_id`, the identifier the scenario registers;
- `connection.ssh_host`, `ssh_user`, `ssh_port`, and `ssh_key_path`, where the
  provisioning service connects and section 23's service-local key path;
- `access: {mode: direct, public_host: <buyer-address>}` for forwarded guest
  ports, or `access: {mode: relay, relay_id: <configured-relay-id>}`. A
  relayed run requires an enabled relay with a token and active grant key;
- `capacity`, the sellable `vcpu_count`, `ram_gb`, and `disk_gb` from section 21;
- `listing_shape`, an explicit guest shape fitting twice within that capacity.

A bare-metal entry uses `domain: bare_metal`, adds `physical_host_id` and its
operator-verified `ssh_host_public_key`, and omits `listing_shape`. At most one
host per domain is allowed. Direct and relay access fields cannot be mixed.
The target names no relay token or grant key and carries no private host key.

The scenario registers its host with an `ssh` connection at version 2, naming
`connection.ssh_key_path` as the service's `key_path`. It reconciles an earlier
registration with the target; the key itself remains in the service filesystem.
Git ignores the real target file; never commit it. The model in
`e2e-tests/src/e2e_harness/real_provisioning_target.py` documents the fields.
Missing, misspelled, foreign or unknown fields fail before scenario mutation;
version 1 fails with conversion instructions rather than being interpreted.

## 25. Run The Real-Provisioning Scenario

Forward the stack's chain, registry, storefront, and provisioning service to the
ports the `local` profile names (8545, 8080, 8001, and 8081), then, from the
repository root:

```bash
make -C e2e-tests test-module MODULE=e2e_vm_real_provisioning ACTIVE_PROFILES=local,real-provisioning-target
# Run the separate bare-metal lane against its configured BARE_METAL_LANE services:
make -C e2e-tests test-module MODULE=e2e_bare_metal_real_provisioning ACTIVE_PROFILES=local,real-provisioning-target
```

The bounded helper gates are separate from deployed lifecycle evidence. Run
`make test-bare-metal-iac` for helper unit/library integration tests and
`make build-provisioning` followed by `make test-bare-metal-iac-native`
for the isolated native filesystem, NSS and IPC gate. A skipped or unavailable
native prerequisite fails that dedicated gate. Deployed qualification must separately prove an actual grant/reclaim, cleanup
observations and successor access; it does not prove valid older-ledger rollback
detection. A mock deal, helper tests, or force-release cannot replace that
evidence. A refused cleanup keeps capacity held
until normal retry or separately audited operator recovery.

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

The lane keeps the first guest's SSH heartbeat process open while a second guest
is created and removed, requiring no observed gap over five seconds. It checks
management connectivity before and after both guests' create and teardown, and
checks released relay holdings without requiring immediate reuse during grant
quarantine. Both guests need no GPU; this proves tunnel coexistence, not a GPU
rental.

A failed run attempts normal lifecycle cleanup for both accepted settlements,
even if one recovery fails. Unconfirmed cleanup names each escrow, negotiation,
fulfillment, reservation, job, VM and host that an operator must recover.

The bare-metal lane instead checks the pinned host key, accepted buyer key and
unrelated-key refusal; expiry must complete reclaim, end delivered access and
restore capacity. Management connectivity must survive. Unreachable SSH is not
proof of successful revocation. Its relay port may remain quarantined after
capacity is released. An absent target skips before mutation; skipped stages
are not qualification evidence.

## 26. Restore And Cleanup

The scenario leaves its pool, host, capacity declaration, and listing in place,
and the next run reconciles them; nothing is deleted from the provisioning
service. Return the stack to mock provisioning by redeploying it with its
default values (`provisioning.mockMode=true`). Once the host is no longer
needed, delete the local files and release the host, and the network openings
section 21 made, wherever it was provided:

```bash
rm -f /tmp/kvm-hosts.ini
(
  cd e2e-tests/config || exit 1
  example=config-real-provisioning-target.yml.example
  rm -f "${example%.example}"
)
```


## 27. Running Live Lanes

A live lane is a test-mode purchase through the buyer commands on a physical host,
from a validated candidate: a whole bare-metal machine, or a guest on a VM host.

**Lanes on separate machines run in parallel.** Their capacity cannot overlap. What
they share is this repository's source, its wheelhouse and environments, and the
images built from them, so changes to those stay serialized: no lane's run rebuilds or
reinstalls what another lane is running on.

**Lanes sharing a machine run in sequence.** A whole-host bare-metal deal and a VM on
the same machine are admitted by different provisioning services, and cross-mode
accounting does not span them. Two lanes whose sources are one machine therefore run
one at a time. The idle lane's listings are held by each listing's durable pause
(`pause_listing`, `POST /api/v1/listings/{id}/pause`), which keeps them open and
published and survives a restart that keeps the storefront's database, though not a
database reset. A pause refuses only a new opening on its listing. A counter or accept
on a thread opened before it, settlement, fulfillment, and teardown all proceed, so a
pause drains nothing.

It relies on one precondition that no permanent requirement states: a publication
refresh or reopen under the same listing identity keeps its pause. A listing bound
under a new derivation key — a corrected declaration or shape, a new member, a changed
hint or override, a new site — is created unpaused.

Before each lane's purchase, and after any restart or redeploy of the idle side,
re-check from fresh read-backs:

1. **Freeze.** Make no change to the idle side's capacity declarations, pools, hints,
   overrides, or sites until the switch completes, so no unpaused listing is bound.
2. **Pause.** Pause every idle-lane listing on the shared machine, and read each back
   open and paused, and open at its registry.
3. **No unpaused listing.** No open listing for the machine on the idle storefront is
   unpaused.
4. **No open negotiation.** No thread on those listings is still open; the negotiation
   watchdog abandons a stale one after its timeout.
5. **Every accepted deal drained.** For every accepted deal on those listings:
   - its settlement and fulfillment are terminal;
   - its site reservation is `released`, or force-released after verification;
   - every provider job for it is terminal;
   - its host-side effects are verified removed: the tenant key and account for bare
     metal, the guest and its artifacts for VM. For VM, verify before any
     force-release that no `frpc-buyers.toml.reload-pending.vm-<guest>` record is left beside
     the VM tunnel client's configuration, and that the running client's status lists
     no `vm-<guest>` proxy;
   - no approved receipt or recorded materialization remains that could still start a
     delivery.

   Check a refund or expired approval as the financial disposition too, but never take
   either as proof of a drain.
6. **Site drained.** At the idle lane's site, no reservation for the machine is in a
   state the site counts as holding capacity: `reserved`, `leased`, `releasing`,
   `release_failed`, or `unmanaged` (`HELD_RESERVATION_STATES` in
   `kit/site/src/market_site/db.py`). In the site's resource-pool projection, every
   member on the machine has an `available` mapping equal to its declared `capacity`
   mapping, dimension by dimension. Neither the lease list, which omits a hold with no
   lease window, nor the scalar `available_units`, which reads only the mirror
   dimension, is enough.
7. **Then the active lane.** Only then may the active lane's listing trade.

If a condition cannot be met — a reset database, an unpaused successor listing, work
that cannot be drained, or a deployment without the pause — stop the lane switch at
that boundary. Take no shortcut.


## 28. Prepare And Operate Buyer Relays

Use a buyer-only relay per operator, distinct from any management relay. Buyer
frps and frpc use the verified **0.61.1** pin. The family installs binaries at
`/usr/local/lib/frp/0.61.1/{frps,frpc}` after checking the archive SHA-256.
The default archive is linux_amd64; another platform requires an operator-supplied
version-specific archive URL and independently verified digest in `frp_archives`,
with the corresponding `frp_platform`. Never substitute an unchecked download.

A shared relay has one client token, so rotating it affects every operator's
hosts; restarting frps to end one operator's sessions interrupts everyone.
Assign each operator a distinct issuer/key and nonoverlapping port range. Keep
management ports on another relay. Its management client's admin API must be off
or authenticated. The buyer client is `frpc-buyers`, not a management client;
its loopback admin API uses a privileged port and a generated per-host password
in root-only configuration. See [seller relay setup](../seller-frp-setup.md).

### Establish the signing authority

Create a relay definition in the operator's mounted document, before its pools
reference it. The service's `relay_definitions_path` names the document. The
following names and address are invented documentation placeholders:

```yaml
relays:
  - id: example-buyer-relay
    relay_addr: relay.example.com
    relay_port: 7000
    vm_port_range_start: 6100
    vm_port_range_count: 100
    token_secret_key: EXAMPLE_RELAY_TOKEN
    grant_key_secret_key: EXAMPLE_RELAY_GRANT_KEY
    enabled: true
```

Keep both values in the private secrets profile, never in the definition document
or repository. Generate a distinct token with `openssl rand -base64 32` and an
Ed25519 private key with the following command, directing its output straight into
an owner-readable secret file/profile rather than a terminal or log:

```bash
openssl genpkey -algorithm ed25519 -outform DER | base64 -w0
```

The profile value is single-line standard base64 PKCS#8 DER. Definitions read it
only when creating a relay; editing a profile does not rotate an existing key.
`GET /api/v1/relays/{relay_id}` returns `grant_keys.active.public_key` as standard
base64 DER SubjectPublicKeyInfo and its `kid`, plus staged/retired key metadata;
it never returns private keys or tokens. Send administrator operations through
the signed provisioning client, not unauthenticated curl. A relay created via
`POST /api/v1/relays/` generates its key inside the service; that private key
survives only with its database. An operator-retained profile key supports an
empty-database reinstall without changing the plugin's trusted public key.

Build plugin TOML using the schema in
[`tools/frp-grant-admission/README.md`](../../tools/frp-grant-admission/README.md#configuration).
Replace every published example key; those are deterministic RFC test values,
never deployment keys. Set `listen` to numeric loopback (for example
`127.0.0.1:7300`). For each relay, configure an issuer whose `audience` equals
its relay id, whose inclusive `ports` contains the entire allocation window,
and whose `keys` contains the relay's public key. Issuer ranges cannot overlap
and must fit inside frps's `allowPorts`. To onboard another site to a shared
relay, assign its range first and add its public key under its own issuer;
check the complete file before reload.

Keep the provisioning service and relay clocks synchronized. Their worst skew
must remain below `relay_port_reuse_margin_seconds`; grant time checks have no
leeway. Monitor synchronization, rather than treating successful HTTP health as
clock evidence.

### Native systemd relay

The family `relay-server` role takes a supplied wheel, hash-pinned runtime
requirements and plugin TOML. Build/export them from the same tool revision:

```bash
make -C tools/frp-grant-admission build
(cd tools/frp-grant-admission && uv export --frozen --no-dev --no-emit-project --output-file dist/requirements.txt)
```

Keep the TOML and inventory outside the repository. Supply controller-local
absolute paths as `frp_grant_admission_wheel`,
`frp_grant_admission_requirements` and `frp_grant_admission_config`, together with
`frp_auth_token`, `frp_proxy_ports` and the relay inventory's `relay_servers`
group. The controller needs the supported Ansible environment and the
`community.general` collection (including its `ufw` module). From
`provisioning/compute/iac`:

```bash
ANSIBLE_ROLES_PATH="$PWD/ansible/roles" ansible-playbook \
  -i <operator-inventory> ansible/playbooks/relay-server.yaml \
  --extra-vars @<owner-readable-relay-vars.yml>
```

The relay needs Python 3.11 or later with venv/pip support. The role never
builds or fetches the plugin: it installs exported dependencies with
`--require-hashes --only-binary=:all:` and the supplied wheel with `--no-deps`.
The wheel is an operator-trusted input, not independently authenticated by its
content fingerprint. The program release is
`/opt/frp-grant-admission/releases/<wheel-sha256>-<requirements-sha256>`;
`/opt/frp-grant-admission/current` selects the checked release. A success receipt
allows reuse; old releases are retained. Do not mutate a selected release.

The candidate program checks private staged TOML with
`frp-grant-admission check <path>`, then publishes those exact bytes to
`/etc/frp-grant-admission/config.toml` and switches `current`. Invalid TOML
preserves active configuration and program selection. The program runs as its
own non-root account/group `frp-grant-admission`, with login disabled, no
home created and no supplementary groups; the role refuses root or an existing UID/GID 0 identity.
The config is root-owned, group-readable mode 0640 in a protected 0750 directory.

A changed program/unit restarts the plugin. A config-only issuer/key/range
change HUP-reloads an already-running unchanged program without restarting
frps. Initial/program startup does not immediately send HUP. The role waits for
the listener before preparing frps. frps's first plugin entry requires one
restart: drain existing leases before introducing it to an active relay.

An ordinary role run refuses an existing listener change before publishing
configuration or switching `current`. HUP retains the bound socket. To relocate
the native listener, stop admission and drain all affected leases, stop both
services, preserve the old protected configuration/program selection, and
perform an explicit operator-managed reinstallation with the new listener and
matching frps entry. Verify both services and admission before reopening. This
is separate maintenance, not an automatic role/API migration. Do not delete
active configuration simply to bypass the refusal during normal operation.

### Container relay

Use the plugin image built from its Dockerfile and pin the deployment reference
to the intended revision/immutable digest. Run it as a sidecar in frps's network
namespace: the same Kubernetes pod, Compose `network_mode: service:frps`, or
explicit host networking. Mount its configuration directory read-only at `/etc/frp-grant-admission`
so replacing `config.toml` is visible on reload; do not publish its loopback
port externally. The image entrypoint is `frp-grant-admission`; its default
arguments are `serve --config /etc/frp-grant-admission/config.toml`.
Check candidate TOML with the same image's `frp-grant-admission check <path>`
before replacing the mounted file and sending the plugin process SIGHUP. A
file bind mount must actually expose the replacement bytes; verify this rather
than assuming a host-side rename updates an existing mount.

Use the upstream frps image at version 0.61.1, with matching `allowPorts`, token,
and this entry in its protected `frps.toml`:

```toml
[[httpPlugins]]
name = "grant-admission"
addr = "127.0.0.1:7300"
path = "/"
ops = ["NewProxy"]
```

There is no repository frps deployment manifest to apply. The operator supplies
the deployment, namespace and image reference. Wait for the plugin listener,
then start frps. Changes to frps configuration/version require a drained restart;
changes to plugin issuer/key/range configuration use HUP. Listener relocation
requires drained coordinated restart and a matching frps address.

Native installer tests exercise installation/config publication and syntax in
disposable fixtures. A container campaign proves its actual image/namespace
path. Neither is proof of the other deployment path, and neither alone proves
a real buyer's purchase, SSH access and successful reclaim.

### Prove admission before enabling a pool

Before the first buyer, and after each plugin configuration change:

1. Check the configuration, record its issuer ranges and public-key thumbprints,
   and verify the deployed frps plugin entry addresses the running loopback
   listener in the same namespace.
2. Using the pinned frpc and the real relay token in an owner-only temporary
   configuration, request one TCP proxy on an unused assigned port, with
   **no** `metadatas.grant`. Use a unique probe name, no load-balancer group,
   and a harmless loopback destination. Never reuse a tenant's port.
3. Run that temporary client against the deployed frps. Require a registration
   refusal carrying `grant_missing` and the matching plugin JSON log entry with
   `event: refuse` and `reason: grant_missing`. A connection failure or token
   authentication failure is not admission proof. Confirm no proxy was installed.
4. Stop the probe, remove its temporary secret-bearing config, and retain only
   sanitized evidence. If a proxy was admitted, keep buyer admission closed.

A minimal probe configuration has this shape; all names/address below are
documentation placeholders. Replace the port with an unused assigned port and
the token with the real token in an owner-only temporary file:

```toml
serverAddr = "relay.example.com"
serverPort = 7000
auth.method = "token"
auth.token = "<private-relay-token>"

[[proxies]]
name = "example-ungranted-probe"
type = "tcp"
localIP = "127.0.0.1"
localPort = 22
remotePort = 6100
```

Run the verified `frpc -c <private-probe-config>` in the foreground; terminate it
after observing the refusal. Do not use a production tenant port.

The tool's `make -C tools/frp-grant-admission test-frp` exercises real binaries
in its own fixture; it does not perform this deployed-relay check.

### Rotate keys and change admission policy

Generate the next private key into the private profile and point the relay
entry's `grant_key_secret_key` at that retained value. Send it as `private_key`
to signed `POST /api/v1/relays/{relay_id}/grant-keys/stage`. Read the staged
public key, add it alongside the active key in the issuer's TOML, check/reload
and verify admission, then call signed
`POST /api/v1/relays/{relay_id}/grant-keys/activate`. If staging omits the
private key the service generates one, which survives only with its database;
do not imply that the profile now contains it.
When an empty-database reinstall must retain the plugin's trust, keep the
operator-supplied key in the deployment profile and keep `grant_key_secret_key`
pointed at it; definitions are read on creation, while a later API rotation is
not reverted by reconciliation. Retain a retired public key until its reported
grant-validity bound has passed.

Read retired keys' `grants_valid_until`. Match a key by the thumbprint printed
by `frp-grant-admission check <path>`; remove it only once that time has passed,
or is null because no unreleased lease remains. Drain affected grants before
narrowing a range, removing an issuer/key, or changing an audience. A registered
proxy is not rechecked until registration/reconnect: HUP is not revocation.
Adding a key/issuer or widening a range is non-destructive, but still requires
the deployed refusal check.

For a compromised signing key, choose explicitly: remove it immediately and
refuse affected tenants at their next reconnect until their leases end, or keep
it through lease drain while the attacker can sign within that issuer's range
and audience. Neither choice reissues live grants. A leaked client token has no
live-rotation shortcut: stop new admission, drain every lease across all
operators sharing it, rotate the token on frps and every client baseline, then
verify before reopening. Coordinated live credential reissue is not provided.

### Contain access when teardown cannot reach a host

If the operator can reach the host, `sudo systemctl disable --now frpc-buyers`
ends all buyer relay access from that host. Recover and reclaim the tenant
normally; stopping the tunnel alone does not terminate host-local activity.
If the host is unreachable, the relay operator must block the leased port at
the relay firewall and end established sockets in frps's network namespace:

```bash
ss -K state established '( sport = :<leased-port> )'
```

This needs `NET_ADMIN` in that namespace; on Kubernetes use an appropriately
privileged ephemeral debug container. Verify both new traffic denial and
established connection termination. If socket destruction is unavailable,
restart frps after installing the block; that interrupts every tenant on that
relay. If only frps configuration is controllable, remove the affected port
from `allowPorts` and restart frps, again accounting for the shared disruption.

Record the port, lease/reservation identity and grant expiry in private incident
state. Keep the block until grant expiry has passed **and** the old registration
has cleared. Port quarantine/expiry alone does not remove an already registered
proxy. Do not remove a block while it is the only containment. On a managed
shared relay, the site operator supplies the affected lease/port/expiry and
requests containment; the relay operator applies and verifies it and reports
when safe to lift. Relay containment ends only that route: full revocation
still requires host recovery, activity termination and verified reclaim.

For diagnostics, correlate a verified plugin log line's `jti` (the reservation
identity) with `GET /api/v1/relays/{relay_id}/leases` while the port row still
represents that tenancy. After port-row reuse, read
`GET /api/v1/contract/leases/{jti}` through the signed client. Unverified log
claims are sender-controlled; do not treat them as authenticated identities.


## 29. Qualify an ordinary Arkhai purchase

Keep buyer and operator identities separate. Use the shipped buyer CLI for every customer action and the signed typed compute-provisioning client for independent host, job, lease, and reservation observations. The operator client takes a base URL, signer, caller role, and expected authority; keep its credential material outside the buyer configuration. Bind the frozen source, selected artifacts, and public configuration identity to each run in restricted evidence.

Before rollout, check the rebuilt consumer against both the currently deployed payment authority responses and the selected publication. If one check is reused for both, establish that the contracts are identical; if they differ, record a compatible rollout order before making a change. Separately verify retained historical signed bytes. Do not deploy or downgrade the authority to match the consumer.

Prove genuine TEST funding at its authority before buying, then correlate the funding evidence with the accepted Agreement, signed receipt, and attributable rental charge. Existing unexplained credit does not prove funding. Serialize or independently attribute payment observations when physical lanes overlap; retain transaction and Agreement identifiers with the evidence.

For a bare-metal buyer, inspect supported syntax and discover a candidate through the CLI:

```bash
market --help
market --config <buyer.toml> bare-metal list --config <buyer.toml>
market --config <buyer.toml> bare-metal show <listing-id> --config <buyer.toml>
```

The root and bare-metal commands load their configuration separately, so these examples supply the same profile at both scopes. Select one advertised Arkhai payment option, prepare the tenant's public SSH key, then use the ordinary buy command. It emits a run identifier and transaction/fulfillment information for follow-up:

```bash
market --config <buyer.toml> bare-metal buy <listing-id> \
  --config <buyer.toml> \
  --option-id <option-id> \
  --ssh-public-key <tenant-public-key> \
  --duration-seconds <duration>
```

For VM buyer flows, use `market listing list` and `market listing show <listing-id>`, then inspect `market buy --help`; the VM plugin's ordinary `market buy` discovers and negotiates from the configured typed resource and settlement selections. Record the emitted buyer run ID and accepted transaction/fulfillment identifiers rather than constructing a second scenario client.

Using the operator's `SyncComputeProvisioningClient`, take typed pre-run reads with `list_hosts()`, `list_leases()`, and `list_jobs()`. Correlate the returned reservation and job identifiers, then use `get_lease(reservation_id)` and `get_job(job_id)` to observe the create/release lifecycle. On the buyer side, retain the actual result and authorized access views; for bare metal, the supported recovery reads are:

```bash
market --config <buyer.toml> bare-metal result --run-id <run-id> --config <buyer.toml>
market --config <buyer.toml> bare-metal access --run-id <run-id> --config <buyer.toml>
```

Check the delivered host key, tenant identity and privilege, wrong-key refusal, and the workload on the paid guest. After the ordinary lease expires, independently observe successful teardown, absence of the guest/access, and restored capacity. A bare-metal buyer can request the ordinary teardown/recovery path with:

```bash
market --config <buyer.toml> bare-metal teardown --run-id <run-id> --config <buyer.toml>
```

Do not equate an accepted receipt with successful delivery or a payment hold with a refund. Keep raw authority responses and deployment data restricted; publish sanitized findings and explicit unrun items. A supplemental network-policy result is admissible only from an actual operator-only CPU guest on the same paid deployment, with the pinned guest base, actual default bridge and virtio NIC, and loaded policy structure bound to that deployment. A namespace-only probe is not a substitute. That guest proves only finite policy selectors it exercises and none of the paid tenant's identity, payment, grant, GPU, delivery, or lifecycle facts. Reusing this method does not claim that an older named marker ran.

### Observations the qualification owes

One ordinary purchase does not qualify real provisioning. Each observation below is owed. A failed observation is recorded as failed; a skipped or unavailable one is recorded as unproven. Neither is inferred from another observation, and its owning check stays open. Mock, native-component, helper, and historical results never stand in for a missing hardware observation.

Before the first destructive cycle, freeze the source candidate and have it independently reviewed and fully validated; bind each cycle to that candidate and its unchanged configuration. The negative admission checks of observation 1 precede any real tenant. Keep the offers closed to general buyers until a paid purchase as described above, with checked GPU work, has passed for each GPU offer, and observations 2, 4, and 5 have passed.

1. **Negative relay admission.** On each buyer relay, before the first paid tenant and after each plugin configuration change, run section 28's admission probe without a grant, then repeat it with a grant whose signature does not verify, a grant for a different port than the one requested, and a grant for a port outside the issuer's range. Expect the plugin's reason codes `grant_missing`, `signature_invalid`, `port_mismatch`, and `port_outside_range` respectively ([reason codes](../../tools/frp-grant-admission/README.md#reason-codes)), each as a registration refusal with the matching plugin `refuse` log entry, no proxy installed, and no connection reaching the backend. Request only ports frps itself allows, so the refusal comes from the plugin rather than from frps. A valid grant's admission is proven by the paid journey, not by this probe.
2. **Two concurrent VM deals.** Buy two CPU-only VMs through `market buy`, each with its own TEST payment. Keep an SSH heartbeat open on the first guest while the second is created and torn down, and apply section 25's criteria: no observed heartbeat gap over five seconds, both delivered shapes match their agreements, an unrelated key is refused, and each guest is removed and its access ended at teardown. In addition, let both leases expire naturally rather than tearing them down early. Check authenticated management connectivity and the management and libvirtd generations before, during, and after those operations; a restart or lost connection fails the observation. Deals driven through the typed operator clients instead of the buyer exercise the physical path but do not make this observation.
3. **Direct access.** Repeat the two-VM cycle over direct access, over an operator-routable test path, only in a controlled pool drained as section 27's steps 5 and 6 require and with no unreleased relay lease for the pool (`GET /api/v1/relays/{relay_id}/leases`). Host management stays unexposed, and a pool that retains an active reservation or relay holding is not rebound. Record the result as controlled-path evidence, distinct from external relay acceptance.
4. **Bare-metal normal cycle.** Buy a bare-metal GPU rental through the buyer and check the pinned relay endpoint, the nonroot tenant, GPU work, and wrong-key refusal. Through the bounded working-data probe, seed tenant activity (a shell, a process, a scheduled job) and working data (home, scratch, path, System V and POSIX IPC objects) beside operator sentinels. After ordinary reclaim, the covered activity, account, private group, data, and IPC are absent, the sentinels are unchanged, fresh access is denied, and capacity is restored.
5. **Bare-metal refusal and retry.** In a successor rental, confirm a fresh UID and key and no access to the predecessor's data. Plant one nonce-scoped descendant owned by another UID inside a tenant-owned directory that cleanup selects; a foreign entry at the top of a shared root is preserved rather than refused, so it proves nothing here. Ordinary reclaim must refuse it: the cleanup job is queued for retry, not terminal, with an error recorded, a retry count of at least one and within its maximum, and a next retry time set; its log names the foreign descendant; the lease stays `releasing` and its capacity is not advertised as available; and an actionable operator notification is emitted, recorded with where it was observed. Repair only that fixture before retries are exhausted; the same job then completes, the final inventory is clean, and the sentinels are unchanged. A forced release, a manual retry, or a reset of the consumed-UID history does not satisfy this observation, and a terminal failure stays a failure with audited recovery.
6. **Repeat registration and adoption.** Reapply the canonical VM and bare-metal registrations and run another publication cycle on the same stack. As in section 25's second run, existing listings are adopted with their identities, states, and pauses intact; no duplicate allocator, host, pool, resource, or listing appears; unexpired relay quarantine is retained; and the consumed-UID history is unchanged.

For each observation, correlate the buyer run, Agreement and receipt, reservation, provisioning jobs, and grant identifiers in restricted evidence. Relay port reuse follows grant expiry and quarantine while compute capacity follows verified teardown, so do not require an immediate port reuse.
