#!/bin/sh
set -e

# Write SSH private key from env if provided
if [ -n "$SSH_PRIVATE_KEY" ]; then
    mkdir -p ~/.ssh
    chmod 700 ~/.ssh
    printf '%s' "$SSH_PRIVATE_KEY" | base64 -d > ~/.ssh/id_ed25519 2>/dev/null || \
        printf '%s\n' "$SSH_PRIVATE_KEY" > ~/.ssh/id_ed25519
    chmod 600 ~/.ssh/id_ed25519
    echo "SSH private key written to ~/.ssh/id_ed25519"
fi

# Write management-vars.yaml from env if provided
if [ -n "$MANAGEMENT_VARS_YAML" ]; then
    mkdir -p /app/compute-provisioning-iac/ansible/inventory
    printf '%s' "$MANAGEMENT_VARS_YAML" | base64 -d > /app/compute-provisioning-iac/ansible/inventory/management-vars.yaml 2>/dev/null || \
        printf '%s\n' "$MANAGEMENT_VARS_YAML" > /app/compute-provisioning-iac/ansible/inventory/management-vars.yaml
    chmod 600 /app/compute-provisioning-iac/ansible/inventory/management-vars.yaml
    echo "management-vars.yaml written to /app/compute-provisioning-iac/ansible/inventory/management-vars.yaml"
fi

# Start the background worker
uv run python -m async_provisioning_service.worker &
WORKER_PID=$!

# Start the API server
uv run uvicorn async_provisioning_service.main:app --host 0.0.0.0 --port 8081 &
SERVER_PID=$!

# If either process exits, shut down the other
trap "kill $WORKER_PID $SERVER_PID 2>/dev/null; exit 1" INT TERM

while kill -0 $WORKER_PID 2>/dev/null && kill -0 $SERVER_PID 2>/dev/null; do
    sleep 1
done

kill $WORKER_PID $SERVER_PID 2>/dev/null
exit 1
