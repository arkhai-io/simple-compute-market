"""Run one test file against an earlier commit, in the environment that owns it.

The change workflow's `run test-before` checks the earlier commit out in a
throwaway worktree, copies the test file in as `HEAD` holds it, and runs this
script there with the file's path. The engine runs the checkout's copy of the
script, not the worktree's, since an earlier commit may predate it.

- A test no project owns, as the scripts' own, runs with no built environment.
- A test a project owns runs in that project's environment, synced against a
  wheelhouse in the worktree. The wheelhouse starts as a copy of the checkout's,
  so nothing is rebuilt by default: the project's own code is the worktree's
  source, the earlier commit's. When the code under test sits in an internal
  dependency, the caller names the root `make` targets that rebuild its wheels
  from the earlier commit in `TEST_BEFORE_DIST`, comma or space separated, such
  as `dist-compute-provisioning`; `dist` rebuilds every wheel.

It exits as the test run does; a build or sync failure exits 2 before it.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

WHEELHOUSE = ".dist"
TARGETS_VARIABLE = "TEST_BEFORE_DIST"
# What a test no project owns runs with: the scripts' suites' own requirements.
UNOWNED = ("uv", "run", "--no-project", "--with", "pytest", "--with", "pyyaml",
           "pytest", "-q")

Runner = Callable[[Sequence[str], Path], int]


def owning_project(root: Path, test: Path) -> Path | None:
    """The nearest directory above `test`, below `root`, with a `pyproject.toml`."""
    directory = (root / test).parent
    while directory != root and root in directory.parents:
        if (directory / "pyproject.toml").is_file():
            return directory
        directory = directory.parent
    return None


def dist_targets(value: str | None) -> list[str]:
    """The `make` targets `TEST_BEFORE_DIST` names; each must be a `dist` target."""
    targets = [target for target in re.split(r"[,\s]+", value or "") if target]
    for target in targets:
        if not re.fullmatch(r"dist(-[a-z0-9-]+)?", target):
            raise ValueError(f"{TARGETS_VARIABLE} names {target!r}, which is no dist target")
    return targets


def plan(root: Path, test: Path, targets: Sequence[str]) -> tuple[list[tuple[list[str], Path]], tuple[list[str], Path]]:
    """The preparing commands, in order, and the test run, each with its directory."""
    project = owning_project(root, test)
    if project is None:
        return [], ([*UNOWNED, str(test)], root)
    preparing = [(["make", target, f"DIST_DIR={root / WHEELHOUSE}"], root) for target in targets]
    preparing.append((["python3", str(root / "scripts" / "uv_project.py"), "reinit",
                       "--project", str(project)], root))
    return preparing, (["uv", "run", "--no-sync", "pytest", "-q",
                        str((root / test).relative_to(project))], project)


def seed_wheelhouse(checkout: Path, root: Path) -> None:
    """Copy the checkout's wheelhouse into the worktree's, which the worktree lacks."""
    source = checkout / WHEELHOUSE
    if not source.is_dir():
        raise FileNotFoundError(f"{source} does not exist: run `make dist` in the checkout first")
    shutil.copytree(source, root / WHEELHOUSE, dirs_exist_ok=True)


def checkout_root(root: Path) -> Path:
    """The checkout the worktree was added from: its common Git directory's parent."""
    common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            cwd=root, capture_output=True, text=True, check=True)
    return Path(common.stdout.strip()).parent


def _run(command: Sequence[str], cwd: Path) -> int:
    print("+ " + " ".join(command), file=sys.stderr, flush=True)
    return subprocess.run(list(command), cwd=cwd).returncode


def main(argv: Sequence[str] | None = None, *, root: Path | None = None,
         checkout: Path | None = None, run: Runner = _run,
         environ: dict[str, str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: test_before.py <test file>", file=sys.stderr)
        return 2
    root = (root or Path.cwd()).resolve()
    test = Path(args[0])
    try:
        targets = dist_targets((os.environ if environ is None else environ).get(TARGETS_VARIABLE))
        preparing, testing = plan(root, test, targets)
        if preparing:
            seed_wheelhouse((checkout or checkout_root(root)).resolve(), root)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"test_before: {exc}", file=sys.stderr)
        return 2
    for command, cwd in preparing:
        if run(command, cwd) != 0:
            print(f"test_before: {' '.join(command)} failed, so the test did not run",
                  file=sys.stderr)
            return 2
    return run(*testing)


if __name__ == "__main__":
    sys.exit(main())
