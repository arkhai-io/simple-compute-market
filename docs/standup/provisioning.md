# Provisioning Deployment

This document covers the deployed async provisioning API and worker path.

## Inputs

- `async-provisioning-service/.env.production.sample`
- `compute-provisioning-iac/ansible/inventory/hosts`
- PostgreSQL for provisioning state
- Redis for the provisioning job queue
- `SSH_PRIVATE_KEY`
- `MANAGEMENT_VARS_YAML`
- FRP dashboard credentials from the FRP setup phase

## Required Runtime Contract

Use `.env.production.sample` as the source template.

The deployed env must include at least:

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

## Deployment Path

Deploy the service through `compute-provisioning-iac` using
`playbooks/frp/docker-app-setup.yaml`, and ensure the worker starts alongside
the API. The container entrypoint launches both.

## Verification

After deployment, verify:

```bash
curl http://<provisioning-host>:8081/health
```

and ensure the response reports both DB and Redis health.

Outputs from this phase:

- `PROVISIONING_SERVICE_URL`
- a reachable provisioning API and worker pair
