"""The declared distributions follow from what each package declares."""

from __future__ import annotations

import os
import re
import tomllib
from functools import cache
from pathlib import Path

import pytest

from release_components import Distribution, load, normalise_distribution

REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASING = REPO_ROOT / "docs" / "development" / "RELEASING.md"
_SKIPPED_DIRS = {".git", ".venv", "node_modules", "openspec", "__pycache__", ".dist"}
_REQUIREMENT_NAME = re.compile(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def _distributions() -> tuple[Distribution, ...]:
    return load().distributions


def _find_links(package: Path) -> list[str]:
    declared = tomllib.loads((package / "pyproject.toml").read_text(encoding="utf-8"))
    return list(declared.get("tool", {}).get("uv", {}).get("find-links", []))


@pytest.mark.parametrize("package", _distributions(), ids=lambda entry: entry.key)
def test_a_declared_package_names_no_local_wheel_directory(package: Distribution) -> None:
    """A released wheel resolves its dependencies from an index, never a local directory.

    uv reads `find-links` even under `--no-sources`, so a directory named in a
    package's pyproject has to exist wherever that package is built, and on a
    fresh checkout none does. Projects therefore never declare the wheelhouse;
    the tools that sync and lock against it supply it.
    """

    directory = REPO_ROOT / package.path
    assert _find_links(directory) == [], (
        f"{package.dist} declares find-links {_find_links(directory)!r}; "
        "a released wheel resolves from an index"
    )


@cache
def _repository_distributions() -> dict[str, dict]:
    """Every distribution a project in the tree declares, by normalised name."""

    found: dict[str, dict] = {}
    for directory, subdirectories, files in os.walk(REPO_ROOT):
        subdirectories[:] = [name for name in subdirectories if name not in _SKIPPED_DIRS]
        if "pyproject.toml" not in files:
            continue
        declared = tomllib.loads((Path(directory) / "pyproject.toml").read_text(encoding="utf-8"))
        name = declared.get("project", {}).get("name")
        if name:
            found[normalise_distribution(name)] = declared["project"]
    return found


def _internal_dependencies(project: dict, repository: dict[str, dict]) -> dict[str, str]:
    """Repository distributions ``project`` requires, each with the extra that adds it.

    An extra counts: a consumer installing it resolves the dependency from
    the index exactly as it would a required one. Required dependencies map to "".
    """

    own = normalise_distribution(project["name"])
    found: dict[str, str] = {}
    sources = [("", project.get("dependencies", []))]
    sources += sorted(project.get("optional-dependencies", {}).items())
    for extra, requirements in sources:
        for requirement in requirements:
            name = normalise_distribution(_REQUIREMENT_NAME.match(requirement).group(1))
            if name in repository and name != own:
                found.setdefault(name, extra)
    return found


def _releasing_rows() -> dict[str, tuple[str, str]]:
    """RELEASING.md's published-package table: dist -> (path, internal deps cell)."""

    section = RELEASING.read_text(encoding="utf-8").split("## Published packages", 1)[1]
    section = section.split("\n## ", 1)[0]
    return {
        dist: (path.rstrip("/"), cell)
        for dist, path, cell in re.findall(
            r"^\| `([^`]+)` \| `([^`]+)` \| (.*) \|$", section, re.MULTILINE
        )
    }


@pytest.mark.parametrize("package", _distributions(), ids=lambda entry: entry.key)
def test_a_declared_package_depends_only_on_declared_packages(package: Distribution) -> None:
    """A released wheel resolves its repository dependencies from the same release.

    The build never notices a missing one: `uv build --no-sources` installs
    only the build backend. The first sign is an install that cannot resolve,
    found by whoever installs the package rather than by whoever released it.
    """

    repository = _repository_distributions()
    project = repository[normalise_distribution(package.dist)]
    declared = {normalise_distribution(entry.dist) for entry in _distributions()}
    missing = {
        name: extra
        for name, extra in _internal_dependencies(project, repository).items()
        if name not in declared
    }
    assert not missing, (
        f"{package.dist} depends on repository distributions the declaration omits: "
        + ", ".join(f"{name} (extra {extra})" if extra else name for name, extra in sorted(missing.items()))
    )


def test_the_declaration_lists_each_distribution_after_its_dependencies() -> None:
    """A publisher uploads in declaration order and stops at the first failure.

    Listing a dependency later than its dependent leaves an index, for the
    length of an upload or after a failed one, holding a distribution it cannot
    install.
    """

    repository = _repository_distributions()
    order = [normalise_distribution(entry.dist) for entry in _distributions()]
    position = {name: index for index, name in enumerate(order)}
    late = [
        f"{name} precedes its dependency {dependency}"
        for name in order
        for dependency in _internal_dependencies(repository[name], repository)
        if position.get(dependency, -1) > position[name]
    ]
    assert not late, "; ".join(late)


def test_each_declared_distribution_is_the_one_at_its_path() -> None:
    repository = _repository_distributions()
    for entry in _distributions():
        pyproject = REPO_ROOT / entry.path / "pyproject.toml"
        assert pyproject.is_file(), f"{entry.key}: {pyproject} does not exist"
        declared = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["name"]
        assert normalise_distribution(declared) == normalise_distribution(entry.dist), (
            f"{entry.key}: {entry.path} declares {declared}, not {entry.dist}"
        )
        assert normalise_distribution(declared) in repository


def test_the_release_guide_lists_exactly_the_declared_distributions() -> None:
    """The guide's table is documentation held equal to the declaration, not a
    second list anything reads."""
    rows = _releasing_rows()
    table = {entry.dist: entry.path for entry in _distributions()}
    assert {dist: path for dist, (path, _) in rows.items()} == table


@pytest.mark.parametrize("package", _distributions(), ids=lambda entry: entry.key)
def test_the_release_guide_states_each_package_internal_deps(package: Distribution) -> None:
    rows = _releasing_rows()
    if package.dist not in rows:
        pytest.fail(f"{package.dist} has no row in {RELEASING.name}")
    repository = _repository_distributions()
    _, cell = rows[package.dist]
    stated = {normalise_distribution(name) for name in re.findall(r"`([^`]+)`", cell)} & set(repository)
    declared = set(_internal_dependencies(repository[normalise_distribution(package.dist)], repository))
    assert stated == declared, (
        f"{RELEASING.name} states {sorted(stated)} for {package.dist}; "
        f"its pyproject declares {sorted(declared)}"
    )
