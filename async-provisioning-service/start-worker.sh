#!/bin/sh
set -e

# Write SSH private key from env if provided.
# The worker invokes ansible-playbook directly, so it needs the SSH key.
if [ -n "$SSH_PRIVATE_KEY" ]; then
    mkdir -p ~/.ssh
    chmod 700 ~/.ssh
    printf '%s' "$SSH_PRIVATE_KEY" | base64 -d > ~/.ssh/id_ed25519 2>/dev/null || \
        printf '%s\n' "$SSH_PRIVATE_KEY" > ~/.ssh/id_ed25519
    chmod 600 ~/.ssh/id_ed25519
    echo "SSH private key written to ~/.ssh/id_ed25519"
fi

# Write management-vars.yaml from env if provided.
if [ -n "$MANAGEMENT_VARS_YAML" ]; then
    mkdir -p /app/compute-provisioning-iac/ansible/inventory
    printf '%s' "$MANAGEMENT_VARS_YAML" | base64 -d > /app/compute-provisioning-iac/ansible/inventory/management-vars.yaml 2>/dev/null || \
        printf '%s\n' "$MANAGEMENT_VARS_YAML" > /app/compute-provisioning-iac/ansible/inventory/management-vars.yaml
    chmod 600 /app/compute-provisioning-iac/ansible/inventory/management-vars.yaml
    echo "management-vars.yaml written"
fi

echo "Starting provisioning worker..."
exec uv run python -m async_provisioning_service.worker