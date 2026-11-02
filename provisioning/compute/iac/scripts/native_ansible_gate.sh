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
"${PYTHON:-python3}" - <<'EOF'
import sys
import unittest

NATIVE = ["test_frp_proxy_wait.py", "test_frp_binary.py", "test_reclaim_barriers.py", "test_admission_installer.py"]
suite = unittest.TestSuite(
    unittest.defaultTestLoader.discover("tests", pattern=name, top_level_dir="tests")
    for name in NATIVE
)
result = unittest.TextTestRunner(verbosity=2).run(suite)
for test, reason in result.skipped:
    print(f"native gate: {test.id()} skipped: {reason}", file=sys.stderr)
sys.exit(0 if result.wasSuccessful() and result.testsRun and not result.skipped else 1)
EOF
