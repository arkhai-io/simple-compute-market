"""What the publish workflow builds follows from what each package declares."""

from __future__ import annotations

import json
import os
import re
import tomllib
from functools import cache
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "manifests" / "published-distributions.json"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "publish-pypi.yml"
RELEASING = REPO_ROOT / "docs" / "development" / "RELEASING.md"
_SKIPPED_DIRS = {".git", ".venv", "node_modules", "openspec", "__pycache__", ".dist"}
_REQUIREMENT_NAME = re.compile(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def _packages() -> list[dict[str, object]]:
    """Every distribution this repository publishes.

    Read from the manifest rather than from a workflow heredoc. The workflow
    stated its own table and the Makefile stated another; the two disagreed in
    both directions, which is what one declaration prevents.
    """

    return json.loads(MANIFEST.read_text(encoding="utf-8"))["distributions"]


def _escaping_force_includes(package: Path) -> list[str]:
    """Wheel contents this package pulls from outside its own directory.

    A `../` source is the thing an sdist tarball cannot carry: the tarball is
    rooted at the package, so `uv build`'s default sdist->wheel rebuild finds
    nothing at that path and fails.
    """

    declared = tomllib.loads((package / "pyproject.toml").read_text(encoding="utf-8"))
    forced = (
        declared.get("tool", {})
        .get("hatch", {})
        .get("build", {})
        .get("targets", {})
        .get("wheel", {})
        .get("force-include", {})
    )
    return sorted(source for source in forced if source.startswith("../"))


@pytest.mark.parametrize("package", _packages(), ids=lambda entry: str(entry["key"]))
def test_a_package_reaching_outside_itself_publishes_a_wheel_only(
    package: dict[str, object],
) -> None:
    """The two facts have to agree, and only one of them was maintained.

    The workflow's own comment says why the buyer plugins are wheel-only, and
    names them as if that set were closed. `vms-storefront` acquired the same
    `../` force-includes and nothing noticed, so every publish of it since has
    died inside `hatchling.build.build_wheel` with `Forced include not found`
    pointing at a path in uv's sdist cache -- a message that names neither the
    package nor the reason.
    """

    directory = REPO_ROOT / str(package["path"])
    if not (directory / "pyproject.toml").is_file():
        pytest.skip(f"{package['path']} is not checked out here")

    escaping = _escaping_force_includes(directory)
    if not escaping:
        return

    assert package.get("wheel_only") is True, (
        f"{package['dist']} force-includes {escaping} from outside {package['path']}, "
        "which an sdist cannot carry; publish it as a wheel only"
    )


def _find_links(package: Path) -> list[str]:
    declared = tomllib.loads((package / "pyproject.toml").read_text(encoding="utf-8"))
    return list(declared.get("tool", {}).get("uv", {}).get("find-links", []))


@pytest.mark.parametrize("package", _packages(), ids=lambda entry: str(entry["key"]))
def test_a_published_package_names_no_local_wheel_directory(
    package: dict[str, object],
) -> None:
    """A publish build resolves from PyPI and consults no local directory.

    uv reads `find-links` even under `--no-sources`, so a directory named in a
    package's pyproject has to exist wherever that package is built, and on a
    fresh publish checkout none does. Projects therefore never declare the
    wheelhouse; the tools that sync and lock against it supply it.
    """

    directory = REPO_ROOT / str(package["path"])
    if not (directory / "pyproject.toml").is_file():
        pytest.skip(f"{package['path']} is not checked out here")

    assert _find_links(directory) == [], (
        f"{package['dist']} declares find-links {_find_links(directory)!r}; "
        "a publish build resolves from PyPI"
    )



def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _workflow_packages() -> list[dict[str, object]]:
    """The `PACKAGES` table the publish workflow builds its matrix from."""

    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"cat > packages\.json <<'JSON'\n(.*?)\n\s*JSON\n", text, re.DOTALL)
    assert match, f"{WORKFLOW} has no packages.json heredoc"
    return json.loads(match.group(1))


def _workflow_filters() -> dict[str, list[str]]:
    """Each `dorny/paths-filter` entry's key and the globs it watches."""

    text = WORKFLOW.read_text(encoding="utf-8")
    block = text.split("filters: |\n", 1)[1].split("- name:", 1)[0]
    return {
        key: re.findall(r"'([^']*)'", globs)
        for key, globs in re.findall(r"^\s+([\w-]+): \[(.*)\]\s*$", block, re.MULTILINE)
    }


def _push_paths() -> list[str]:
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"^  push:\n(?:.*\n)*?    paths:\n((?:      - '[^']*'\n)+)", text, re.MULTILINE)
    assert match, f"{WORKFLOW} has no push.paths list"
    return re.findall(r"'([^']*)'", match.group(1))


def _watches(pattern: str, path: str) -> bool:
    """Whether a filter glob matches ``path``, for the two forms the workflow uses."""

    if pattern.endswith("/**"):
        return path.startswith(pattern[:-2])
    return pattern == path


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
            found[_normalise(name)] = declared["project"]
    return found


def _internal_dependencies(project: dict, repository: dict[str, dict]) -> dict[str, str]:
    """Repository distributions ``project`` requires, each with the extra that adds it.

    An extra counts: a consumer installing it resolves the dependency from
    PyPI exactly as it would a required one. Required dependencies map to "".
    """

    own = _normalise(project["name"])
    found: dict[str, str] = {}
    sources = [("", project.get("dependencies", []))]
    sources += sorted(project.get("optional-dependencies", {}).items())
    for extra, requirements in sources:
        for requirement in requirements:
            name = _normalise(_REQUIREMENT_NAME.match(requirement).group(1))
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


@pytest.mark.parametrize("package", _workflow_packages(), ids=lambda entry: str(entry["key"]))
def test_a_published_package_depends_only_on_published_packages(
    package: dict[str, object],
) -> None:
    """A wheel on PyPI resolves its repository dependencies from PyPI too.

    The build never notices a missing one: `uv build --no-sources` installs
    only the build backend. The first sign is an install that cannot resolve,
    found by whoever installs the package rather than by whoever published it.
    """

    repository = _repository_distributions()
    project = repository[_normalise(str(package["dist"]))]
    published = {_normalise(str(entry["dist"])) for entry in _workflow_packages()}
    missing = {
        name: extra
        for name, extra in _internal_dependencies(project, repository).items()
        if name not in published
    }
    assert not missing, (
        f"{package['dist']} depends on repository distributions the workflow does not publish: "
        + ", ".join(f"{name} (extra {extra})" if extra else name for name, extra in sorted(missing.items()))
    )


@pytest.mark.parametrize("package", _packages(), ids=lambda entry: str(entry["key"]))
def test_a_manifest_package_depends_only_on_manifest_packages(
    package: dict[str, object],
) -> None:
    """The registry push uploads the manifest's set and nothing else.

    A distribution it pushes whose repository dependency it does not push is
    uninstallable from that registry, for the same reason as on PyPI.
    """

    repository = _repository_distributions()
    project = repository[_normalise(str(package["dist"]))]
    pushed = {_normalise(str(entry["dist"])) for entry in _packages()}
    missing = {
        name: extra
        for name, extra in _internal_dependencies(project, repository).items()
        if name not in pushed
    }
    assert not missing, (
        f"{package['dist']} depends on repository distributions {MANIFEST.name} omits: "
        + ", ".join(f"{name} (extra {extra})" if extra else name for name, extra in sorted(missing.items()))
    )


def test_the_manifest_lists_each_distribution_after_its_dependencies() -> None:
    """The registry push uploads in manifest order and stops at the first failure.

    Listing a dependency later than its dependent leaves the registry, for the
    length of a push or after a failed one, holding a distribution it cannot
    install.
    """

    repository = _repository_distributions()
    order = [_normalise(str(entry["dist"])) for entry in _packages()]
    position = {name: index for index, name in enumerate(order)}
    late = [
        f"{name} precedes its dependency {dependency}"
        for name in order
        for dependency in _internal_dependencies(repository[name], repository)
        if position.get(dependency, -1) > position[name]
    ]
    assert not late, "; ".join(late)


def test_each_table_entry_names_the_distribution_at_its_path() -> None:
    repository = _repository_distributions()
    for entry in [*_workflow_packages(), *_packages()]:
        pyproject = REPO_ROOT / str(entry["path"]) / "pyproject.toml"
        assert pyproject.is_file(), f"{entry['key']}: {pyproject} does not exist"
        declared = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["name"]
        assert _normalise(declared) == _normalise(str(entry["dist"])), (
            f"{entry['key']}: {entry['path']} declares {declared}, not {entry['dist']}"
        )
        assert _normalise(declared) in repository


def test_every_published_package_is_watched_by_its_filter_and_the_push_trigger() -> None:
    """A package nothing watches never publishes on a version bump.

    The push trigger's `paths` gate the whole run before any filter is read,
    so a package outside them is as unpublished as one with no filter.
    """

    filters = _workflow_filters()
    push_paths = _push_paths()
    packages = _workflow_packages()
    assert set(filters) == {str(entry["key"]) for entry in packages}, (
        "path filters and the PACKAGES table name different keys"
    )
    for entry in packages:
        key, manifest = str(entry["key"]), f"{entry['path']}/pyproject.toml"
        globs = filters[key]
        assert ".github/workflows/publish-pypi.yml" in globs, f"{key} does not watch the workflow"
        assert any(_watches(glob, manifest) for glob in globs), f"{key}'s filter misses {manifest}"
        assert any(_watches(glob, manifest) for glob in push_paths), (
            f"push.paths do not cover {manifest}, so {entry['dist']} never triggers a run"
        )


def test_the_release_guide_lists_exactly_the_published_packages() -> None:
    rows = _releasing_rows()
    table = {str(entry["dist"]): str(entry["path"]) for entry in _workflow_packages()}
    assert {dist: path for dist, (path, _) in rows.items()} == table


@pytest.mark.parametrize("package", _workflow_packages(), ids=lambda entry: str(entry["key"]))
def test_the_release_guide_states_each_package_internal_deps(package: dict[str, object]) -> None:
    rows = _releasing_rows()
    if str(package["dist"]) not in rows:
        pytest.fail(f"{package['dist']} has no row in {RELEASING.name}")
    repository = _repository_distributions()
    _, cell = rows[str(package["dist"])]
    stated = {_normalise(name) for name in re.findall(r"`([^`]+)`", cell)} & set(repository)
    declared = set(_internal_dependencies(repository[_normalise(str(package["dist"]))], repository))
    assert stated == declared, (
        f"{RELEASING.name} states {sorted(stated)} for {package['dist']}; "
        f"its pyproject declares {sorted(declared)}"
    )
