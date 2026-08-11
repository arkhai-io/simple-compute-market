"""A project that ships its own modules must reinstall itself in `reinit`.

A force-include wheel installs its modules into its own virtual environment, and
its tests import them from there rather than from the source tree. `uv sync` will
not replace a wheel whose version has not changed, so a source edit stays
invisible until something forces a reinstall. The result is a suite that passes
or fails against whatever was installed first — which has produced a false
failure and hidden a real fix in this repository more than once.

Projects using a `src` layout are exempt: installed and source resolve to the
same import path, so staleness there is benign.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _force_include_projects() -> list[tuple[Path, str]]:
    found: list[tuple[Path, str]] = []
    for pyproject in REPO.rglob("pyproject.toml"):
        if ".venv" in pyproject.parts or "node_modules" in pyproject.parts:
            continue
        data = tomllib.loads(pyproject.read_text())
        name = data.get("project", {}).get("name")
        if not name:
            continue
        wheel = (
            data.get("tool", {}).get("hatch", {})
            .get("build", {}).get("targets", {}).get("wheel", {})
        )
        if "force-include" in wheel and (pyproject.parent / "Makefile").exists():
            found.append((pyproject.parent, name))
    return sorted(found)


PROJECTS = _force_include_projects()


def test_the_audit_finds_projects_to_check() -> None:
    """Guard against the discovery silently matching nothing."""
    assert PROJECTS, "no force-include projects found — has the layout changed?"


@pytest.mark.parametrize(
    "project,name", PROJECTS, ids=[name for _, name in PROJECTS]
)
def test_reinit_reinstalls_the_project_itself(project: Path, name: str) -> None:
    makefile = (project / "Makefile").read_text()
    recipe = re.search(r"^reinit:.*?\n((?:\t.*\n)+)", makefile, re.M)
    if recipe is None:
        pytest.skip(f"{name} has no reinit recipe")

    assert f"--reinstall-package {name}" in recipe.group(1), (
        f"{name} ships its own modules but its reinit does not reinstall it, so "
        f"`make test` in {project.relative_to(REPO)} runs against whatever wheel "
        "was installed first rather than the working tree"
    )
