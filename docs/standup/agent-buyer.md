# Buyer Agent Deployment

This document covers the deployed buyer agent path for the production canary.

## Inputs

- `core/agent/.env.production.sample`
- a writable host-local buyer env file at `/etc/simple-market-service/buyer-agent.env`
- a buyer wallet private key and address
- a ZeroTier-capable runtime host with Docker and access to `/dev/net/tun`
- access to the deployed registry and provisioning URLs
- an SSH public key for tenant access

## Image

The buyer uses the same image build and publish path as the seller agent:
`core/Dockerfile` plus `.github/workflows/docker-build-push-core-agent.yml`.

Choose the exact immutable image tag or digest before deployment:

```bash
export BUYER_AGENT_IMAGE="us-east4-docker.pkg.dev/<gcp-project>/a2a-agent/a2a-agent:<tag-or-digest>"
sudo docker pull "${BUYER_AGENT_IMAGE}"
```

## Host Preparation

Create dedicated host paths for the buyer env file, SQLite DB, and ZeroTier
state:

```bash
sudo install -d -m 0755 /etc/simple-market-service
sudo install -d -m 0755 /var/lib/simple-market-service/buyer-market
sudo install -d -m 0755 /var/lib/simple-market-service/buyer-zerotier
sudo cp core/agent/.env.production.sample /etc/simple-market-service/buyer-agent.env
```

Edit `/etc/simple-market-service/buyer-agent.env` with the real buyer values.
At minimum, set:

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
- `TOKEN_REGISTRY_PATH=/app/core/agent/app/data/token_registry_base_sepolia.json`
- `ENABLE_EVENT_QUEUE=false`
- `AUTO_REGISTER=true`

The buyer runtime has the same writable `ENV_FILE` requirement as the seller
path. Startup writes `ZEROTIER_IP`, the resolved `BASE_URL_OVERRIDE`, and
`ONCHAIN_AGENT_ID` back into `/etc/simple-market-service/buyer-agent.env`.

The buyer and seller env files must not reuse the same URL, wallet, or
`ONCHAIN_AGENT_ID`.

If the image is stored in Artifact Registry, authenticate Docker on the host
before the first pull:

```bash
gcloud auth print-access-token \
  | sudo docker login -u oauth2accesstoken --password-stdin https://<region>-docker.pkg.dev
```

## Container Launch

Launch the buyer container with host mounts for the env file, SQLite DB, and
ZeroTier state:

```bash
sudo docker rm -f sms-buyer-agent 2>/dev/null || true

sudo docker run -d \
  --name sms-buyer-agent \
  --restart unless-stopped \
  --cap-add NET_ADMIN \
  --cap-add SYS_MODULE \
  --device /dev/net/tun:/dev/net/tun \
  --env-file /etc/simple-market-service/buyer-agent.env \
  -e ENV_FILE=/etc/simple-market-service/buyer-agent.env \
  -p 8000:8000 \
  -v /etc/simple-market-service/buyer-agent.env:/etc/simple-market-service/buyer-agent.env \
  -v /var/lib/simple-market-service/buyer-market:/var/lib/market \
  -v /var/lib/simple-market-service/buyer-zerotier:/var/lib/zerotier-one \
  "${BUYER_AGENT_IMAGE}"
```

Notes:

- `PORT`, the published port, and `BASE_URL_OVERRIDE` must agree.
- The buyer SQLite DB stays under `/var/lib/market`, backed by the host mount.
- The `/var/lib/zerotier-one` mount preserves the buyer's ZeroTier node
  identity across restarts.
- Keep enough native gas in the buyer wallet for `approve + escrow.create` if
  the canary uses `WETH`.

## Registration And Identity Capture

Wait for startup registration to finish, then capture the persisted buyer
identity values:

```bash
sudo docker logs --tail 200 sms-buyer-agent
grep '^ZEROTIER_IP=' /etc/simple-market-service/buyer-agent.env
grep '^BASE_URL_OVERRIDE=' /etc/simple-market-service/buyer-agent.env
grep '^ONCHAIN_AGENT_ID=' /etc/simple-market-service/buyer-agent.env
```

If the buyer host is joining the ZeroTier network for the first time, capture
the reported ZeroTier node ID from the startup logs and authorize that member on
the controller before expecting `ZEROTIER_IP` resolution to complete.

Do not proceed until `/etc/simple-market-service/buyer-agent.env` contains a
canonical `ONCHAIN_AGENT_ID=eip155:...` value that is distinct from the seller's
identity.

If you disable `AUTO_REGISTER`, run the explicit registration step against the
same env file:

```bash
cd core/agent
make register ENV_FILE=/etc/simple-market-service/buyer-agent.env
```

## Verification

Verify the buyer's deployed ZeroTier URL and registration endpoints:

```bash
grep '^BASE_URL_OVERRIDE=' /etc/simple-market-service/buyer-agent.env
curl http://<buyer-zerotier-ip>:8000/.well-known/agent-card.json
curl http://<buyer-zerotier-ip>:8000/.well-known/erc-8004-registration.json
```

The buyer is ready for canary use only after the canonical `eip155:` agent ID
has been captured for the canary runner and the deployed buyer URL resolves over
ZeroTier.
