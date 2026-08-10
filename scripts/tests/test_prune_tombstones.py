"""The tombstone prune utility.

This deletes files and directories, so the cases that matter most are the ones
where it must *not* act: a live module that merely mentions the marker, a
documentation example, and a directory outside the source roots.
"""

from __future__ import annotations

from pathlib import Path

import prune_tombstones as prune


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "domains" / "thing").mkdir(parents=True)
    return tmp_path


def test_find_tombstones_selects_only_whole_file_tombstones(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    d = root / "domains" / "thing"
    (d / "gone.py").write_text("# TOMBSTONE: moved.\n", encoding="utf-8")
    (d / "live.py").write_text("# TOMBSTONE: stale\n\nX = 1\n", encoding="utf-8")
    (d / "doc.md").write_text("Example:\n\n```\n# TOMBSTONE: reason\n```\n", encoding="utf-8")

    found = {p.name for p in prune.find_tombstones(root)}

    assert found == {"gone.py"}


def test_skip_dirs_are_not_walked(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    cached = root / "domains" / "thing" / "__pycache__"
    cached.mkdir()
    (cached / "gone.py").write_text("# TOMBSTONE: moved.\n", encoding="utf-8")

    assert prune.find_tombstones(root) == []


def test_a_directory_holding_only_build_artifacts_is_vacant(tmp_path: Path) -> None:
    d = tmp_path / "pkg"
    (d / "__pycache__").mkdir(parents=True)
    (d / "__pycache__" / "x.pyc").write_bytes(b"\x00")

    assert prune._is_vacant(d)


def test_vacancy_is_recursive(tmp_path: Path) -> None:
    """A husk survived once because its empty subpackage counted as content."""
    nested = tmp_path / "pkg" / "sub" / "deeper"
    nested.mkdir(parents=True)

    assert prune._is_vacant(tmp_path / "pkg")


def test_a_directory_holding_source_is_not_vacant(tmp_path: Path) -> None:
    d = tmp_path / "pkg"
    d.mkdir()
    (d / "mod.py").write_text("X = 1\n", encoding="utf-8")

    assert not prune._is_vacant(d)


def test_a_directory_holding_a_tombstone_is_not_yet_vacant(tmp_path: Path) -> None:
    """Vacancy is about what remains, so pruning must happen first."""
    d = tmp_path / "pkg"
    d.mkdir()
    (d / "gone.py").write_text("# TOMBSTONE: moved.\n", encoding="utf-8")

    assert not prune._is_vacant(d)


def test_the_source_roots_are_the_sweep_boundary() -> None:
    """A deletion utility must not be able to reach an arbitrary path."""
    assert "domains" in prune.SOURCE_ROOTS
    for outside in ("", ".", "/", "..", "docs", "openspec", "scripts"):
        assert outside not in prune.SOURCE_ROOTS
