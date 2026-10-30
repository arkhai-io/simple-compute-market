#!/usr/bin/env bash
# Syntax-check every playbook this tree ships, the parse-only ones included, with
# the ansible-playbook first on PATH. `make validate-playbooks` and the native
# Ansible gate both run this script, so the list is kept here once.
#
# A syntax check parses a playbook and what it imports statically; it templates
# nothing and executes nothing. The parse-only playbooks import the task files
# their roles reach only through include_tasks, which a syntax check of the role's
# own playbook does not follow.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
export ANSIBLE_CONFIG=ansible/ansible.cfg

PLAYBOOKS=(
  ansible/playbooks/frp/frp-server-setup.yaml
  ansible/playbooks/frp/docker-app-setup.yaml
  ansible/playbooks/host-kit/vm-setup.yaml
  ansible/playbooks/host-kit/vm-setup-task-files.yaml
  ansible/playbooks/host-kit/passthrough-audit.yaml
  ansible/playbooks/single-tenant/vm-operations.yaml
  ansible/playbooks/single-tenant/vm-management-task-files.yaml
)

for playbook in "${PLAYBOOKS[@]}"; do
  ansible-playbook -i ansible/inventory/ "$playbook" --syntax-check
done
echo "syntax-checked ${#PLAYBOOKS[@]} playbooks"
