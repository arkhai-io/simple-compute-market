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

Settlement mechanisms are explicit and disabled by default. A hosted-only
buyer uses:

```toml
[Settlement]
schema_version = 1
priority = ["fiat.stripe.v1"]

[Settlement.stripe]
enabled = true
# Set the hosted base URL, authority/environment, exact signed manifest,
# client/API 0.2.0/schema 5 and capability pins, USD/US policy, and
# [Settlement.stripe.authority].principals.

[Settlement.alkahest]
enabled = false
```

The selected durable marketplace profile must also have an active opaque payer
binding for that exact hosted authority/environment. The binding contains no
provider customer, instrument, mandate, or payment data. A saved instrument is
selected only for the current direct authorization call and is never stored in
TOML or the run log.

Create and manage that opaque binding through the direct, signer-authenticated
payer namespace:

```bash
market settlement stripe payer create --country US
market settlement stripe payer show
market settlement stripe payer setup start \
  --funding-profile card.v1 --label primary-card --action open
market settlement stripe payer setup status SETUP_REF --action open
market settlement stripe payer instrument list
market settlement stripe payer instrument default INSTRUMENT_REF
```

Saved setup accepts `card.v1` and `us_ach_debit.v1`; push
`us_bank_transfer.v1` remains purchase-interactive. Use `instrument revoke` or
`instrument delete` for the same opaque `INSTRUMENT_REF`. After a proven local
profile rotation, `payer owner rotate` proves both retained signers; retire an
old hosted owner with `payer owner retire --principal scheme:identifier`.
`payer delete` deletes the hosted profile and retires the local binding. Add
`--json` for the safe projection and `--action open|print|fail` for transient
setup actions; neither output stores action values or payment data.

An Alkahest buyer instead enables and prioritizes `alkahest.v1`, supplies
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
  --resource 'gpu_model in [H200,H100] region=us-east' \
  --settlement 'mechanism=fiat.stripe.v1 asset=usd stripe.funding_profile=card.v1 stripe.interaction=interactive'
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
  --settlement 'mechanism=fiat.stripe.v1 asset=usd stripe.funding_profile=card.v1 stripe.interaction=interactive' \
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

`buy --from` reads `buyer_profile_id` and the canonical principal from run-log
version 3, then resolves that exact retained signer. Changing the selected
profile or rotating the primary affects only fresh work. A predecessor cannot
be retired while a recoverable run or hosted payer binding still needs it.
`market settle --from <run_id>` is the narrower accepted-settlement resume path;
it derives mechanism, chain/token metadata, and action handling from the run.

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

## Hosted funding profiles

When a listing advertises `fiat.stripe.v1`, constrain one exact option with a
clause such as `mechanism=fiat.stripe.v1 asset=usd
stripe.funding_profile=card.v1 stripe.interaction=interactive`. The other
initial profiles are `us_bank_transfer.v1` and `us_ach_debit.v1`; they remain
distinct choices even when price and condition match.

Discovery uses the listing plus selected-profile readiness and performs no
hosted mutation. After seller-accepted terms are durable, the CLI obtains one
exact purchase authorization directly from the hosted authority using the
selected or recorded marketplace signer, then starts, polls, and reclaims the
obligation only through the seller storefront. The run log keeps the exact
profile and opaque authorization/settlement references, never the payer or
saved-instrument reference.

Use `--action open` for interactive setup/payment/confirmation or bank
instructions, `--action print` to hand the transient action to an external
automation boundary, or `--action fail` when interaction is forbidden. Pending
push transfer or ACH availability remains pending until authoritative funded
state; displaying instructions or completing a redirect does not imply VM
fulfillment. The run log keeps only safe public reason/deadline/action
kind/expiry metadata and never an action URL, client secret, bank detail, or
provider payload. Resume the accepted run to retrieve current state and action.

## Buy API credits with hosted funding

The API-credit buyer uses the same selected durable profile and hosted policy.
It filters exact listing options before negotiation, then revalidates service,
quantity, key mode/key ID, parties, currency, profile, and condition from the
accepted seller state before authorization:

```bash
market credits buy \
  --service-name vllm-chat \
  --quantity 10 \
  --new-key \
  --funding-profile card.v1 \
  --action open \
  --yes
```

The returned API credential is buyer-only output, not hosted settlement
evidence. Resume a recorded pending purchase with
`market credits settle-status RUN_ID`; use
`market credits settle-reclaim RUN_ID --reason expired` only when issuance did
not commit. For an existing-key top-up, replace `--new-key` with
`--existing-key KEY_ID`; another marketplace principal is rejected by the
credits authority. Hosted-only API-credit commands do not require wallet,
chain, RPC, or gas configuration.

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
- **Do not restore `[Identity]` after import.** Buyer commands reject it; select
  a durable profile and recover forward with retained principal history.
