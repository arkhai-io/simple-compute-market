#!/usr/bin/env bash
# Parse both domains with their own configuration and the shared image settings.
# These absolute paths are the provisioning image's packaged IaC locations.
set -euo pipefail
export ANSIBLE_LOG_PATH=/dev/null
cd /opt/domains/bare_metal/provisioning/iac
ANSIBLE_CONFIG=ansible/ansible.cfg ansible-playbook -i localhost, ansible/playbooks/node-access.yaml --syntax-check
ANSIBLE_CONFIG=ansible/ansible.cfg ansible-playbook -i localhost, ansible/playbooks/host-kit/host-setup.yaml --syntax-check
ANSIBLE_CONFIG="$(python -c 'from importlib.resources import files; print(files("compute_provisioning_ansible") / "ansible.cfg")')"
export ANSIBLE_CONFIG
test -f "$ANSIBLE_CONFIG"
cd /opt/domains/vms/provisioning/iac
IAC_SYNTAX_USE_ENV=1 bash scripts/validate_playbooks.sh
ansible-playbook -i localhost, /opt/domains/bare_metal/provisioning/iac/ansible/playbooks/node-access.yaml --syntax-check
ansible-playbook -i localhost, /opt/domains/bare_metal/provisioning/iac/ansible/playbooks/host-kit/host-setup.yaml --syntax-check
