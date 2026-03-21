# Registry Deployment

This document covers deployment of the ERC-8004 registry for the production
canary path.

## Inputs

- `erc-8004-registry-py/.env.production.sample`
- a host-local runtime env file at `/etc/simple-market-service/registry.env`
- a PostgreSQL database for the registry
- an authenticated `RPC_URL`
- verified ERC-8004 contract addresses for the target network
- a runtime host that is already joined to the ZeroTier network when the
  registry must be reachable over the overlay

## Image

The registry image is built from `erc-8004-registry-py/Dockerfile`. The repo's
default CI publish path is defined in
`.github/workflows/docker-build-push-erc8004-registry.yml`.

Prefer the shared image manifest from
`docs/standup/image-selection.md` at `/etc/simple-market-service/image-manifest.env`.
Choose the exact immutable image tag or digest before deployment:

```bash
set -a
. /etc/simple-market-service/image-manifest.env
set +a
gcloud auth print-access-token \
  | sudo docker login -u oauth2accesstoken --password-stdin https://<region>-docker.pkg.dev
sudo docker pull "${REGISTRY_IMAGE}"
```

## Host Preparation

Create the host-local env bundle and populate it from the deployed sample:

```bash
sudo install -d -m 0755 /etc/simple-market-service
sudo cp erc-8004-registry-py/.env.production.sample /etc/simple-market-service/registry.env
```

Edit `/etc/simple-market-service/registry.env` with the real deployment values.
The required env bundle must include at least:

- `DATABASE_URL`
- `CHAIN_ID`
- `RPC_URL`
- `IDENTITY_REGISTRY_ADDRESS`
- `REPUTATION_REGISTRY_ADDRESS`
- `VALIDATION_REGISTRY_ADDRESS`
- `HOST=0.0.0.0`
- `PORT=8080`
- `ZEROTIER_NETWORK` when joining the overlay directly

Use `.env.production.sample` as the source template, not `.env.sample`.

For deployed canaries, run the registry container on a host that is already joined to the ZeroTier network before you start the container. In other words, the host is already joined to the ZeroTier network before the registry process starts. The registry image does not join ZeroTier from inside the container.

The registry process initializes tables at startup via `init_db()`. The Makefile
still exposes `make migrate` for development and schema maintenance, but the
deployed canary path should treat the runtime env contract as the primary
requirement.

## Container Launch

For the deployed canary path, run the containerized registry rather than the
bare `uvicorn` example from the service README:

```bash
sudo docker rm -f sms-registry 2>/dev/null || true

sudo docker run -d \
  --name sms-registry \
  --restart unless-stopped \
  --env-file /etc/simple-market-service/registry.env \
  -p 8080:8080 \
  "${REGISTRY_IMAGE}"
```

## Verification

After deployment, verify:

```bash
sudo docker ps --filter name=sms-registry
sudo docker logs --tail 200 sms-registry
curl http://<registry-host>:8080/health
```

and confirm that the URL is reachable from the canary runner over the intended
network path.

## Outputs

- `REGISTRY_URL`
