# Local Secret Layout

Keep the deployment source-of-truth outside Git in
`~/.config/simple-market-service`, then materialize the host-local runtime files
under `/etc/simple-market-service`.

This is the canonical layout for operator-managed credentials, including the
Alchemy-backed RPC endpoints and the SSH keys used by provisioning and canary
validation.

## Local Directory Contract

Create a local directory with mode `0700`:

```bash
install -d -m 0700 ~/.config/simple-market-service
```

Then store these files with mode `0600`:

- `~/.config/simple-market-service/alchemy.env`
- `~/.config/simple-market-service/wallets.env`
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

`alchemy.env` should include at least:

```dotenv
ALCHEMY_BASE_SEPOLIA_HTTP_URL=https://base-sepolia.g.alchemy.com/v2/<key>
ALCHEMY_BASE_SEPOLIA_WSS_URL=wss://base-sepolia.g.alchemy.com/v2/<key>
ALCHEMY_BASE_MAINNET_HTTP_URL=https://base-mainnet.g.alchemy.com/v2/<key>
ALCHEMY_BASE_MAINNET_WSS_URL=wss://base-mainnet.g.alchemy.com/v2/<key>
```

`wallets.env` should include the local credential paths and agent wallets:

```dotenv
SELLER_PRIVATE_KEY=0x<seller-private-key>
SELLER_WALLET_ADDRESS=0x<seller-wallet-address>
BUYER_PRIVATE_KEY=0x<buyer-private-key>
BUYER_WALLET_ADDRESS=0x<buyer-wallet-address>
SSH_PUBLIC_KEY=ssh-ed25519 AAAA... canary@example.com
PROVISIONER_SSH_PRIVATE_KEY_PATH=~/.ssh/provisioner_ed25519
CANARY_TENANT_SSH_PRIVATE_KEY_PATH=~/.ssh/sms_canary_tenant_ed25519
```

`shared.env` should include the deployment-wide values that stay aligned across
registry, agents, provisioning, and the canary runner:

```dotenv
CHAIN_NAME=base_sepolia
CHAIN_ID=84532
ZEROTIER_NETWORK=<network-id>
FRP_SERVER_ADDR=<frp-host-or-zerotier-ip>
FRP_DOMAIN=<frp-domain>
FRP_DASHBOARD_PASSWORD=<frp-dashboard-password>
DEFAULT_VM_HOST=btc1
REGISTRY_URL=http://<registry-zerotier-ip>:8080
PROVISIONING_SERVICE_URL=http://<provisioner-zerotier-ip>:8081
```

`contracts.env` should contain the deployed ERC-8004 addresses:

```dotenv
IDENTITY_REGISTRY_ADDRESS=0x...
REPUTATION_REGISTRY_ADDRESS=0x...
VALIDATION_REGISTRY_ADDRESS=0x...
```

`provisioning.env` should hold the host-specific runtime values and point at the
local `management-vars.yaml` file:

```dotenv
DATABASE_URL=postgresql+psycopg2://...
REDIS_URL=redis://...
REDIS_QUEUE_NAME=provisioning_jobs
ANSIBLE_BECOME_PASS=<sudo-password>
MANAGEMENT_VARS_PATH=~/.config/simple-market-service/management-vars.yaml
```

`seller-agent.env`, `buyer-agent.env`, and `prod-canary.env` should each hold
their role-specific overrides such as agent IDs, URLs, and canary defaults.

## Materialization Step

Render the host-local bundle with:

```bash
python scripts/materialize_host_envs.py \
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

- `ALCHEMY_BASE_SEPOLIA_HTTP_URL` and `ALCHEMY_BASE_SEPOLIA_WSS_URL` into the
  right services for Base Sepolia
- `SSH_PRIVATE_KEY` and `MANAGEMENT_VARS_YAML` as base64 payloads in
  `/etc/simple-market-service/provisioning.env`
- `PROVISIONER_SSH_PRIVATE_KEY_PATH` and `CANARY_TENANT_SSH_PRIVATE_KEY_PATH`
  into the provisioning and canary contracts

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

Do not commit anything from `~/.config/simple-market-service` or
`/etc/simple-market-service`.
