# Buyer quickstart

Install the `market` CLI, point it at a listing registry, find a listing, buy
compute, and SSH into the leased VM.

For the seller side see [`seller-quickstart.md`](./seller-quickstart.md).

## Supported settlement methods

The buyer supports Alkahest escrow settlement.

| Mechanism | Buyer payment choices | Buyer requirements |
|---|---|---|
| Alkahest (`alkahest.v1`) | The exact chain/asset/escrow option advertised by the listing | An EVM wallet, RPC-backed chain configuration, gas, and the advertised asset. |


## Prerequisites

- Linux or macOS (Windows: WSL).
- Python 3.12+.
- A public marketplace identity plus matching signing material injected through
  `ARKHAI_IDENTITY_CREDENTIAL`.
- An SSH keypair for leased VMs:

  ```bash
  ssh-keygen -t ed25519 -N "" -f ~/.ssh/mms_buyer_id_ed25519
  ```

  The pubkey gets injected into every VM you lease via cloud-init.
- For `alkahest.v1`, configure an EVM wallet, an RPC-backed chain, and the
  deployed Alkahest address file. Fund the wallet with gas and the advertised
  token.

## 1. Install

From PyPI (lightest — just the buyer CLI). The `market` console script
ships in `arkhai-core-buyer`; `arkhai-vms-buyer` adds the VM-compute
plugin:

```bash
uv tool install arkhai-core-buyer --with arkhai-vms-buyer
```

Released build (latest):

```bash
curl -fsSL https://github.com/arkhai-io/simple-compute-market/releases/latest/download/install.sh | bash
```

Installs `market` into `~/.local/bin`. The installer uses `uv` to provision
the Python version required by the buyer CLI; a literal `python3.12` system
command is not required. Pin a version with
`... | bash -s -- --version market-cli-v0.5.3`.

In noninteractive Linux environments, allow apt dependency installation
explicitly:

```bash
curl -fsSL https://github.com/arkhai-io/simple-compute-market/releases/latest/download/install.sh \
  | MARKET_INSTALL_ASSUME_YES=1 bash
```

Or from the repo:

```bash
git clone https://github.com/arkhai-io/simple-compute-market.git
cd simple-compute-market
make build-buyer
export PATH="$PWD/domains/vms/buyer/.venv/bin:$PATH"
market --version
```

## 2. Configure

`market` keeps public buyer configuration under `~/.config/arkhai` and durable
profile metadata under `$XDG_DATA_HOME/arkhai/buyer/profiles.json` (normally
`~/.local/share/arkhai/buyer/profiles.json`). Generate the role template, then
create or import one profile:

```bash
market config init-user
# Desktop: generate Ed25519 material into the OS keyring.
market profile create --name personal --provider os-keyring \
  --reference arkhai/buyer/personal --scheme ed25519 --generate

# Headless: first create an owner-only regular secret file, then:
market profile create --name automation --provider secret-file \
  --reference /run/secrets/arkhai/buyer-credential --scheme ed25519

# Alkahest users additionally render independent wallet/chain inputs:
market config init-user --include-evm-resources
```

`market profile list|show|select|rotate|retire|delete` manages only public
metadata and redacted references. There is no provider fallback: keyring,
strict file, and an explicitly named environment variable are distinct choices.
Set `[provisioning].ssh_public_key`, `[registry].urls`, and each signed registry
authority pin in public config. Never put a seed or marketplace private key in
TOML.

Settlement mechanisms are explicit and disabled by default.

An Alkahest buyer enables and prioritizes `alkahest.v1`, supplies
`[Settlement.alkahest].address_config_path`, and fills the generated `[Wallet]`
and `[Chains.<name>]` tables. Enabling a mechanism does not make an incompatible
listing selectable; discovery still requires one advertised compatible option.

Import a legacy `[Identity]` explicitly before removing it. The credential must
derive the exact configured principal; preview validates every conflict without
writing, and an exact rerun converges:

```bash
market profile import ~/.config/arkhai/legacy-buyer.toml --name personal \
  --provider secret-file --reference /run/secrets/arkhai/buyer-credential --check
market profile import ~/.config/arkhai/legacy-buyer.toml --name personal \
  --provider secret-file --reference /run/secrets/arkhai/buyer-credential
market config migrate --scope settlement --check
market config migrate --scope settlement --write --backup
```

## 3. Browse and explain

The resource-query language is typed by each registry's active filter
specification. The settlement language is evaluated buyer-side over advertised
options. One `--settlement` occurrence is a conjunction over one option;
repeated occurrences are alternatives in command order.

```bash
market listing list
market listing list --resource 'gpu_model=H200 gpu_count>=1'
market listing list \
  --resource 'gpu_model=H200' \
  --settlement 'mechanism=alkahest.v1 alkahest.chain=base_sepolia'
market listing list --resource 'gpu_model=H200' --explain
market listing show <listing_id>
```

`list` queries every compatible URL in `[registry].urls` in parallel and
deduplicates by listing ID. `--explain` reports canonical registry predicates,
local settlement constraints, survivor counts, and sanitized rejection
categories, then stops before negotiation or settlement.

## 4. Buy

```bash
market buy \
  --resource 'gpu_model=H200 gpu_count>=1' \
  --settlement 'mechanism=alkahest.v1 alkahest.chain=base_sepolia' \
  --duration-hours 1 \
  --settlement-timeout 1800 \
  --yes
```

The CLI filters resources first, selects one compatible advertised settlement
option, negotiates, persists the exact accepted option, starts that mechanism,
and polls until the seller returns `status: ready` with VM credentials.

Useful inputs:

- `--resource` — one filter-spec-typed conjunction. Unknown fields and
  unsupported operators fail before the listing query.
- repeatable `--settlement` — ordered pre-acceptance alternatives. It never
  enables a mechanism or authorizes recovery-time failover.
- `--initial-price` / `--max-price` — negotiation-policy rate bounds. Omit both
  to use the seller's advertised rate.
- `--settlement-timeout` — default 600s. Real cloud-init can take 5–10 minutes.

The terminal output includes a `Connection` block. Use the `vm_host_ip`
field (the printed `ssh_command` references the inventory alias, not the
DNS name):

```bash
ssh -i ~/.ssh/mms_buyer_id_ed25519 -p <port> tenant<id>@<vm_host_ip>
```

## 5. Resume an interrupted buy

Every `market buy` writes a JSONL run log at
`~/.local/state/arkhai/buy-runs/<run_id>.jsonl`:

```bash
market logs runs                  # list past runs + last status
market logs show <run_id>         # full event log for one run
market buy --from <run_id>        # resume from wherever the run stopped
```

`buy --from` reads `buyer_profile_id` and the canonical principal from run-log
version 3, then resolves that exact retained signer. Changing the selected
profile or rotating the primary affects only fresh work. A predecessor cannot
be retired while a recoverable run still needs it.
`market settle --from <run_id>` is the narrower accepted-settlement resume path;
it derives mechanism and chain/token metadata from the run.

If `buy` crashed after an accepted settlement was created, **always resume**.
Starting a new buy can create a second commercial commitment or lock more funds.

## 6. Service and reclaim

Run the mechanism-neutral service loop for heartbeats and expiry recovery:

```bash
market service --from <run_id>
```

Raw Alkahest inspection and mutation utilities are intentionally namespaced:

```bash
market settlement alkahest escrow show --escrow-uid <escrow_uid>
market settlement alkahest escrow reclaim --escrow-uid <escrow_uid>
market settlement alkahest chain check
```


## Common pitfalls

- **Resource and settlement constraints are different layers.** A successful
  registry resource query can still produce zero compatible settlement
  options; `--explain` distinguishes the two outcomes.
- **Every settlement predicate in one clause matches one option.** Fields from
  separate settlement options are never combined to satisfy a clause.
- **Accepted settlement never follows current priority.** Resume the existing
  run; changing `[Settlement].priority` does not redirect it.
- **Prices on the CLI are human asset units.** Publication normalizes each
  mechanism's explicit asset-scoped rate exactly once. Negotiation logs retain
  canonical values required by the accepted plan.
- **VM SSH uses `vm_host_ip`, not the alias** the `ssh_command` field
  prints (`tenant<id>@kvm1` etc. — the host name is the seller's
  inventory alias, not DNS).
- **The tenant user has no sudo password.** Cloud-init only injects
  your SSH pubkey.
- **`[registry.auth]` keys must match `[registry] urls` exactly** —
  scheme, host, port, no trailing slash. Mismatch silently sends
  unauthenticated requests, you get 401s.
- **Do not restore `[Identity]` after import.** Buyer commands reject it; select
  a durable profile and recover forward with retained principal history.
