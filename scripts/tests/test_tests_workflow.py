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


def test_the_scripts_job_installs_the_change_workflow_from_the_tree() -> None:
    """The job running the scripts' suites, `test-deployment-packaging` through
    `test-release-tooling`, installs the change workflow built from the tree — its
    command and its skills — before it runs them, writing no local configuration into
    the checkout, whose committed configuration CI checks alone."""

    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    tool = next(i for i, line in enumerate(lines)
                if line.strip() == "uv tool install --force scripts/change-workflow-wheel")
    step = max(i for i in range(tool) if lines[i].startswith("      - "))
    end = next(i for i in range(tool, len(lines)) if lines[i].startswith("      - "))
    run = next(i for i, line in enumerate(lines)
               if line.strip() == "run: make ${{ matrix.target }}")

    assert lines[step].strip() == "- if: matrix.target == 'test-deployment-packaging'"
    assert step < tool < end <= run
    install = [line.strip() for line in lines[tool:end] if "change-workflow\" install" in line]
    assert install == ['cd "$RUNNER_TEMP" && "$bin/change-workflow" install']
    assert re.search(r"^test-deployment-packaging: test-release-tooling\b",
                     MAKEFILE.read_text(encoding="utf-8"), re.MULTILINE)


def test_the_scripts_job_names_each_skipped_test() -> None:
    """The job running the scripts' suites under `SANDBOX_REQUIRED=1` reports every
    test that skips, with its reason, so its log shows which test skipped rather than
    a bare count: a skip no gate turns into a failure, such as the Codex sandbox
    test's where Codex is absent, is then read, not inferred. `-r` replaces pytest's
    default summary, so it keeps `fE`, the failures and errors whose lines the CI
    evidence reads failing tests from."""

    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    run = next(i for i, line in enumerate(lines)
               if line.strip() == "run: make ${{ matrix.target }}")
    step = max(i for i in range(run) if lines[i].startswith("      - "))
    env = [line.strip() for line in lines[step:run]]

    assert lines[step].strip() == "- name: make ${{ matrix.target }}"
    assert ("PYTEST_ADDOPTS: ${{ matrix.target == 'test-deployment-packaging' "
            "&& '-rfEs' || '' }}") in env
    assert ("SANDBOX_REQUIRED: ${{ matrix.target == 'test-deployment-packaging' "
            "&& '1' || '' }}") in env
