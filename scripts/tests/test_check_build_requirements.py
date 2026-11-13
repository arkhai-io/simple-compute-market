"""The build-requirement pin check, over synthetic trees."""

from __future__ import annotations

from pathlib import Path

import pytest

from check_build_requirements import main, problems

EXPORT = ("export UV_BUILD_CONSTRAINT := $(or $(wildcard $(abspath {path})),"
          "$(error {path} not found))\n")
BUILD = "build:\n\tuv build --wheel --out-dir $(DIST_DIR)\n"


def _tree(root: Path, constraints: str = "hatchling==1.33.0\n",
          requires: str = '["hatchling"]', makefile: str | None = None) -> None:
    (root / "build-constraints.txt").write_text(constraints, encoding="utf-8")
    (root / "kit" / "site").mkdir(parents=True)
    (root / "kit" / "site" / "pyproject.toml").write_text(
        f'[project]\nname = "arkhai-kit-site"\nversion = "1.0.0"\n'
        f'[build-system]\nrequires = {requires}\nbuild-backend = "hatchling.build"\n',
        encoding="utf-8")
    (root / "kit" / "site" / "Makefile").write_text(
        makefile if makefile is not None
        else EXPORT.format(path="../../build-constraints.txt") + BUILD, encoding="utf-8")


def test_a_pinned_backend_and_a_constrained_build_pass(tmp_path: Path) -> None:
    _tree(tmp_path)

    assert problems(tmp_path) == []


def test_an_unpinned_backend_is_refused(tmp_path: Path) -> None:
    _tree(tmp_path, constraints="setuptools==80.0.0\n")

    assert problems(tmp_path) == [
        "kit/site/pyproject.toml: requires 'hatchling' to build, which "
        "build-constraints.txt does not pin"]


def test_an_unpinned_plugin_is_refused(tmp_path: Path) -> None:
    _tree(tmp_path, requires='["hatchling", "hatch-vcs>=0.4"]')

    assert problems(tmp_path) == [
        "kit/site/pyproject.toml: requires 'hatch-vcs>=0.4' to build, which "
        "build-constraints.txt does not pin"]


def test_a_requirement_is_matched_by_its_normalised_name(tmp_path: Path) -> None:
    _tree(tmp_path, constraints="Hatchling==1.33.0\nhatch_vcs==0.4.0\n",
          requires='["hatchling", "hatch.vcs"]')

    assert problems(tmp_path) == []


def test_a_uv_build_without_the_constraint_is_refused(tmp_path: Path) -> None:
    _tree(tmp_path, makefile=BUILD)

    assert problems(tmp_path) == [
        "kit/site/Makefile: runs uv build without exporting UV_BUILD_CONSTRAINT from "
        "build-constraints.txt"]


def test_a_constraint_path_that_does_not_reach_the_declaration_is_refused(
        tmp_path: Path) -> None:
    _tree(tmp_path, makefile=EXPORT.format(path="../build-constraints.txt") + BUILD)

    assert problems(tmp_path) == [
        "kit/site/Makefile: runs uv build without exporting UV_BUILD_CONSTRAINT from "
        "build-constraints.txt"]


def test_a_makefile_running_no_uv_build_needs_no_constraint(tmp_path: Path) -> None:
    _tree(tmp_path, makefile="test:\n\tuv run pytest\n# uv build in a comment\n")

    assert problems(tmp_path) == []


@pytest.mark.parametrize("line", ["hatchling>=1.33", "hatchling", "hatchling == 1.33.0"])
def test_a_declaration_line_that_is_not_an_exact_pin_is_refused(tmp_path: Path,
                                                                line: str) -> None:
    _tree(tmp_path, constraints=f"# the backend\n{line}\n")

    assert problems(tmp_path)[0] == (
        f"build-constraints.txt:2: {line!r} is not an exact pin, <name>==<version>")


def test_a_name_pinned_twice_is_refused(tmp_path: Path) -> None:
    _tree(tmp_path, constraints="hatchling==1.33.0\nHatchling==1.34.0\n")

    assert problems(tmp_path) == ["build-constraints.txt:2: Hatchling is pinned twice"]


def test_a_project_that_is_not_valid_toml_is_refused(tmp_path: Path) -> None:
    _tree(tmp_path)
    (tmp_path / "kit" / "site" / "pyproject.toml").write_text("[project\n", encoding="utf-8")

    assert problems(tmp_path)[0].startswith("kit/site/pyproject.toml: is not valid TOML")


def test_a_build_requirement_naming_no_package_is_refused(tmp_path: Path) -> None:
    _tree(tmp_path, requires='["hatchling", ">=1.0"]')

    assert problems(tmp_path) == [
        "kit/site/pyproject.toml: build requirement '>=1.0' names no package"]


def test_a_missing_declaration_is_refused(tmp_path: Path) -> None:
    _tree(tmp_path)
    (tmp_path / "build-constraints.txt").unlink()

    assert problems(tmp_path) == ["build-constraints.txt is missing"]


def test_this_tree_passes(capsys: pytest.CaptureFixture[str]) -> None:
    assert main() == 0
    assert capsys.readouterr().out.startswith("OK: ")
