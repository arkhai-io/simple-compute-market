# Deployment Input Checklist

This checklist tracks what is already available in repo state and what still has
to be recovered or created before a real ZeroTier-backed canary run.

## Environment Targets

| Environment | FRP host alias | Provisioning host alias | Candidate KVM host(s) | Source |
| --- | --- | --- | --- | --- |
| `dev` | `proxy-dev` | `provisioning-dev` | `ww1`, `piknik1`, `nodeinfra1`, `btc1` | `compute-provisioning-iac/ansible/inventory/hosts` |
| `staging` | `proxy-staging` | `provisioning-staging` | `ww1`, `piknik1`, `nodeinfra1`, `btc1` | `compute-provisioning-iac/ansible/inventory/hosts` |
| `production` | `proxy-production` | `provisioning-production` | `ww1`, `piknik1`, `nodeinfra1`, `btc1` | `compute-provisioning-iac/ansible/inventory/hosts` |

## Shared Inputs

| Input | Status | Current source | If missing, do this ourselves |
| --- | --- | --- | --- |
| `CHAIN_NAME=base-sepolia` | Available | `core/agent/.env.production.sample` | Keep unless the target chain changes |
| `CHAIN_ID=84532` | Available | `erc-8004-registry-py/.env.production.sample` | Keep unless the target chain changes |
| `IDENTITY_REGISTRY_ADDRESS` | Available but verify | `erc-8004-registry-py/.env.sample`, `erc-8004-registry-py/README.md` | Verify against explorer before use |
| `REPUTATION_REGISTRY_ADDRESS` | Available but verify | `erc-8004-registry-py/.env.sample`, `erc-8004-registry-py/README.md` | Verify against explorer before use |
| `VALIDATION_REGISTRY_ADDRESS` | Available but verify | `erc-8004-registry-py/.env.sample`, `erc-8004-registry-py/README.md` | Verify against explorer before use |
| Alkahest Base Sepolia addresses | Available | `../alkahest/contracts/deployments/deployment_base_sepolia.json` | If the target deployment changes, export a fresh JSON and sync `service/src/service/clients/alkahest.py` |
| `CHAIN_RPC_URL` / `RPC_URL` | Missing | samples only | Create at Infura, Alchemy, or another authenticated RPC provider |
| `ZEROTIER_NETWORK` | Missing | `infra/zerotier/.env.sample` only | Recover from the live controller or create a new network and authorize all nodes |
| Registry ZeroTier URL | Missing | none | Deploy registry, confirm reachability over ZeroTier, then set `REGISTRY_URL` |
| Provisioning ZeroTier URL | Missing | none | Deploy async provisioning, confirm reachability over ZeroTier, then set `PROVISIONING_SERVICE_URL` |
| Seller agent ZeroTier URL | Missing | none | Deploy seller agent, resolve `{ZEROTIER_IP}`, and publish its real URL |
| Buyer agent ZeroTier URL | Missing | none | Deploy buyer agent, resolve `{ZEROTIER_IP}`, and publish its real URL |

## Registry Inputs

| Variable | Status | Current source | If missing, do this ourselves |
| --- | --- | --- | --- |
| `DATABASE_URL` | Missing | production sample uses placeholder | Provision Postgres and create a registry database/user |
| `HOST`, `PORT`, health-check vars | Available | `erc-8004-registry-py/.env.production.sample` | Keep unless deployment topology changes |
| `ZEROTIER_NETWORK` | Missing | sample only | Recover from controller or create network |

## Provisioning Inputs

| Variable | Status | Current source | If missing, do this ourselves |
| --- | --- | --- | --- |
| `DATABASE_URL` | Missing | production sample uses placeholder | Provision Postgres and create a provisioning database/user |
| `REDIS_URL` | Missing until infra exists | Terraform defines outputs but repo has no state | Run Terraform or recover the live Redis endpoint |
| `DEFAULT_VM_HOST` | Available | production sample + inventory | Keep `ww1` or switch deliberately to another tracked KVM host |
| `ANSIBLE_BECOME_PASS` | Missing | sample now exposes it, no value committed | Recover the host sudo password or rotate one for the chosen KVM host |
| `SSH_PRIVATE_KEY` | Missing | documented in `compute-provisioning-iac/README.md` | Generate `~/.ssh/provisioner_ed25519`, then base64-encode it |
| `MANAGEMENT_VARS_YAML` | Missing | repo only has `vm-vars-example.yaml` | Create `ansible/inventory/management-vars.yaml`, then base64-encode it |
| `FRP_SERVER_ADDR` | Partially available | likely the chosen `proxy-*` host IP | Confirm that the selected proxy host is the FRP server |
| `FRP_DOMAIN` | Docs only | `compute-provisioning-iac/README.md` examples | Recover from the live FRP deployment and DNS records |
| `FRP_DASHBOARD_PASSWORD` | Missing | not committed | Recover from existing FRP setup or generate a new one |
| `ENABLE_AUTH=true` | Available | production sample + runbook | Keep enabled in deployed environments |
| `AUTH_FAIL_OPEN=false` | Available | production sample + runbook | Keep disabled for canary/prod validation |
| `ADMIN_SECRET` | Not used by current runtime | Stale submodule docs only | Ignore it for deployment bundles until the IaC docs are updated |

## Agent Inputs

Use two separate local agent env files for deployed canaries: one seller bundle
and one buyer bundle. Do not reuse the same URL, private key, or `ONCHAIN_AGENT_ID`
across both actors.

| Variable | Status | Current source | If missing, do this ourselves |
| --- | --- | --- | --- |
| `BASE_URL_OVERRIDE=http://{ZEROTIER_IP}:8000/` | Available pattern only | production sample + runbook | Resolve on the deployed host after ZeroTier join |
| `GEMINI_API_KEY` | Missing | production sample placeholder | Create a deployment-scoped API key if this runtime path still needs it |
| `AGENT_PRIV_KEY` | Missing | production sample placeholder | Generate buyer/seller canary wallets and store secrets outside git |
| `AGENT_WALLET_ADDRESS` | Missing | production sample placeholder | Derive from each generated private key |
| `ONCHAIN_AGENT_ID` | Missing until registration | runtime output | Register each agent on-chain after ZeroTier URL resolution |
| `SSH_PUBLIC_KEY` | Missing | production sample placeholder | Generate a canary tenant keypair and publish the public key |
| `TOKEN_REGISTRY_PATH` | Available | production sample | Keep unless token registry file moves |
| `DEFAULT_VM_HOST` | Available | production sample + inventory | Keep `ww1` unless the seller environment changes |

## Smoke Harness Inputs

| Input | Status | Current source | If missing, do this ourselves |
| --- | --- | --- | --- |
| `SELLER_AGENT_ID` / `BUYER_AGENT_ID` | Missing until registration | `prod_canary_smoke.py` CLI args | Capture canonical `eip155:` IDs after agent registration |
| `SELLER_PRIVATE_KEY` / `BUYER_PRIVATE_KEY` | Missing | `prod_canary_smoke.py` CLI args | Use the canary wallets created for deployment |
| `SSH_PRIVATE_KEY_PATH` | Missing | `prod_canary_smoke.py` CLI args | Point it at the tenant private key that matches `SSH_PUBLIC_KEY` |
| `CANARY_GPU_MODEL`, `CANARY_REGION`, `CANARY_TOKEN_SYMBOL`, `CANARY_TOKEN_AMOUNT` | Defaults exist | `prod_canary_smoke.py` | Set explicitly for the target environment to avoid accidental mismatches |

## Immediate Blockers

1. Confirm the live ZeroTier network ID and service URLs.
2. Recover or create Postgres credentials for both registry and provisioning.
3. Generate or recover the provisioner SSH key, management vars, and FRP dashboard password.
4. Generate funded canary wallets and register buyer/seller agents on-chain.
5. Keep the Alkahest Base Sepolia addresses in this repo synchronized with `../alkahest`.
