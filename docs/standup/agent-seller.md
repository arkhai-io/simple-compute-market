# Seller Agent Deployment

This document covers the deployed seller agent path for the production canary.

## Inputs

- `core/agent/.env.production.sample`
- a writable host-local seller env file at `/etc/simple-market-service/seller-agent.env`
- a seller wallet private key and address
- a ZeroTier-capable runtime host with Docker and access to `/dev/net/tun`
- access to the deployed registry and provisioning URLs
- an SSH public key for tenant access

## Image

The agent image is built from `core/Dockerfile`. The repo's default CI publish
path is defined in `.github/workflows/docker-build-push-core-agent.yml` and
publishes `a2a-agent` images to Artifact Registry.

Choose the exact tag or digest you want to run before deployment. If you use the
repo's default workflow, a working pattern is:

```bash
export SELLER_AGENT_IMAGE="us-east4-docker.pkg.dev/<gcp-project>/a2a-agent/a2a-agent:<tag-or-digest>"
sudo docker pull "${SELLER_AGENT_IMAGE}"
```

Pin the image by immutable tag or digest. Do not deploy production canaries from
an unpinned `latest` tag.

## Host Preparation

Create persistent host paths for the env file, the agent SQLite DB, and the
ZeroTier identity/state directory:

```bash
sudo install -d -m 0755 /etc/simple-market-service
sudo install -d -m 0755 /var/lib/simple-market-service/seller-market
sudo install -d -m 0755 /var/lib/simple-market-service/seller-zerotier
sudo cp core/agent/.env.production.sample /etc/simple-market-service/seller-agent.env
```

Edit `/etc/simple-market-service/seller-agent.env` so it contains the real seller
deployment values. At minimum, set:

- `PORT=8000`
- `BASE_URL_OVERRIDE=http://{ZEROTIER_IP}:8000/`
- `AGENT_DB_PATH=/var/lib/market/agent.db`
- `IDENTITY_REGISTRY_ADDRESS`
- `REPUTATION_REGISTRY_ADDRESS`
- `VALIDATION_REGISTRY_ADDRESS`
- `CHAIN_ID=84532`
- `REGISTRY_URL`
- `CHAIN_RPC_URL`
- `CHAIN_NAME=base_sepolia`
- `AGENT_PRIV_KEY`
- `AGENT_WALLET_ADDRESS`
- `SSH_PUBLIC_KEY`
- `ZEROTIER_NETWORK`
- `PROVISIONING_MODE=http`
- `PROVISIONING_SERVICE_URL`
- `DEFAULT_VM_HOST`
- `TOKEN_REGISTRY_PATH=/app/core/agent/app/data/token_registry_base_sepolia.json`
- `ENABLE_EVENT_QUEUE=false`
- `AUTO_REGISTER=true`

Keep the env file on the host, outside Git, because it contains real secrets and
is mutated during startup.

The deployed seller runtime writes `ZEROTIER_IP`, the resolved
`BASE_URL_OVERRIDE`, and `ONCHAIN_AGENT_ID` back into `ENV_FILE` during startup.
This is a real runtime requirement enforced by `core/entrypoint.sh`. Do not use
a read-only env mount for the deployed seller path.

If the image is stored in Artifact Registry, authenticate Docker on the host
before the first pull:

```bash
gcloud auth print-access-token \
  | sudo docker login -u oauth2accesstoken --password-stdin https://<region>-docker.pkg.dev
```

If the host firewall is enabled, allow inbound `8000/tcp` on the ZeroTier
interface before starting the container.

## Container Launch

Launch the seller container with explicit host mounts for the env file, SQLite
DB path, and ZeroTier state:

```bash
sudo docker rm -f sms-seller-agent 2>/dev/null || true

sudo docker run -d \
  --name sms-seller-agent \
  --restart unless-stopped \
  --cap-add NET_ADMIN \
  --cap-add SYS_MODULE \
  --device /dev/net/tun:/dev/net/tun \
  --env-file /etc/simple-market-service/seller-agent.env \
  -e ENV_FILE=/etc/simple-market-service/seller-agent.env \
  -p 8000:8000 \
  -v /etc/simple-market-service/seller-agent.env:/etc/simple-market-service/seller-agent.env \
  -v /var/lib/simple-market-service/seller-market:/var/lib/market \
  -v /var/lib/simple-market-service/seller-zerotier:/var/lib/zerotier-one \
  "${SELLER_AGENT_IMAGE}"
```

Notes:

- `PORT` in the env file must stay aligned with `-p 8000:8000` and
  `BASE_URL_OVERRIDE=http://{ZEROTIER_IP}:8000/`.
- The `/var/lib/market` mount persists the seller SQLite DB referenced by
  `AGENT_DB_PATH`.
- The `/var/lib/zerotier-one` mount persists the ZeroTier node identity so
  restarts do not create a new node that must be re-authorized.
- If the image is stored in Artifact Registry, authenticate Docker on the host
  before the first pull.

## Registration And Identity Capture

The standard deployed path uses `AUTO_REGISTER=true`, so registration happens at
container startup. Wait for the container to finish the registration step, then
capture the persisted identity values from the host-local env file:

```bash
sudo docker logs --tail 200 sms-seller-agent
grep '^ZEROTIER_IP=' /etc/simple-market-service/seller-agent.env
grep '^BASE_URL_OVERRIDE=' /etc/simple-market-service/seller-agent.env
grep '^ONCHAIN_AGENT_ID=' /etc/simple-market-service/seller-agent.env
```

If the seller host is joining the ZeroTier network for the first time, capture
the reported ZeroTier node ID from the startup logs and authorize that member on
the controller before expecting `ZEROTIER_IP` resolution to complete.

Do not continue until `/etc/simple-market-service/seller-agent.env` contains a
canonical `ONCHAIN_AGENT_ID=eip155:...` value and `BASE_URL_OVERRIDE` has been
resolved to the seller's real ZeroTier URL.

If you intentionally disable `AUTO_REGISTER`, run the repo's explicit
registration flow against the same env file before exposing the agent:

```bash
cd core/agent
make register ENV_FILE=/etc/simple-market-service/seller-agent.env
```

## Verification

Resolve the deployed seller URL from the persisted env file, then verify the
registration and portfolio endpoints:

```bash
grep '^BASE_URL_OVERRIDE=' /etc/simple-market-service/seller-agent.env
curl http://<seller-zerotier-ip>:8000/.well-known/agent-card.json
curl http://<seller-zerotier-ip>:8000/.well-known/erc-8004-registration.json
curl http://<seller-zerotier-ip>:8000/resources/portfolio
```

The seller is ready for canary use only after resource seeding is complete and
`/resources/portfolio` reports a matching available resource. Continue with
`docs/standup/resource-seeding.md` before running the canary.
