# Provisioning Deployment

This document covers the deployed async provisioning API and worker path.

Before you edit `/etc/simple-market-service/provisioning.env` directly, define
the local source-of-truth in `docs/standup/local-secrets.md` and render the
host-local bundle with `python scripts/materialize_host_envs.py --local-secrets-dir ~/.config/simple-market-service --output-dir /etc/simple-market-service`.

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

Prefer the shared image manifest from
`docs/standup/image-selection.md` at `/etc/simple-market-service/image-manifest.env`.
Choose the exact immutable image tag or digest before deployment:

```bash
set -a
. /etc/simple-market-service/image-manifest.env
set +a
gcloud auth print-access-token \
  | sudo docker login -u oauth2accesstoken --password-stdin https://<region>-docker.pkg.dev
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

If you are using the canonical local secret layout under
`~/.config/simple-market-service`, prefer the renderer instead of hand-editing
these files:

```bash
python scripts/materialize_host_envs.py \
  --local-secrets-dir ~/.config/simple-market-service \
  --output-dir /etc/simple-market-service
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

Start from `compute-provisioning-iac/ansible/inventory/vm-vars-example.yaml` for
the VM-operation contract, then keep a separate
`/etc/simple-market-service/management-vars.yaml` bundle for the golden-image
metadata used by provisioning. At minimum, that secret bundle should define:

```yaml
root_ssh_filename: <root-ssh-key-filename-on-kvm-host>
golden_image_name: <published-golden-image-name>
gcs_bucket_url: gs://<golden-image-bucket>
gcs_image_path: <golden-image-object-prefix>
```

`image_setup_type=scratch does not require management-vars.yaml`. Use the
bundle only when `image_setup_type=golden requires management-vars.yaml`.

For the direct-run path, the image already contains the checked-in
`compute-provisioning-iac/ansible/inventory/hosts` file. The container startup
script materializes `MANAGEMENT_VARS_YAML` at
`/app/compute-provisioning-iac/ansible/inventory/management-vars.yaml`, so the
operator only needs to choose a valid `DEFAULT_VM_HOST` alias and inject the
real `management-vars.yaml` content at launch time.

Do not try to store multi-line SSH keys in `/etc/simple-market-service/provisioning.env`.
Keep the real private key on disk and inject it at container launch time via
base64 so startup can write it to `~/.ssh/id_ed25519`.

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
  -e SSH_PRIVATE_KEY="$(base64 < /path/to/id_ed25519 | tr -d '\n')" \
  -e MANAGEMENT_VARS_YAML="$(base64 < /etc/simple-market-service/management-vars.yaml | tr -d '\n')" \
  -p 8081:8081 \
  "${PROVISIONING_IMAGE}"
```

## Verification

After deployment, verify:

```bash
sudo docker logs --tail 200 sms-provisioning
curl http://<provisioning-host>:8081/health
```

and ensure the response reports both DB and Redis health. Also confirm the
container logs show:

- `SSH private key written to ~/.ssh/id_ed25519`
- `management-vars.yaml written to /app/compute-provisioning-iac/ansible/inventory/management-vars.yaml`
- the worker booting alongside the API process

## Outputs

- `PROVISIONING_SERVICE_URL`
- a reachable provisioning API and worker pair
