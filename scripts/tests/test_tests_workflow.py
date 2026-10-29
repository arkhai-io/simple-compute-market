"""The Tests workflow runs what `make test` runs, target for target."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tests.yml"
MAKEFILE = REPO_ROOT / "Makefile"


def _make_test_targets() -> list[str]:
    """The prerequisites of the root `test` target, in order."""

    match = re.search(r"^test:([^#\n]*)", MAKEFILE.read_text(encoding="utf-8"), re.MULTILINE)
    assert match, "the root Makefile has no `test` target"
    return match.group(1).split()


def _matrix_targets() -> list[str]:
    """The `target` list of the workflow's test matrix.

    Read line by line rather than through a YAML parser, which the scripts
    suite does not install: the list is the indented `- name` lines under
    `target:`.
    """

    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "target:")
    indent = len(lines[start]) - len(lines[start].lstrip())
    targets = []
    for line in lines[start + 1:]:
        if len(line) - len(line.lstrip()) <= indent:
            break
        item = line.strip()
        assert item.startswith("- "), f"unexpected matrix line {line!r}"
        targets.append(item[2:].strip())
    return targets


def test_the_matrix_is_make_tests_targets() -> None:
    """A target added to `make test` but not to the matrix would pass a
    change's validation locally and never run in CI, and one only in the
    matrix would run in CI alone; either way the two stop agreeing."""

    assert _matrix_targets() == _make_test_targets()
