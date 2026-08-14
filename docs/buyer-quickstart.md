# Buyer quickstart

Install the `market` CLI, point it at a listing registry, find a listing, buy
compute, and SSH into the leased VM.

For the seller side see [`seller-quickstart.md`](./seller-quickstart.md).

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
- For hosted `fiat.stripe.v1`, the seller's listing and hosted authority provide
  the payment action; no buyer wallet, chain, RPC, gas, or token balance is
  required.
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

`market` reads `~/.config/arkhai/buyer.toml`. Generate the current typed
template, including optional EVM resources only when needed:

```bash
market config init-user
# Alkahest users:
market config init-user --include-evm-resources
```

Set `[Identity].scheme` and `[Identity].identifier` to the public principal
derived from `ARKHAI_IDENTITY_CREDENTIAL`, set
`[provisioning].ssh_public_key`, and configure `[registry].urls` plus each
registry authority pin. The generated template documents every field.

Settlement mechanisms are explicit and disabled by default. A hosted-only
buyer uses:

```toml
[Settlement]
schema_version = 1
priority = ["fiat.stripe.v1"]

[Settlement.stripe]
enabled = true
# Set the hosted base URL, authority/environment, signed manifest and API/schema
# pins, required capabilities, and [Settlement.stripe.authority].principals.

[Settlement.alkahest]
enabled = false
```

An Alkahest buyer instead enables and prioritizes `alkahest.v1`, supplies
`[Settlement.alkahest].address_config_path`, and fills the generated `[Wallet]`
and `[Chains.<name>]` tables. Enabling a mechanism does not make an incompatible
listing selectable; discovery still requires one advertised compatible option.

Preview and migrate a legacy buyer config explicitly:

```bash
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
  --resource 'gpu_model in [H200,H100] region=us-east' \
  --settlement 'mechanism=fiat.stripe.v1 asset=usd stripe.method=card'
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
  --settlement 'mechanism=fiat.stripe.v1 asset=usd stripe.method=card' \
  --duration-hours 1 \
  --initial-price 2 \
  --max-price 2 \
  --action print \
  --settlement-timeout 1800 \
  --yes
```

The CLI filters resources first, selects one compatible advertised settlement
option, negotiates, persists the exact accepted option, starts that mechanism,
and polls until the seller returns `status: ready` with VM credentials.
`--action open|print|fail` controls any transient buyer action on both fresh and
resumed runs. `open` uses the browser, `print` is automation-friendly, and
`fail` stops actionably while preserving resumable accepted state.

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

`buy --from` picks up the same run log at its last authoritative handoff.
`market settle --from <run_id>` is the narrower accepted-settlement resume path;
it derives mechanism, chain/token metadata, and action handling from the run and
typed configuration rather than accepting mechanism-specific overrides.

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

## Hosted Checkout settlement

When a listing advertises `fiat.stripe.v1`, constrain it with a settlement
clause such as `mechanism=fiat.stripe.v1 asset=usd stripe.method=card`.
Discovery and negotiation use listing data only; no hosted-provider mutation
occurs before seller acceptance. After acceptance, the CLI starts and polls the
obligation through the seller storefront, not through a buyer-configured
financial authority.

Use `--action open` for interactive Checkout, `--action print` to hand the
transient action to an external automation boundary, or `--action fail` when
interaction is forbidden. The run log retains only the opaque settlement
reference, lifecycle status, action kind, and expiry. It never retains an action
URL or payment data. Resume the accepted run to retrieve a current action.

## Common pitfalls

- **Resource and settlement constraints are different layers.** A successful
  registry resource query can still produce zero compatible settlement
  options; `--explain` distinguishes the two outcomes.
- **Every settlement predicate in one clause matches one option.** Fields from
  separate Stripe and Alkahest options are never combined to satisfy a clause.
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
