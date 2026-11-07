#!/usr/bin/env bash
# Exercise shipped roles through the image's Ansible; a skipped native test fails.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PYTHONDONTWRITEBYTECODE=1
export ANSIBLE_LOG_PATH=/dev/null
export ANSIBLE_ROLES_PATH="$PWD/ansible/roles"
ansible-playbook --version
ansible-galaxy collection list ansible.posix
ansible-playbook -i localhost, ansible/playbooks/relay-server.yaml --syntax-check
ansible-playbook -i localhost, ansible/playbooks/relay-task-files.yaml --syntax-check
# Each native test runs in its own interpreter, several at once. A skip, a failure,
# a test that ends without reporting its result, a module that cannot be imported,
# or a module name matching no test fails the gate.
"${PYTHON:-python3}" scripts/native_gate_runner.py tests \
  test_frp_proxy_wait.py test_frp_binary.py test_reclaim_barriers.py test_admission_installer.py
