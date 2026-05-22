# Buyer quickstart

How to install the `market` CLI, configure it to talk to one or more
indexer registries, find listings, buy compute on Base Sepolia, and SSH
into the leased VM.

This assumes someone (you, a friend, or a public operator) has already
deployed a seller stack — see [`seller-quickstart.md`](./seller-quickstart.md)
if not.

---

## What you'll have at the end

- The `market` console script on your `PATH`.
- A `~/.config/arkhai/config.toml` with your Base Sepolia wallet, your SSH
  key, and the URL(s) of one or more indexer registries you want to
  search.
- A working `market buy --gpu-model H200 --duration-hours 1` flow that
  ends with you SSH'd into a fresh Ubuntu VM, billed in USDC on chain.

## Prerequisites

- Linux or macOS (Windows: WSL).
- Python 3.12+.
- Ethereum wallet on Base Sepolia with **test ETH** (for gas) and
  **whatever token the seller accepts** (typically USDC test funds from
  [faucet.circle.com](https://faucet.circle.com)).
- A Base Sepolia RPC URL. `https://sepolia.base.org` works for one-off
  buys; for sustained use get an Infura or Alchemy key.
- An SSH keypair you'll use to log into leased VMs. If you don't have
  one yet:

  ```bash
  ssh-keygen -t ed25519 -N "" -f ~/.ssh/mms_buyer_id_ed25519
  ```

  Treat this like any other personal SSH key. The pubkey gets injected
  into every VM you lease via cloud-init.

## 1. Install the CLI

Three options:

### a) From the install script (release builds, recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/.../market-installer.sh | bash
```

Details in [`buyer/INSTALLER.md`](../buyer/INSTALLER.md). Drops a `market`
binary in `~/.local/bin` (or `/usr/local/bin` with `sudo`).

### b) Development install from the repo

```bash
git clone https://github.com/arkhai-io/simple-compute-market.git
cd simple-compute-market
make build-buyer
# the wrapper at ./buyer/.venv/bin/market is what `make install-buyer` symlinks
```

If you skip `make install-buyer`, add the venv directly:

```bash
export PATH="$PWD/buyer/.venv/bin:$PATH"
market --version
```

### c) Inside an existing Python project

```bash
uv pip install -e ./buyer  # path to the buyer subtree
```

## 2. Configure

`market` reads `$XDG_CONFIG_HOME/arkhai/config.toml` — that's
`~/.config/arkhai/config.toml` on Linux/macOS. Scaffold a starter:

```bash
market config init-user
```

Or just create it directly. Minimal working config:

```toml
[wallet]
address     = "0xYourBuyerAddress"
private_key = "0xYourBuyerPrivateKey"
# The pubkey you generated above. Gets injected into VMs you lease.
ssh_public_key = "ssh-ed25519 AAAA…buyer@host"

[chain]
name     = "base_sepolia"
chain_id = 84532
rpc_url  = "https://base-sepolia.infura.io/v3/<YOUR_KEY>"

[registry]
# One or more indexer URLs. The CLI discovers listings by fanning out
# queries to every URL listed here.
urls                      = ["http://<INDEXER_HOST>:8080"]
identity_registry_address = "0x8004A818BFB912233c491871b3d84c89A494BD9e"

[registry.auth]
# Only needed for indexers running with REGISTRY_REQUIRE_API_KEY=true.
# The seller operating that indexer hands you a bearer token. Omit
# entirely for fully public indexers. Keys must match URLs in
# [registry] urls verbatim (scheme, host, port, no trailing slash).
"http://<INDEXER_HOST>:8080" = "shared-bootstrap-token"

[buyer]
# 0x ERC-20 address used when `market buy` has no --token-contract.
# Decimals + symbol are resolved on chain via [chain].rpc_url and
# cached at $XDG_CACHE_HOME/arkhai/tokens/<chain_id>.json.
default_token_address = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"

[buyer.negotiation]
# "bisection" doesn't need torch installed. The default is "rl" which
# pulls in torch ~ 1GB.
policy_mode   = "bisection"
```

Two things that will bite you if you skip them:

- **`ssh_public_key`** — without it, `market settle` fails before
  reaching the seller because the cloud-init injection has no key to
  send.
- **`[registry.auth]` keys exactly matching `[registry] urls`** — case,
  scheme, port, no trailing slash. A mismatch silently sends
  unauthenticated requests and you get 401s.

## 3. Browse what's for sale

```bash
market listing list
market listing list --gpu-model H200
market listing show <listing_id>
```

`list` queries every URL in `[registry] urls` in parallel, dedupes, and
prints the union. `show` digs into one listing — what's offered, what
escrows are accepted, the seller URL, max duration.

If the registry is private and you forgot `[registry.auth]`, you'll see
`401 Unauthorized` here.

## 4. Buy

```bash
market buy \
  --gpu-model H200 \
  --duration-hours 1 \
  --price-markup 1.5 \
  --yes \
  --settlement-timeout 1800 \
  --poll-interval 10
```

What that does:

1. **Discover** — query all indexers, filter for `gpu_model=H200`.
2. **Aggregate** — pick the best match per `best_price` policy.
3. **Negotiate** — open a bid against the seller; bisection-converge to
   an agreed price.
4. **Escrow** — create an on-chain ERC-20 escrow attestation locking
   `agreed_price × duration_seconds / 3600` raw token units to the
   seller.
5. **Settle** — POST the escrow uid to the seller, who validates it on
   chain and (in live mode) drives the provisioning ansible playbook.
6. **Poll** — wait for the seller to return `status: ready` with VM
   credentials.

Output ends with a "Settlement complete" table including a `Connection`
field. The juicy bit:

```
"ssh_command": "ssh -i <your_private_key> -p 27978 tenant1ef9@btc1"
```

The `tenant1ef9@btc1` part is mostly cosmetic — `btc1` is the seller's
inventory alias for the host, not its DNS name. Use the
`vm_host_ip` field from the same response, or substitute the seller's
public IP yourself:

```bash
ssh -i ~/.ssh/mms_buyer_id_ed25519 -p 27978 tenant1ef9@<seller_public_ip>
```

You should land in a fresh Ubuntu 24.04 VM. Welcome.

### Useful flags

- `--initial-price` / `--max-price` — paired; explicit bid range in raw
  token base units per hour. Omit both to derive from the seller's
  advertised min_price (`× --price-markup`, default 1.5).
- `--gpu-model`, `--gpu-count-min`, `--region`, `--vcpu-min`, `--ram-gb-min`,
  `--disk-gb-min` — `market listing list` filters.
- `--settlement-timeout` (default 600s) — provisioning timeout. Fresh
  Ubuntu cloud-init + apt installs can take 5-10 min on a slow link;
  bump to 1800 if you're seeing timeouts before any progress.
- `--token-contract` + `--token-decimals` — override
  `[buyer].default_token_address` and skip the chain `decimals()`
  lookup. Useful for one-off buys against a token you haven't put in
  config.

## 5. Resume an interrupted buy

Every `market buy` writes a JSONL run log to
`$XDG_STATE_HOME/arkhai/buy-runs/<run_id>.jsonl`. If `buy` crashes after
escrow creation but before settle completes, you can resume:

```bash
market logs runs                  # list past runs and their last status
market logs show <run_id>         # show full event log for one run
market settle --from <run_id>     # resume from where it died
```

`settle --from` re-reads the run log, finds the escrow uid that was
already created on chain, and re-POSTs to the seller. Use this whenever
the buy timed out on the buyer side but the seller is still
provisioning.

## 6. Tear down

Leases auto-expire at `agreed_duration_seconds`. The seller's lease
watchdog will shut down the VM, release the resource, and either claim
the escrow (if the buyer's escrow is claimable) or refund.

To exit early:

```bash
market escrow reclaim <escrow_uid>
```

(Only works after the escrow's `expiration_unix` has passed — the
escrow contract enforces a timeout, not buyer-driven cancel.)

## Common sharp edges

- **`--initial-price` xor `--max-price`** is rejected. Pass both or
  neither (defaults derive from seller min_price).
- **Prices are raw token base units, per hour.** For USDC (6 decimals),
  2 USDC/hr = `--max-price 2000000`, not `--max-price 2`. The buyer
  CLI's help text says "raw token units" but it's easy to miss.
- **`market buy` and `market settle` are not idempotent on chain.** A
  buy that fails after escrow creation but before settle locks your
  funds in the escrow until the expiration timestamp. Always
  `market settle --from <run_id>` rather than re-running `market buy`
  on the same listing if you've already created an escrow.
- **VM SSH is direct on the host's public IP, not via the inventory
  alias** the seller's response printed. The `vm_host_ip` field has the
  real IP.
- **VM tenant user does not have a sudo password.** Cloud-init only
  injects your SSH pubkey; root sudo is configured for a separate root
  user. If you need `sudo` you'll have to negotiate that with the
  seller out-of-band or wait for the role-aware provisioning flow.
- **Switching policy from `rl` to `bisection`** (in `[buyer.negotiation]`)
  saves ~1GB of torch download on `make build-buyer`. Bisection is also
  more predictable for testing.
