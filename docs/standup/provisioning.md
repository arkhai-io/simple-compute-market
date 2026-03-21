# Provisioning Deployment

This document covers the deployed async provisioning API and worker path.

## Inputs

- `async-provisioning-service/.env.production.sample`
- a host-local runtime env file at `/etc/simple-market-service/provisioning.env`
- a host-local provisioning secret bundle at `/etc/simple-market-service/management-vars.yaml`
- `compute-provisioning-iac/ansible/inventory/hosts`
- PostgreSQL for provisioning state
- Redis for the provisioning job queue
- `SSH_PRIVATE_KEY`
- `MANAGEMENT_VARS_YAML`
- FRP dashboard credentials from the FRP setup phase

## Image

The async provisioning image is built from
`async-provisioning-service/Dockerfile`. The repo's default CI publish path is
defined in `.github/workflows/docker-build-push-async-provisioning.yml`.

Choose the exact immutable image tag or digest before deployment:

```bash
export PROVISIONING_IMAGE="us-east4-docker.pkg.dev/<gcp-project>/async-provisioning-service/async-provisioning-service:<tag-or-digest>"
sudo docker pull "${PROVISIONING_IMAGE}"
```

## Host Preparation

Use `.env.production.sample` as the source template.

Prepare the host-local env and secret files:

```bash
sudo install -d -m 0755 /etc/simple-market-service
sudo cp async-provisioning-service/.env.production.sample /etc/simple-market-service/provisioning.env
sudo install -m 0600 /path/to/management-vars.yaml /etc/simple-market-service/management-vars.yaml
```

Edit `/etc/simple-market-service/provisioning.env` so the deployed env includes
at least:

- `DATABASE_URL`
- `REDIS_URL`
- `REDIS_QUEUE_NAME`
- `DEFAULT_VM_HOST`
- `ANSIBLE_BECOME_PASS`
- `ENABLE_AUTH=true`
- `AUTH_FAIL_OPEN=false`
- `REGISTRY_URL`
- `FRP_SERVER_ADDR`
- `FRP_DOMAIN`
- `FRP_DASHBOARD_PASSWORD`
- `SSH_PRIVATE_KEY`
- `MANAGEMENT_VARS_YAML`

`DEFAULT_VM_HOST` must match an alias in
`compute-provisioning-iac/ansible/inventory/hosts`.

`MANAGEMENT_VARS_YAML` is not a checked-in tracked secret. Generate the real
`management-vars.yaml` file through the IaC host-kit workflow, then base64-encode
it for container injection as documented in `compute-provisioning-iac/README.md`.

## Container Launch

Deploy the service through `compute-provisioning-iac` using
`playbooks/frp/docker-app-setup.yaml`, or launch the already-built container
directly with the same env contract. In either case, the worker must start
alongside the API. The container entrypoint launches both the API server and the
background worker in the same container.

```bash
sudo docker rm -f sms-provisioning 2>/dev/null || true

sudo docker run -d \
  --name sms-provisioning \
  --restart unless-stopped \
  --env-file /etc/simple-market-service/provisioning.env \
  -e MANAGEMENT_VARS_YAML="$(base64 < /etc/simple-market-service/management-vars.yaml | tr -d '\n')" \
  -p 8081:8081 \
  "${PROVISIONING_IMAGE}"
```

## Verification

After deployment, verify:

```bash
curl http://<provisioning-host>:8081/health
```

and ensure the response reports both DB and Redis health. Also confirm the
container logs show the worker booting alongside the API process.

## Outputs

- `PROVISIONING_SERVICE_URL`
- a reachable provisioning API and worker pair
