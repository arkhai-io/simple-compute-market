# Local Secret Layout

Keep credentials outside Git in two local layers, then materialize the
host-local runtime files under `/etc/simple-market-service`.

This is the canonical layout for operator-managed credentials, including the
Alchemy-backed RPC endpoints and the SSH keys used by provisioning and canary
validation.

## Directory Contract

Create both local directories with mode `0700`:

```bash
install -d -m 0700 ~/.config/web3-ops
install -d -m 0700 ~/.config/simple-market-service
```

Keep shared cross-project credentials in `~/.config/web3-ops` with mode `0600`:

- `~/.config/web3-ops/alchemy.env`
- `~/.config/web3-ops/wallets.env`

Keep project-specific overlays in `~/.config/simple-market-service` with mode `0600`:

- `~/.config/simple-market-service/shared.env`
- `~/.config/simple-market-service/contracts.env`
- `~/.config/simple-market-service/registry.env`
- `~/.config/simple-market-service/provisioning.env`
- `~/.config/simple-market-service/seller-agent.env`
- `~/.config/simple-market-service/buyer-agent.env`
- `~/.config/simple-market-service/prod-canary.env`
- `~/.config/simple-market-service/management-vars.yaml`

Recommended key files that stay outside this directory but remain local:

- `~/.ssh/provisioner_ed25519`
- `~/.ssh/sms_canary_tenant_ed25519`

## Required Fragments

`~/.config/web3-ops/alchemy.env` should include at least:

```dotenv
ETH_SEPOLIA_HTTP_RPC_URL=https://eth-sepolia.g.alchemy.com/v2/<key>
ETH_SEPOLIA_WSS_RPC_URL=wss://eth-sepolia.g.alchemy.com/v2/<key>
ALCHEMY_BASE_MAINNET_HTTP_URL=https://base-mainnet.g.alchemy.com/v2/<key>
ALCHEMY_BASE_MAINNET_WSS_URL=wss://base-mainnet.g.alchemy.com/v2/<key>
```

`~/.config/web3-ops/wallets.env` should include the reusable credential paths
and wallet keys:

```dotenv
SEPOLIA_FUNDER_PRIVATE_KEY=0x<sepolia-funder-private-key>
MAINNET_FUNDER_PRIVATE_KEY=0x<mainnet-funder-private-key>
SELLER_PRIVATE_KEY=0x<seller-private-key>
SELLER_WALLET_ADDRESS=0x<seller-wallet-address>
BUYER_PRIVATE_KEY=0x<buyer-private-key>
BUYER_WALLET_ADDRESS=0x<buyer-wallet-address>
SSH_PUBLIC_KEY=ssh-ed25519 AAAA... canary@example.com
PROVISIONER_SSH_PRIVATE_KEY_PATH=~/.ssh/provisioner_ed25519
CANARY_TENANT_SSH_PRIVATE_KEY_PATH=~/.ssh/sms_canary_tenant_ed25519
```

`~/.config/simple-market-service/shared.env` should include the deployment-wide
values that stay aligned across registry, agents, provisioning, and the canary
runner:

```dotenv
CHAIN_NAME=ethereum_sepolia
CHAIN_ID=11155111
ZEROTIER_NETWORK=<network-id>
FRP_SERVER_ADDR=<frp-host-or-zerotier-ip>
FRP_DOMAIN=<frp-domain>
FRP_DASHBOARD_PASSWORD=<frp-dashboard-password>
DEFAULT_VM_HOST=btc1
REGISTRY_URL=http://<registry-zerotier-ip>:8080
PROVISIONING_SERVICE_URL=http://<provisioner-zerotier-ip>:8081
```

`~/.config/simple-market-service/contracts.env` should contain the deployed
ERC-8004 addresses:

```dotenv
IDENTITY_REGISTRY_ADDRESS=0x...
REPUTATION_REGISTRY_ADDRESS=0x...
VALIDATION_REGISTRY_ADDRESS=0x...
```

`~/.config/simple-market-service/provisioning.env` should hold the host-specific
runtime values and point at the local `management-vars.yaml` file:

```dotenv
DATABASE_URL=postgresql+psycopg2://...
REDIS_URL=redis://...
REDIS_QUEUE_NAME=provisioning_jobs
ANSIBLE_BECOME_PASS=<sudo-password>
MANAGEMENT_VARS_PATH=~/.config/simple-market-service/management-vars.yaml
```

`~/.config/simple-market-service/seller-agent.env`,
`~/.config/simple-market-service/buyer-agent.env`, and
`~/.config/simple-market-service/prod-canary.env` should each hold their
role-specific overrides such as agent IDs, URLs, and canary defaults. For
repeatable canary funding, add these keys to `prod-canary.env`:

```dotenv
BUYER_NATIVE_FLOOR_WEI=20000000000000
SELLER_NATIVE_FLOOR_WEI=10000000000000
BUYER_TOKEN_BUFFER_BASE_UNITS=0
CANARY_MAINNET_MAX_NATIVE_TOPUP_WEI=200000000000000
CANARY_MAINNET_MAX_ERC20_TOPUP_BASE_UNITS=2000000
# Required for Base mainnet ERC20 funding when the token is not in the checked-in registry:
# CANARY_FUNDING_TOKEN_ADDRESS=0x...
# CANARY_FUNDING_TOKEN_DECIMALS=6
```

## Materialization Step

Render the host-local bundle with:

```bash
python scripts/materialize_host_envs.py \
  --shared-secrets-dir ~/.config/web3-ops \
  --local-secrets-dir ~/.config/simple-market-service \
  --output-dir /etc/simple-market-service
```

That command writes:

- `/etc/simple-market-service/contracts.env`
- `/etc/simple-market-service/registry.env`
- `/etc/simple-market-service/provisioning.env`
- `/etc/simple-market-service/seller-agent.env`
- `/etc/simple-market-service/buyer-agent.env`
- `/etc/simple-market-service/prod-canary.env`
- `/etc/simple-market-service/management-vars.yaml`

The renderer also derives and injects:

- `ETH_SEPOLIA_HTTP_RPC_URL` and `ETH_SEPOLIA_WSS_RPC_URL` into the right
  services for Ethereum Sepolia
- `SSH_PRIVATE_KEY` and `MANAGEMENT_VARS_YAML` as base64 payloads in
  `/etc/simple-market-service/provisioning.env`
- `PROVISIONER_SSH_PRIVATE_KEY_PATH` and `CANARY_TENANT_SSH_PRIVATE_KEY_PATH`
  into the provisioning and canary contracts

## Canary Funding Preflight

Before a live run, compute the top-ups from the same local secret bundle:

```bash
python scripts/pre_canary_fund.py \
  --shared-secrets-dir ~/.config/web3-ops \
  --local-secrets-dir ~/.config/simple-market-service
```

When you are ready to broadcast the top-up transactions from
`SEPOLIA_FUNDER_PRIVATE_KEY` or `MAINNET_FUNDER_PRIVATE_KEY`, rerun with
`--apply`. For Base mainnet, also pass `--allow-mainnet`; the apply step refuses
to proceed without that acknowledgement and the configured
`CANARY_MAINNET_MAX_NATIVE_TOPUP_WEI` /
`CANARY_MAINNET_MAX_ERC20_TOPUP_BASE_UNITS` caps.

## One-Shot Repeatable Run

For the isolated runner or a local operator machine, use the single orchestration
entrypoint after the local secret bundle is ready:

```bash
python scripts/run_repeatable_canary.py \
  --environment isolated-eth-sepolia \
  --shared-secrets-dir ~/.config/web3-ops \
  --local-secrets-dir ~/.config/simple-market-service \
  --output-dir /etc/simple-market-service \
  --artifacts-dir artifacts \
  --inventory-path compute-provisioning-iac/ansible/inventory/hosts \
  --apply-funding
```

That wrapper runs `scripts/materialize_host_envs.py`,
`scripts/pre_canary_fund.py`, `scripts/run_deployment_gate_checks.py`,
`scripts/validate_deployment_bundle.py`, `scripts/prod_canary_smoke.py`, and
`scripts/prod_canary_rollback.py` in the correct order.

For a Base mainnet lane, add `--allow-mainnet` and keep the mainnet caps in
`prod-canary.env` set to the smallest values that still support the canary.

## Verification

After the render completes, confirm that the expected files exist and stay
local to the host:

```bash
ls -l /etc/simple-market-service
grep '^CHAIN_RPC_URL=' /etc/simple-market-service/seller-agent.env
grep '^RPC_URL=' /etc/simple-market-service/registry.env
grep '^SSH_PRIVATE_KEY=' /etc/simple-market-service/provisioning.env
grep '^SSH_PRIVATE_KEY_PATH=' /etc/simple-market-service/prod-canary.env
```

`~/.config/web3-ops` is the reusable cross-project credential store. Keep
project-specific overrides in `~/.config/simple-market-service`.

Do not commit anything from `~/.config/web3-ops`,
`~/.config/simple-market-service`, or `/etc/simple-market-service`.
