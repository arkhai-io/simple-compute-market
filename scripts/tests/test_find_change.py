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
