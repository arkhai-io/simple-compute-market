"""A change is found by its name whether it is active or archived."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "find_change", Path(__file__).resolve().parents[1] / "find_change.py"
)
assert _SPEC and _SPEC.loader
finder = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(finder)


def _tree(root: Path, *directories: str) -> Path:
    for directory in directories:
        (root / "openspec/changes" / directory).mkdir(parents=True)
    return root


def test_an_active_change_is_its_own_directory(tmp_path: Path) -> None:
    root = _tree(tmp_path, "shape-bounds")

    assert finder.change_directory(root, "shape-bounds") == root / "openspec/changes/shape-bounds"


def test_an_archived_change_is_found_under_its_dated_directory(tmp_path: Path) -> None:
    root = _tree(tmp_path, "archive/2026-10-14-shape-bounds", "archive/2026-10-01-other")

    assert (finder.change_directory(root, "shape-bounds")
            == root / "openspec/changes/archive/2026-10-14-shape-bounds")


def test_an_active_change_is_preferred_to_an_archived_one(tmp_path: Path) -> None:
    root = _tree(tmp_path, "shape-bounds", "archive/2026-10-14-shape-bounds")

    assert finder.change_directory(root, "shape-bounds") == root / "openspec/changes/shape-bounds"


def test_a_missing_change_is_refused(tmp_path: Path) -> None:
    root = _tree(tmp_path, "other", "archive/2026-10-14-other")

    with pytest.raises(finder.ChangeNotFound, match="no change 'shape-bounds'"):
        finder.change_directory(root, "shape-bounds")


def test_a_change_archived_twice_is_refused_naming_both(tmp_path: Path) -> None:
    root = _tree(tmp_path, "archive/2026-09-01-shape-bounds", "archive/2026-10-14-shape-bounds")

    with pytest.raises(finder.ChangeNotFound, match="more than once") as raised:
        finder.change_directory(root, "shape-bounds")

    assert "2026-09-01-shape-bounds" in str(raised.value)
    assert "2026-10-14-shape-bounds" in str(raised.value)


def test_a_name_ending_another_archived_name_does_not_match_it(tmp_path: Path) -> None:
    root = _tree(tmp_path, "archive/2026-10-14-capacity-shape-bounds")

    with pytest.raises(finder.ChangeNotFound):
        finder.change_directory(root, "shape-bounds")


@pytest.mark.parametrize("name", ["", "archive", "archive/2026-10-14-shape-bounds", "..", "."])
def test_what_is_not_a_change_name_is_refused(tmp_path: Path, name: str) -> None:
    root = _tree(tmp_path, "archive/2026-10-14-shape-bounds")

    with pytest.raises(finder.ChangeNotFound):
        finder.change_directory(root, name)


def test_the_command_prints_the_relative_directory(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _tree(tmp_path, "archive/2026-10-14-shape-bounds")

    assert finder.main(["shape-bounds"], root) == 0
    assert capsys.readouterr().out == "openspec/changes/archive/2026-10-14-shape-bounds\n"


def test_the_command_names_a_missing_change_and_fails(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _tree(tmp_path, "other")

    assert finder.main(["shape-bounds"], root) == 1
    assert "no change 'shape-bounds'" in capsys.readouterr().err


def test_active_only_refuses_an_archived_change(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _tree(tmp_path, "shape-bounds", "archive/2026-10-14-other")

    assert finder.main(["--active", "shape-bounds"], root) == 0
    assert finder.main(["--active", "other"], root) == 1
    assert "is archived" in capsys.readouterr().err


def test_archived_only_refuses_an_active_change(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _tree(tmp_path, "shape-bounds", "archive/2026-10-14-other")

    assert finder.main(["--archived", "other"], root) == 0
    assert finder.main(["--archived", "shape-bounds"], root) == 1
    assert "is not archived" in capsys.readouterr().err


def test_the_two_restrictions_cannot_be_combined(tmp_path: Path) -> None:
    root = _tree(tmp_path, "shape-bounds")

    assert finder.main(["--active", "--archived", "shape-bounds"], root) == 2
    assert finder.main(["--active", "--records", "shape-bounds"], root) == 2


# A change's records.

def test_an_active_changes_records_are_its_reviews(tmp_path: Path) -> None:
    root = _tree(tmp_path, "shape-bounds/reviews")

    assert finder.records_directory(root, "shape-bounds") == (
        root / "openspec/changes/shape-bounds/reviews")


def test_records_beside_an_active_directory_without_them_are_the_archives(
        tmp_path: Path) -> None:
    # The owner's workspace: the change's active directory from its branch, and the
    # archive copy its clone's cleanup made, which alone holds the records.
    root = _tree(tmp_path, "shape-bounds", "archive/2026-10-14-shape-bounds/reviews",
                 "archive/2026-09-01-shape-bounds")

    assert finder.records_directory(root, "shape-bounds") == (
        root / "openspec/changes/archive/2026-10-14-shape-bounds/reviews")


def test_a_change_with_no_records_here_has_none(tmp_path: Path) -> None:
    root = _tree(tmp_path, "shape-bounds", "archive/2026-10-14-shape-bounds")

    assert finder.records_directory(root, "shape-bounds") is None


def test_records_archived_twice_are_refused(tmp_path: Path) -> None:
    root = _tree(tmp_path, "archive/2026-09-01-shape-bounds/reviews",
                 "archive/2026-10-14-shape-bounds/reviews")

    with pytest.raises(finder.ChangeNotFound, match="more than once"):
        finder.records_directory(root, "shape-bounds")


def test_records_are_looked_for_in_the_checkout_before_the_workspace(tmp_path: Path) -> None:
    here = _tree(tmp_path / "clone", "shape-bounds/reviews")
    there = _tree(tmp_path / "work", "archive/2026-10-14-shape-bounds/reviews",
                  "archive/2026-10-14-other/reviews")
    workspace = {here: there}.get

    assert finder.find_records(here, "shape-bounds", workspace) == (
        here / "openspec/changes/shape-bounds/reviews")
    assert finder.find_records(here, "other", workspace) == (
        there / "openspec/changes/archive/2026-10-14-other/reviews")


def test_records_outside_a_clone_are_looked_for_in_the_checkout_alone(tmp_path: Path) -> None:
    root = _tree(tmp_path, "shape-bounds")

    with pytest.raises(finder.ChangeNotFound) as raised:
        finder.find_records(root, "shape-bounds", lambda _: None)

    assert "workspace" not in str(raised.value)
