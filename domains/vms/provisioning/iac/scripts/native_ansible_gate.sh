#!/usr/bin/env bash
# The VM IaC's native Ansible gate: every playbook's syntax check, then the tests
# that run shipped tasks through a real ansible-playbook, with the Ansible first on
# PATH. Where the default test run skips those tests for want of ansible-core 2.17
# to 2.19 or the ansible.posix json callback, this gate fails: a skipped test fails
# it, and so does finding no test to run.
#
# `make test-provisioning-iac-native` runs it in the built provisioning image,
# whose Ansible and collections are the ones that run these roles. It needs only
# the standard library and PyYAML beside that Ansible, and writes nothing in this
# tree.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
PYTHON="${PYTHON:-python3}"
export PYTHONDONTWRITEBYTECODE=1
# ansible.cfg logs beside itself; a check run keeps no log.
export ANSIBLE_LOG_PATH=/dev/null

ansible-playbook --version
ansible-galaxy collection list ansible.posix

bash scripts/validate_playbooks.sh

"$PYTHON" - <<'EOF'
import sys
import unittest

# The modules that run a shipped task through ansible-playbook. Each skips
# without a supported Ansible and its callback; here a skip is a failure.
NATIVE = ["test_frp_proxy_wait.py"]

suite = unittest.TestSuite(
    unittest.defaultTestLoader.discover("tests", pattern=name, top_level_dir="tests")
    for name in NATIVE
)
result = unittest.TextTestRunner(verbosity=2).run(suite)
for test, reason in result.skipped:
    print(f"native gate: {test.id()} was skipped: {reason}", file=sys.stderr)
if result.testsRun == 0:
    print("native gate: no native test ran", file=sys.stderr)
sys.exit(0 if result.wasSuccessful() and result.testsRun and not result.skipped else 1)
EOF
