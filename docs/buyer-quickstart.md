# Buyer quickstart

Install the `market` CLI, point it at an indexer, find a listing, buy
compute on Base Sepolia, and SSH into the leased VM.

For the seller side see [`seller-quickstart.md`](./seller-quickstart.md).

## Prerequisites

- Linux or macOS (Windows: WSL).
- Python 3.12+.
- A Base Sepolia wallet with test ETH (for gas) and whatever ERC-20 the
  seller accepts (USDC test funds from
  [faucet.circle.com](https://faucet.circle.com)).
- A Base Sepolia RPC URL (`https://sepolia.base.org` works for one-offs;
  Infura/Alchemy otherwise).
- An SSH keypair for leased VMs:

  ```bash
  ssh-keygen -t ed25519 -N "" -f ~/.ssh/mms_buyer_id_ed25519
  ```

  The pubkey gets injected into every VM you lease via cloud-init.

## 1. Install

From a release build:

```bash
curl -fsSL https://raw.githubusercontent.com/.../market-installer.sh | bash
```

Details in [`buyer/INSTALLER.md`](../buyer/INSTALLER.md).

Or from the repo:

```bash
git clone https://github.com/arkhai-io/simple-compute-market.git
cd simple-compute-market
make build-buyer
export PATH="$PWD/buyer/.venv/bin:$PATH"
market --version
```

## 2. Configure

`market` reads `~/.config/arkhai/buyer.toml`. Scaffold with
`market config init-user` or write directly:

```toml
[wallet]
private_key    = "0x<YOUR_BUYER_PRIVATE_KEY>"
ssh_public_key = "ssh-ed25519 AAAA...your-key buyer@host"

[chain]
chain_id = 84532
rpc_url  = "https://base-sepolia.infura.io/v3/<YOUR_KEY>"

[registry]
urls = ["http://<INDEXER_HOST>:8080"]

[registry.auth]
# Required when the indexer runs with REGISTRY_REQUIRE_API_KEY=true.
# Keys must match the URLs in [registry] urls exactly (scheme, host,
# port, no trailing slash).
"http://<INDEXER_HOST>:8080" = "<your-token>"

[buyer]
default_token_address = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"

[buyer.negotiation]
# Bisection avoids a ~1GB torch download. Switch to "rl" if you want it.
policy_mode = "bisection"
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
  --price-markup 1.5 \
  --settlement-timeout 1800 \
  --yes
```

The CLI discovers a matching listing, negotiates via bisection, locks
escrow on chain, and polls until the seller returns
`status: ready` with VM credentials.

Useful flags:

- `--initial-price` / `--max-price` — both required if either given;
  bid range in human / whole-token units per hour (USDC: `--max-price 2`
  = $2/hr; the CLI scales by the token's on-chain `decimals()`).
- `--gpu-count-min`, `--region`, `--vcpu-min`, `--ram-gb-min`,
  `--disk-gb-min` — additional listing filters.
- `--settlement-timeout` — default 600s. Real cloud-init can take 5-10
  min; bump to 1800 if you see timeouts before progress.
- `--token-contract` + `--token-decimals` — override config and skip
  the on-chain `decimals()` lookup.

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
  prints (`tenant<id>@btc1` etc. — the host name is the seller's
  inventory alias, not DNS).
- **The tenant user has no sudo password.** Cloud-init only injects
  your SSH pubkey.
- **`[registry.auth]` keys must match `[registry] urls` exactly** —
  scheme, host, port, no trailing slash. Mismatch silently sends
  unauthenticated requests, you get 401s.
