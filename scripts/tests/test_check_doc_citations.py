"""A change's untracked review records are not checked for citations."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "check_doc_citations", Path(__file__).resolve().parents[1] / "check_doc_citations.py"
)
assert _SPEC and _SPEC.loader
checker = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(checker)


def _change(root: Path) -> Path:
    change = root / "openspec/changes/shape-bounds"
    (change / "reviews/transcripts").mkdir(parents=True)
    (change / "specs/kit").mkdir(parents=True)
    for name in ("why", "specs/kit/spec", "reviews/03-review", "reviews/transcripts/03-note"):
        (change / f"{name}.md").write_text("cites openspec/changes/gone.md\n", "utf-8")
    return change


def test_review_records_are_not_documents_of_a_change(tmp_path: Path) -> None:
    change = _change(tmp_path)

    found = checker.documents(tmp_path, "shape-bounds")

    assert [path.relative_to(change).as_posix() for path in found] == [
        "specs/kit/spec.md", "why.md"]


def test_repository_view_also_skips_review_records(tmp_path: Path) -> None:
    _change(tmp_path)

    found = checker.documents(tmp_path)

    assert not any("reviews" in path.parts for path in found)
    assert len(found) == 2


def test_a_change_is_found_by_name_once_archived(tmp_path: Path) -> None:
    change = _change(tmp_path)
    archived = tmp_path / "openspec/changes/archive/2026-10-14-shape-bounds"
    archived.parent.mkdir()
    change.rename(archived)

    found = checker.documents(tmp_path, "shape-bounds")

    assert [path.relative_to(archived).as_posix() for path in found] == [
        "specs/kit/spec.md", "why.md"]


def test_an_unknown_change_is_refused(tmp_path: Path) -> None:
    _change(tmp_path)

    with pytest.raises(SystemExit, match="no change 'other'"):
        checker.documents(tmp_path, "other")


def test_an_archived_change_citing_its_own_unarchived_path_resolves(tmp_path: Path) -> None:
    archived = tmp_path / "openspec/changes/archive/2026-10-14-shape-bounds"
    archived.mkdir(parents=True)
    (archived / "notes.md").write_text("x", "utf-8")
    (archived / "why.md").write_text(
        "see openspec/changes/shape-bounds/notes.md and openspec/changes/shape-bounds/gone.md,"
        " and docs/missing.md\n",
        "utf-8")

    problems = checker.unresolvable(tmp_path, "shape-bounds")

    assert sorted(cited for _, cited, _ in problems) == [
        "docs/missing.md", "openspec/changes/shape-bounds/gone.md"]


def test_an_active_change_citing_its_own_path_must_resolve_as_written(tmp_path: Path) -> None:
    change = tmp_path / "openspec/changes/shape-bounds"
    change.mkdir(parents=True)
    (change / "why.md").write_text("see openspec/changes/shape-bounds/gone.md\n", "utf-8")

    assert [cited for _, cited, _ in checker.unresolvable(tmp_path, "shape-bounds")] == [
        "openspec/changes/shape-bounds/gone.md"]
