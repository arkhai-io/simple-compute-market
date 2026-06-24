# Buyer quickstart

Install the `market` CLI, point it at a listing registry, find a listing, buy
compute, and SSH into the leased VM.

For the seller side see [`seller-quickstart.md`](./seller-quickstart.md).

## Prerequisites

- Linux or macOS (Windows: WSL).
- Python 3.12+.
- A wallet on the EVM chain the seller publishes on, funded with gas
  plus whatever ERC-20 the seller accepts. Examples below use Base
  Sepolia + USDC at `0x036CbD53842c5426634e7929541eC2318f3dCF7e` (test
  funds from [faucet.circle.com](https://faucet.circle.com)); any EVM
  chain with Alkahest deployed works.
- An RPC URL for that chain.
- An SSH keypair for leased VMs:

  ```bash
  ssh-keygen -t ed25519 -N "" -f ~/.ssh/mms_buyer_id_ed25519
  ```

  The pubkey gets injected into every VM you lease via cloud-init.

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

`market` reads `~/.config/arkhai/buyer.toml`. Scaffold with
`market config init-user` or write directly:

```toml
[wallet]
private_key    = "0x<YOUR_BUYER_PRIVATE_KEY>"
ssh_public_key = "ssh-ed25519 AAAA...your-key buyer@host"

[chains.base_sepolia]
chain_id = 84532
rpc_url  = "https://sepolia.base.org"   # public RPC; or your own provider

[registry]
# The Arkhai public listing registry (preprod, Base Sepolia listings):
urls = ["http://34.41.205.175/registry"]
# Or point at any other listing registry, e.g. a self-hosted one:
# urls = ["http://<INDEXER_HOST>:8080"]

[registry.auth]
# Required when the listing registry gates reads (REGISTRY_REQUIRE_READ_API_KEY=true).
# The public preprod listing registry is currently read-open — no token needed.
# Keys must match the URLs in [registry] urls exactly (scheme, host,
# port, no trailing slash).
# "http://<INDEXER_HOST>:8080" = "<your-token>"

[negotiation]
# Ordered policy chain run per round. The buyer's default chain pairs
# `buyer_escrow_shape_guard` (vetoes if the seller mutates a buyer-
# pinned field) with the `bisection` terminal. Switch the terminal to
# `"rl"` for the trained pufferlib checkpoint (~1GB torch download).
# For per-escrow-kind dispatch, replace this list with a
# [negotiation.policies] table; see docs/configuration.md.
# See docs/configuration.md for the full reference.
policies = ["buyer_escrow_shape_guard", "bisection"]
```

## 3. Browse

```bash
market listing list
market listing list --gpu-model H200
market listing show <listing_id>
```

`list` queries every URL in `[registry] urls` in parallel and dedupes.

## 4. Buy

```bash
market buy \
  --gpu-model H200 \
  --duration-hours 1 \
  --initial-price 1 \
  --max-price 2 \
  --settlement-timeout 1800 \
  --yes
```

The CLI discovers a matching listing, negotiates via bisection, locks
escrow on chain, and polls until the seller returns
`status: ready` with VM credentials.

Useful flags:

- `--initial-price` / `--max-price` — bid range in human / whole-token
  units per hour (USDC: `--max-price 2` = $2/hr; the CLI scales by the
  token's on-chain `decimals()`).
- `--gpu-count-min`, `--region`, `--vcpu-min`, `--ram-gb-min`,
  `--disk-gb-min` — additional listing filters.
- `--settlement-timeout` — default 600s. Real cloud-init can take 5-10
  min; bump to 1800 if you see timeouts before progress.
- `--token-contract` — optional filter: only consider listings whose
  accepted escrow uses this ERC-20. Omit it and the token comes from the
  chosen listing. `--token-decimals` skips the on-chain `decimals()` lookup.

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

`buy --from` picks up the same run-log — mid-negotiation, post-escrow,
or post-submit — and walks it to terminal. `market settle --from` is a
narrower alias that skips straight to stages 3-5 (escrow.create +
settle + poll); it assumes the negotiation already agreed.

If `buy` crashed after escrow creation but before settle, **always**
resume — re-running a bare `market buy` against the same listing
creates a second escrow and locks more funds.

## 6. Tear down

Leases auto-expire at `agreed_duration_seconds`. The seller's lease
watchdog releases the resource and either claims or refunds the escrow
once the timeout passes.

To exit early after `expiration_unix`:

```bash
market escrow reclaim <escrow_uid>
```

## Common pitfalls

- **Prices on the CLI are human / whole-token units per hour.** `2`
  with 6-decimal USDC = $2/hr. Run-log entries record post-scaling
  base units.
- **`market buy` and `settle` are not idempotent on chain.** A buy
  that fails after escrow creation locks funds until `expiration_unix`.
  Resume with `market buy --from <run_id>`, don't re-`buy` from scratch.
- **VM SSH uses `vm_host_ip`, not the alias** the `ssh_command` field
  prints (`tenant<id>@kvm1` etc. — the host name is the seller's
  inventory alias, not DNS).
- **The tenant user has no sudo password.** Cloud-init only injects
  your SSH pubkey.
- **`[registry.auth]` keys must match `[registry] urls` exactly** —
  scheme, host, port, no trailing slash. Mismatch silently sends
  unauthenticated requests, you get 401s.
