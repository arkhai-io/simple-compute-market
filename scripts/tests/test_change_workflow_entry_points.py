"""The scripts the Makefile, the skills, the step table, and the hook run by path
reach the engine's modules, and act on the checkout they sit in from any directory.

Each runs as its callers run it, a Python process started on its path, from a
directory no repository contains. Its arguments get it past finding the
repository, which outside one it would refuse, and stop it before it changes
anything: a change name no change may have, or a read-only action. An integration
test, since what is proven is the process's working directory.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
NOT_IN_REPOSITORY = "is not inside a Git repository"


@pytest.mark.parametrize("script,args,statuses,shown", [
    ("find_change.py", ["archive"], {1}, "'archive' is not a change name"),
    ("change_next_step.py", ["archive"], {1}, "'archive' is not a change name"),
    ("check_tasks.py", ["archive"], {2}, "'archive' is not a change name"),
    ("change_clone.py", ["remove", "archive"], {1}, "archive"),
    ("change_history.py", ["sync", "archive"], {1}, "ERROR"),
    ("change_cost.py", ["archive"], {1}, "'archive' is not a change name"),
    ("run_change_step.py", ["log", "archive"], {1}, "'archive' is not a change name"),
    # These read the checkout and change nothing, so what they print is its own.
    ("round_view.py", ["check"], {0, 1}, ""),
    ("check_push_ready.py", ["check"], {0, 1}, "push"),
    ("check_change_index.py", [], {0, 1}, "openspec/changes/README.md"),
    ("check_agent_skills.py", [], {0, 1}, "agent skill"),
    ("post_compaction_context.py", [], {0}, "Checked-out branch:"),
])
def test_an_entry_point_runs_its_module_on_its_own_checkout(
        tmp_path: Path, script: str, args: list[str], statuses: set[int], shown: str) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    environ = {**os.environ, "GIT_CEILING_DIRECTORIES": str(tmp_path)}

    ran = subprocess.run([sys.executable, str(SCRIPTS / script), *args], cwd=outside,
                         env=environ, capture_output=True, text=True, check=False)

    printed = ran.stdout + ran.stderr
    assert ran.returncode in statuses, printed
    assert shown in printed
    assert NOT_IN_REPOSITORY not in printed and "Traceback" not in printed
    assert list(outside.iterdir()) == []
