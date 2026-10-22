"""`make init` bootstraps a checkout whose `.dist` holds nothing.

Each role's environment installs every internal package its lock names from
`.dist`, so each `init-*` target must build a wheel for each of them first. A
workspace's `.dist` is filled by earlier builds and hides a missing one; a fresh
clone's bootstrap does not. Read through `make -n` over the real Makefiles: a
recursive `$(MAKE)` still runs under `-n`, printing the commands of the targets it
reaches, so every wheel build the target would make is printed.
"""

from __future__ import annotations

import os
import re
import subprocess
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_ENTERING = re.compile(r"^make(?:\[\d+\])?: Entering directory '(?P<dir>[^']+)'$")
_LEAVING = re.compile(r"^make(?:\[\d+\])?: Leaving directory ")
# A wheel build as the dist targets write it: `cd <project> && uv build …` or
# `cd <project> && make build …`.
_BUILD = re.compile(r"cd (?P<dir>\S+) && (?:uv build|\S*make build)")


def _normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _projects() -> dict[str, Path]:
    """Every tracked project's distribution name, to its directory; untracked
    checkouts under the tree hold copies that would shadow them."""
    listed = subprocess.run(["git", "ls-files", "*pyproject.toml"], cwd=REPO_ROOT,
                            capture_output=True, text=True, check=True).stdout.split()
    found: dict[str, Path] = {}
    for path in listed:
        name = tomllib.loads((REPO_ROOT / path).read_text("utf-8")).get(
            "project", {}).get("name")
        if name:
            found[_normalized(name)] = (REPO_ROOT / path).parent.resolve()
    return found


def _internal(lock: Path) -> set[str]:
    """The packages a lock installs from `.dist`."""
    packages = tomllib.loads(lock.read_text("utf-8")).get("package", [])
    return {_normalized(package["name"]) for package in packages
            if Path(str(package.get("source", {}).get("registry", ""))).name == ".dist"}


def _built(target: str, dist: Path) -> set[Path]:
    """The project directories `make -n <target>` builds a wheel in."""
    # The directory messages are read in English, one make at a time.
    environment = {name: value for name, value in os.environ.items()
                   if name not in ("MAKEFLAGS", "GNUMAKEFLAGS", "MFLAGS", "MAKELEVEL",
                                   "CHANGE")} | {"LC_ALL": "C"}
    printed = subprocess.run(["make", "-n", "-w", target, f"DIST_DIR={dist}"], cwd=REPO_ROOT,
                             env=environment, capture_output=True, text=True,
                             check=True).stdout
    directories, built = [REPO_ROOT], set()
    for line in printed.splitlines():
        if entering := _ENTERING.match(line):
            directories.append(Path(entering["dir"]))
        elif _LEAVING.match(line) and len(directories) > 1:
            directories.pop()
        elif build := _BUILD.search(line):
            built.add((directories[-1] / build["dir"]).resolve())
    return built


def test_init_creates_every_environment_the_helm_render_checks_load_with() -> None:
    # `make -n init` prints each role's `cd <project> && make init`.
    environment = {name: value for name, value in os.environ.items()
                   if name not in ("MAKEFLAGS", "GNUMAKEFLAGS", "MFLAGS", "MAKELEVEL",
                                   "CHANGE")} | {"LC_ALL": "C"}
    printed = subprocess.run(["make", "-n", "init", "DIST_DIR=/nonexistent-dist"],
                             cwd=REPO_ROOT, env=environment, capture_output=True, text=True,
                             check=True).stdout
    for project in ("domains/vms/storefront", "domains/bare_metal/storefront"):
        assert f"cd {project} && make init" in printed, project


@pytest.mark.parametrize(("target", "project"), [
    ("init-buyer", "domains/vms/buyer"),
    ("init-storefront", "domains/vms/storefront"),
    ("init-bare-metal-storefront", "domains/bare_metal/storefront"),
    ("init-arkhai-core-registry", "core/registry"),
])
def test_each_init_target_builds_every_wheel_its_lock_installs(tmp_path: Path, target: str,
                                                                project: str) -> None:
    projects = _projects()
    needed = _internal(REPO_ROOT / project / "uv.lock")
    assert needed, f"{project}'s lock installs nothing from .dist"

    built = _built(target, tmp_path / "dist")

    missing = sorted(name for name in needed if projects.get(name) not in built)
    assert not missing, f"{target} builds no wheel for {', '.join(missing)}"
