# arkhai-e2e-tests

End-to-end integration tests for Arkhai deployed blockchain environments.
Tests run against live (or local) EVM-compatible nodes and validate contract
state and wallet configuration for each target environment.

---

## Quick start

```bash
# 1. First build/init and install the full stack
make build
make deploy

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

---

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
