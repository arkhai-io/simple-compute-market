# arkhai-e2e-tests

End-to-end integration tests for Arkhai deployed blockchain environments.
Tests run against live (or local) EVM-compatible nodes and validate contract
state and wallet configuration for each target environment.

---

## Quick start

```bash
# 1. First build/init and install the full stack. A local cluster uses the
#    local overlay, so uninstalling discards the release's state
#    (docs/development/DEPLOYMENT_AND_CONFIG.md, "Stateful service persistence").
make build
make -C helm deploy-local

# 2. Run tests against local Anvil node.
make test ACTIVE_PROFILES=local
```

---

## Configuration system

Configuration is managed by [dynaconf](https://www.dynaconf.com/) and layered
from multiple sources.

### Resolution order

Highest priority wins.

| Priority | Source | Example |
|----------|--------|---------|
| 1 | `ARKHAI_*` environment variables | `ARKHAI_RPC__URL=https://…` |
| 2 | `config-<profile>.yml` files (secrets injected here) |
| 3 | `config.yml` (in `CONFIG_DIRECTORY`) | base env config |
| 4 | `.env` file | local development overrides |
| 5 | `.secrets.toml` | local secrets (gitignored) |
| 6 | `settings.toml` | project defaults / schema |

### Config directory and profiles

These environment variables affect which config files are loaded.

```
CONFIG_DIRECTORY=/path/to/config    # directory containing config.yml
ACTIVE_PROFILES=staging,secrets     # comma-separated; files loaded in order
```

The loader merges `config.yml` first, then each `config-<profile>.yml` in the
order listed in `ACTIVE_PROFILES`.  This lets you stack a base environment
profile with a separate secrets-only profile:

```bash
ACTIVE_PROFILES=staging,staging-secrets
# loads: config.yml → config-staging.yml → config-staging-secrets.yml
```

### Shared payment-scenario configuration

The API-credit payment scenario reads the `PAYMENTS` section (environment
prefix `ARKHAI_PAYMENTS__`) through `tests/e2e/roles/helpers/payments.py`, which
other payment scenarios may reuse. SERVICE_URL names the payments target; leave
it blank and the scenario reports `blocked` and skips. With it set, supply the
other five: SERVICE_IDENTITY (public Ed25519 receipt signer), DISPUTE_AUTHORITY,
BUYER_ACCOUNT, BUYER_MARKETPLACE_CREDENTIAL and SELLER_MARKETPLACE_CREDENTIAL;
a missing one fails the scenario, naming it. Marketplace credentials are
independent of payment account IDs.

FEE_BPS defaults to 250. LIVEMODE and DEVELOPMENT_AUTH default to false and
must be `true` or `false`; generated buyer tables explicitly pin the receipt
mode. Choose either DEVELOPMENT_AUTH=true (literal loopback service URL only) or
API_KEY_ENV naming the buyer's bearer-key environment variable, never both.
Forward the named variable into the test runner yourself; host environment
variables are not inherited by the buyer-machine container.

An unreachable or unready `/health` also reports `blocked` and skips; invalid
policy fails rather than selecting another settlement mechanism. The shared
serializer writes only a named payments table — `Settlement.arkhai_payments`,
or `bare_metal.arkhai_payments`, which it supports for a bare-metal buyer — and
the scenario supplies domain settings and payer.
See [Private Service Dependencies](../docs/development/TESTING.md#private-service-dependencies)
for the public testing boundary.

### Secret injection (Kubernetes / Vault)

In a Kubernetes environment, mount secrets as a file into `CONFIG_DIRECTORY`:

```yaml
# deployment.yaml (excerpt)
volumes:
  - name: e2e-secrets
    secret:
      secretName: arkhai-e2e-staging-secrets
volumeMounts:
  - name: e2e-secrets
    mountPath: /etc/arkhai-config/config-staging-secrets.yml
    subPath: config-staging-secrets.yml

env:
  - name: CONFIG_DIRECTORY
    value: /etc/arkhai-config
  - name: ACTIVE_PROFILES
    value: staging,staging-secrets
```

The mounted file only needs to contain the keys it overrides:

```yaml
# config-staging-secrets.yml (mounted by k8s secret)
buyer:
  private_key: "0x..."
seller:
  private_key: "0x..."
```

For Vault, use the Vault Agent sidecar to render the same file from a template.

### All configuration keys

```yaml
rpc:
  url: "http://localhost:8545"   # RPC HTTP or WebSocket endpoint
  chain_id: 31337                # must match the actual chain
  timeout_seconds: 30
  retry_attempts: 3
  retry_backoff_seconds: 2

registry:
  identity_address:   ""         # deployed IdentityRegistry contract
  reputation_address: ""         # deployed ReputationRegistry contract
  validation_address: ""         # deployed ValidationRegistry contract
  owner_address:      ""         # expected owner() of all three contracts

buyer:
  private_key:    ""             # hex private key (with or without 0x)
  wallet_address: ""             # checksummed Ethereum address

seller:
  private_key:    ""
  wallet_address: ""

tests:
  minimum_eth_balance: "0.01"   # wallets must hold more than this (ETH)
  gas_price_strategy: "medium"
  require_checksummed_addresses: true
```

Any key can be overridden via an env var using `ARKHAI_` prefix and `__` as
the nested separator:

```bash
ARKHAI_RPC__URL=https://mainnet.infura.io/v3/YOUR_KEY
ARKHAI_REGISTRY__IDENTITY_ADDRESS=0xabc…
ARKHAI_BUYER__PRIVATE_KEY=0xdeadbeef…
```

---

## Running tests

### Make targets

```bash
make test                          # all tests, ACTIVE_PROFILES=local
make test-ci                       # all tests + HTML report (for CI)
make test-module                   # limits tests tagged as that module (usually a single test file)

# Override profile and config dir
make test ACTIVE_PROFILES=staging CONFIG_DIRECTORY=/mnt/e2e-config

# Pass extra pytest args
make test PYTEST_ARGS="-k test_contract_owner -v --tb=long"
```

### E2E mock provisioning tests

These targets spin up the full docker-compose stack, wait for services to be
ready (including on-chain agent registration), run the tests, then tear down.

```bash
make e2e-mock-happy       # deal lifecycle: create → negotiate → escrow → fulfill → arbitrate → close
make e2e-mock-failure     # provisioning fails → orders reopen
```

Each target uses the CLI (`market listing create`, `market listing history`,
`market listing show --negotiation --credentials --show-password`) to drive
order creation and inspect results. CLI output is captured in the pytest log.

To run against an already-running stack without lifecycle management:

```bash
ACTIVE_PROFILES=local,e2e-mock uv run pytest -m mock_provisioning_happy -v --tb=long
```

---

### Bare-metal payment deal

The bare-metal lane includes marker `e2e_bare_metal_payment_deal`.
With payments configured, run its three ordered calls against the ready lane:

```sh
make test-buyer-machine \
  NETWORK=simple-market-bare-metal_default \
  BUYER_MODULE=e2e_bare_metal_payment_deal
```

Supply the shared PAYMENTS settings in the runner's config directory, plus
SELLER_ACCOUNT, COMPUTE_HOURLY_GROSS=1000000 and DISPUTE_WINDOW=P7D. The seller
must enable the same payments policy and trust its service identity.
SELLER_MARKETPLACE_CREDENTIAL must resolve to the lane's pinned seller scheme;
the purchase buyer is a separate wallet-free Ed25519 profile. An unconfigured
public CI run reports a named blocked payments prerequisite, not success.

The fixture declares a distinct backed whole host and publishes only a
USD 1.00/hour option for a one-hour term. The installed
`market bare-metal buy` emits `run_started → agreement_accepted → payment_approved → run_ended(status=agreed)`.
Delivery reads use that purchase's signer and fulfillment transport.
Re-drive recovers the original run's retained profile and calls the shared
`settle_agreement` client, keeping both transaction and fulfillment unchanged;
there is no bare-metal settle command. Seller refund reverses the held once
payment, then a separate buyer teardown converges mock reclaim and site capacity
release. If a call fails before the refund call finishes, the module's cleanup
finds the purchase in the buyer's run log; when the log records the payment
approved, it refunds the payment (a repeat refund returns the same result) and
releases the host if one was delivered. It then removes its mock rules, drains,
and removes its pool override, and resumes the loops it paused last. Each step is
attempted even after an earlier one fails, and the failures are reported together;
mock-rule removal ignores a rule that is already gone.
This is mock grant/reclaim evidence, not SSH qualification. The canonical
Alkahest mock-deal scenario remains selected unchanged.

## CI/CD

The GitHub Actions workflow at `.github/workflows/e2e.yml` can be triggered:

- **Manually** via `workflow_dispatch` — choose profile and optional pytest args
- **On a schedule** — nightly at 02:00 UTC against staging

Secrets are passed from the GitHub environment and written into a
`config-<profile>.yml` file in a temporary runtime config directory,
matching the same mechanism used in Kubernetes deployments.

Test reports are uploaded as workflow artefacts and retained for 30 days.

---

## Adding tests

1. Create `tests/test_<feature>.py`
2. Import fixtures from `conftest.py` (`w3`, `registry_settings`, etc.)
3. Mark tests with `@pytest.mark.contracts`, `@pytest.mark.wallets`, or add a
   new marker in `pyproject.toml` under `[tool.pytest.ini_options] markers`
4. Add helper utilities to `tests/helpers/` if they are reusable

```python
# tests/test_example.py
import pytest

@pytest.mark.contracts
def test_my_new_check(w3, registry_settings):
    address = registry_settings["identity_address"]
    # ... your assertions
```
