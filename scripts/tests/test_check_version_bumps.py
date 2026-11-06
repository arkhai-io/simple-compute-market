"""A package a change bumps moves one SemVer step from its version where the change
began, however many times the branch bumped it."""

from __future__ import annotations

from pathlib import Path

import pytest

import check_version_bumps as checker
from change_diff import merge_base
from change_diff_fixtures import change_repo, commit, write


def _pyproject(version: str, name: str = "arkhai-kit-pools") -> str:
    return f'[project]\nname = "{name}"\nversion = "{version}"\n'


@pytest.mark.parametrize("new", ["0.4.0", "0.4.1", "0.5.0", "1.0.0"])
def test_one_step_or_none_passes(new: str) -> None:
    assert checker.bump_problem("pkg", "0.4.0", new) is None


@pytest.mark.parametrize("new", ["0.4.2", "0.6.0", "0.5.1", "2.0.0", "0.3.9"])
def test_more_than_one_step_names_the_package_and_both_versions(new: str) -> None:
    problem = checker.bump_problem("pkg", "0.4.0", new)

    assert problem is not None and problem.startswith(f"pkg: 0.4.0 → {new} is more than")


def test_a_version_that_is_not_major_minor_patch_is_named() -> None:
    assert "not a MAJOR.MINOR.PATCH" in checker.bump_problem("pkg", "0.4.0", "0.5.0rc1")


def test_a_bump_replaced_by_a_larger_one_on_the_branch_passes(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = change_repo(tmp_path, monkeypatch, {"kit/pools/pyproject.toml": _pyproject("0.4.0")})
    commit(repo, {"kit/pools/pyproject.toml": _pyproject("0.4.1")}, "a fix")
    commit(repo, {"kit/pools/pyproject.toml": _pyproject("0.5.0")}, "an incompatible edit")

    assert checker.problems(repo, merge_base(repo)) == []


def test_a_package_bumped_twice_fails_naming_it_and_both_versions(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    repo = change_repo(tmp_path, monkeypatch, {
        "kit/pools/pyproject.toml": _pyproject("0.4.0"),
        "kit/sites/pyproject.toml": _pyproject("0.2.0", "arkhai-kit-sites")})
    commit(repo, {"kit/pools/pyproject.toml": _pyproject("0.4.1")})
    write(repo, "kit/pools/pyproject.toml", _pyproject("0.4.2"))
    write(repo, "kit/new/pyproject.toml", _pyproject("0.9.0", "arkhai-kit-new"))

    assert checker.main([], root=repo) == 1
    assert capsys.readouterr().out.splitlines()[0] == (
        "arkhai-kit-pools (kit/pools/pyproject.toml): 0.4.0 → 0.4.2 is more than one "
        "version step; bump once, to one of 0.4.1, 0.5.0, 1.0.0")
