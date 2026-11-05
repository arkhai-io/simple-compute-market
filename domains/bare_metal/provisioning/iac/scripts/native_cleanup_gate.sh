#!/usr/bin/env bash
# This gate runs only inside the dedicated disposable container created by the
# root target. It never accepts host account paths or an external scratch path.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
: "${BARE_METAL_DISPOSABLE_NATIVE:?use make test-bare-metal-iac-native}"
[[ "$BARE_METAL_DISPOSABLE_NATIVE" == "private-container-v1" ]]
[[ "$EUID" == 0 && -f /.dockerenv ]]
[[ -d /work && ! -L /work ]]
awk '$2 == "/work" && $3 == "tmpfs" { found=1 } END { exit !found }' /proc/mounts
PYTHON="${PYTHON:-python3}"
export PYTHONDONTWRITEBYTECODE=1
ansible-playbook --version
"$PYTHON" - <<'PY'
import os
from pathlib import Path
import sys
import unittest

root = Path.cwd()
sys.path.insert(0, str(root / "ansible/roles/bare-metal-access/files"))
suite = unittest.defaultTestLoader.discover("tests/integration", pattern="test_native*.py")
result = unittest.TextTestRunner(verbosity=2, failfast=True).run(suite)
for test, reason in result.skipped:
    print(f"native gate skipped: {test.id()}: {reason}", file=sys.stderr)
if not result.testsRun:
    print("native gate: no tests ran", file=sys.stderr)
sys.exit(0 if result.wasSuccessful() and result.testsRun and not result.skipped else 1)
PY
